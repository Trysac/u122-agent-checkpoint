"""Checkpoint and resume agent runs from an append-only JSONL log."""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, TypeVar

__all__ = [
    "CheckpointError",
    "CheckpointStore",
    "RunLog",
    "__version__",
    "canonical_hash",
]

__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.addHandler(logging.NullHandler())

ErrorCode = Literal[
    "divergence",
    "not_serializable",
    "run_completed",
    "locked",
    "entry_too_large",
    "too_many_steps",
    "invalid_run_id",
    "corrupt_log",
]

RunStatus = Literal["running", "completed", "failed"]
DivergenceAction = Literal["raise", "truncate"]

T = TypeVar("T")

_RUN_ID_REGEX = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_MAX_ERROR_MSG_LEN = 200


def _sanitize_msg(msg: str) -> str:
    if len(msg) > _MAX_ERROR_MSG_LEN:
        return msg[:_MAX_ERROR_MSG_LEN] + "..."
    return msg


class CheckpointError(Exception):
    """Base exception for all agent_checkpoint errors."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        step_index: int | None = None,
    ) -> None:
        self.code: ErrorCode = code
        self.step_index: int | None = step_index
        default_msg = f"Checkpoint error [{code}]"
        if step_index is not None:
            default_msg += f" at step {step_index}"
        if message:
            default_msg += f": {_sanitize_msg(message)}"
        super().__init__(default_msg)


def _serialize_canonical(value: Any) -> str:
    """Serialize value to canonical JSON or raise CheckpointError with 'not_serializable'."""
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
            ensure_ascii=False,
        )
    except (TypeError, ValueError) as err:
        raise CheckpointError("not_serializable", str(err)) from err


def canonical_hash(value: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON representation of value."""
    payload = _serialize_canonical(value)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class RunLog:
    """Context manager and interface for an open agent execution run."""

    def __init__(
        self,
        store: CheckpointStore,
        run_id: str,
        log_path: Path,
        lock_path: Path,
        on_divergence: DivergenceAction,
        lock_fd: int | None = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._log_path = log_path
        self._lock_path = lock_path
        self._on_divergence: DivergenceAction = on_divergence
        self._lock_fd: int | None = lock_fd
        self._closed: bool = False
        self._records: list[dict[str, Any]] = []
        self._status: RunStatus = "running"
        self._current_index: int = 0
        self._file: Any | None = None

        self._load_and_repair()

    @property
    def status(self) -> RunStatus:
        """Current status of the run: 'running', 'completed', or 'failed'."""
        return self._status

    def _load_and_repair(self) -> None:
        if not self._log_path.exists():
            self._file = open(self._log_path, "a+", encoding="utf-8")  # noqa: SIM115
            return

        # Read line by line (the spec): memory is bounded by the longest record.
        valid_records: list[dict[str, Any]] = []
        valid_byte_length = 0
        total_bytes = 0
        with open(self._log_path, "rb") as f:
            for i, raw in enumerate(f):
                total_bytes += len(raw)
                if raw == b"\n":
                    valid_byte_length += 1
                    continue
                try:
                    record = json.loads(raw.rstrip(b"\n").decode("utf-8"))
                except Exception as err:
                    if not raw.endswith(b"\n"):  # the last line without a newline is a torn write
                        logger.warning(
                            "Detected torn tail line in run %s; truncating", self._run_id
                        )
                        break
                    raise CheckpointError("corrupt_log", f"Line {i} corrupted: {err}") from err

                if not isinstance(record, dict) or record.get("v") != 1:
                    raise CheckpointError("corrupt_log", f"Line {i} is not a valid v1 record")

                valid_records.append(record)
                valid_byte_length += len(raw)

        if total_bytes == 0:
            self._file = open(self._log_path, "a+", encoding="utf-8")  # noqa: SIM115
            return

        if valid_byte_length < total_bytes:
            with open(self._log_path, "r+b") as f:
                f.truncate(valid_byte_length)
                f.flush()
                os.fsync(f.fileno())

        self._records = valid_records
        terminal = None
        for rec in self._records:
            if "status" in rec:
                terminal = rec["status"]
                break

        if terminal in ("completed", "failed"):
            self._status = terminal
        else:
            self._status = "running"

        self._file = open(self._log_path, "a+", encoding="utf-8")  # noqa: SIM115

    def _check_not_completed(self) -> None:
        if self._status in ("completed", "failed"):
            raise CheckpointError(
                "run_completed",
                f"Run '{self._run_id}' has already terminated with status '{self._status}'",
                step_index=self._current_index,
            )

    def _truncate_history_from(self, index: int) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None

        surviving = self._records[:index]
        tmp_path = self._log_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            for rec in surviving:
                line = _serialize_canonical(rec)
                f.write(line + "\n")
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, self._log_path)
        self._records = surviving
        self._file = open(self._log_path, "a+", encoding="utf-8")  # noqa: SIM115

    def step(self, name: str, inputs: Any, fn: Callable[[], T]) -> T:
        """Replay recorded step output or invoke fn and record the step."""
        if self._closed:
            raise CheckpointError("locked", "RunLog is already closed")
        self._check_not_completed()

        if self._current_index >= self._store.max_steps:
            raise CheckpointError(
                "too_many_steps",
                f"Step index {self._current_index} exceeds maximum steps {self._store.max_steps}",
                step_index=self._current_index,
            )

        step_hash = canonical_hash([name, inputs])

        if self._current_index < len(self._records):
            recorded = self._records[self._current_index]
            if "status" in recorded:
                raise CheckpointError(
                    "run_completed",
                    f"Encountered terminal state at step {self._current_index}",
                    step_index=self._current_index,
                )

            recorded_name = recorded.get("name")
            recorded_hash = recorded.get("hash")
            if recorded_name == name and recorded_hash == step_hash:
                result: T = recorded["output"]
                self._store._dispatch_event(
                    {
                        "run_id": self._run_id,
                        "step": self._current_index,
                        "name": name,
                        "replayed": True,
                    }
                )
                self._current_index += 1
                return result

            if self._on_divergence == "raise":
                raise CheckpointError(
                    "divergence",
                    f"Divergence detected at step {self._current_index}",
                    step_index=self._current_index,
                )
            else:
                self._truncate_history_from(self._current_index)

        output = fn()

        line = _serialize_canonical(output)
        line_bytes = (line + "\n").encode("utf-8")
        if len(line_bytes) > self._store.max_entry_bytes:
            raise CheckpointError(
                "entry_too_large",
                f"Step output byte length {len(line_bytes)} exceeds limit "
                f"{self._store.max_entry_bytes}",
                step_index=self._current_index,
            )

        record = {
            "v": 1,
            "i": self._current_index,
            "name": name,
            "hash": step_hash,
            "output": output,
        }
        line = _serialize_canonical(record)

        if self._file is None:
            raise RuntimeError("File not opened")
        self._file.write(line + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

        self._records.append(record)
        self._store._dispatch_event(
            {
                "run_id": self._run_id,
                "step": self._current_index,
                "name": name,
                "replayed": False,
            }
        )
        self._current_index += 1
        return output

    def complete(self, result: Any = None) -> None:
        """Record terminal completion of the run."""
        if self._closed:
            raise CheckpointError("locked", "RunLog is already closed")
        self._check_not_completed()

        record = {
            "v": 1,
            "status": "completed",
            "result": result,
        }
        line = _serialize_canonical(record)
        line_bytes = (line + "\n").encode("utf-8")
        if len(line_bytes) > self._store.max_entry_bytes:
            raise CheckpointError(
                "entry_too_large",
                f"Terminal entry exceeds limit {self._store.max_entry_bytes}",
                step_index=self._current_index,
            )

        if self._file is None:
            raise RuntimeError("File not opened")
        self._file.write(line + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

        self._records.append(record)
        self._status = "completed"
        self._store._dispatch_event(
            {
                "run_id": self._run_id,
                "status": "completed",
            }
        )

    def fail(self, code: str) -> None:
        """Record terminal failure of the run."""
        if self._closed:
            raise CheckpointError("locked", "RunLog is already closed")
        self._check_not_completed()

        record = {
            "v": 1,
            "status": "failed",
            "code": code,
        }
        line = _serialize_canonical(record)
        line_bytes = (line + "\n").encode("utf-8")
        if len(line_bytes) > self._store.max_entry_bytes:
            raise CheckpointError(
                "entry_too_large",
                f"Terminal failure entry exceeds limit {self._store.max_entry_bytes}",
                step_index=self._current_index,
            )

        if self._file is None:
            raise RuntimeError("File not opened")
        self._file.write(line + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

        self._records.append(record)
        self._status = "failed"
        self._store._dispatch_event(
            {
                "run_id": self._run_id,
                "status": "failed",
            }
        )

    def close(self) -> None:
        """Close run log file and release lock."""
        if self._closed:
            return
        self._closed = True
        try:
            if self._file is not None:
                self._file.close()
                self._file = None
        finally:
            if self._lock_fd is not None:
                with contextlib.suppress(OSError):
                    os.close(self._lock_fd)
                self._lock_fd = None
            if self._lock_path.exists():
                with contextlib.suppress(OSError):
                    os.remove(self._lock_path)

    def __enter__(self) -> RunLog:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self.close()


class CheckpointStore:
    """Filesystem-backed store for agent checkpoint logs."""

    def __init__(
        self,
        directory: str | os.PathLike[str],
        *,
        max_entry_bytes: int = 1_048_576,
        max_steps: int = 10_000,
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self.directory = Path(directory)
        self.max_entry_bytes = max_entry_bytes
        self.max_steps = max_steps
        self.on_event = on_event
        self.directory.mkdir(parents=True, exist_ok=True)

    def _dispatch_event(self, event: dict[str, Any]) -> None:
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                logger.exception("Error in on_event listener")

    def _validate_run_id(self, run_id: str) -> None:
        if not isinstance(run_id, str) or not _RUN_ID_REGEX.match(run_id):
            raise CheckpointError("invalid_run_id", f"Invalid run ID: {run_id!r}")

    def open(
        self,
        run_id: str,
        *,
        on_divergence: DivergenceAction = "raise",
        break_lock: bool = False,
    ) -> RunLog:
        """Open or create a run log for execution or replay."""
        self._validate_run_id(run_id)
        if on_divergence not in ("raise", "truncate"):
            raise ValueError(f"Invalid on_divergence mode: {on_divergence}")

        log_path = self.directory / f"{run_id}.jsonl"
        lock_path = self.directory / f"{run_id}.lock"

        if break_lock and lock_path.exists():
            with contextlib.suppress(OSError):
                os.remove(lock_path)

        # Close the file descriptor immediately after creation so the file is not held open
        # by an open handle (which on Windows prevents deletion by break_lock or os.remove).
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
            fd = os.open(lock_path, flags, 0o600)
            os.close(fd)
        except FileExistsError as err:
            raise CheckpointError("locked", f"Run '{run_id}' is locked by another process") from err

        try:
            return RunLog(
                store=self,
                run_id=run_id,
                log_path=log_path,
                lock_path=lock_path,
                on_divergence=on_divergence,
            )
        except Exception:
            if lock_path.exists():
                with contextlib.suppress(OSError):
                    os.remove(lock_path)
            raise

    def list_runs(self) -> list[tuple[str, str]]:
        """List all runs in the directory and their statuses, sorted by run ID."""
        runs: list[tuple[str, str]] = []
        if not self.directory.exists():
            return runs

        for entry in self.directory.iterdir():
            if entry.is_file() and entry.suffix == ".jsonl":
                run_id = entry.stem
                if not _RUN_ID_REGEX.match(run_id):
                    continue
                status: RunStatus = "running"
                try:
                    with open(entry, "rb") as f:
                        for line in f:  # line by line: memory is bounded by one record
                            stripped = line.strip()
                            if not stripped:
                                continue
                            with contextlib.suppress(Exception):
                                data = json.loads(stripped.decode("utf-8"))
                                if isinstance(data, dict) and data.get("status") in (
                                    "completed",
                                    "failed",
                                ):
                                    status = data["status"]
                except OSError:
                    pass
                runs.append((run_id, status))

        runs.sort(key=lambda item: item[0])
        return runs
