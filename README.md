# agent-checkpoint

[![CI](https://github.com/Trysac/u122-agent-checkpoint/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u122-agent-checkpoint/actions)

Checkpoint and resume agent runs from an append-only JSONL log: recorded steps replay without re-execution, divergence detection, torn-tail recovery and terminal states.

## The Problem

Long agent runs fail halfway through on a timeout or a crash, and restarting them repeats every LLM call and tool side effect already paid for. Resuming needs a log of completed steps keyed by their inputs, so that the rerun returns recorded results until it reaches new work. This library records steps to an append-only file and replays them deterministically on resume.

## Installation

```bash
pip install trysac-agent-checkpoint
```

## Usage Example

```python
from agent_checkpoint import CheckpointStore

store = CheckpointStore(".checkpoints")
with store.open("run-001") as log:
    data = log.step("fetch", {"url": "https://example.org"}, lambda: "fetched")
    result = log.step("process", {"payload": data}, lambda: f"processed: {data}")
    log.complete(result)

assert store.list_runs() == [("run-001", "completed")]
```

## Public API Summary

- `CheckpointStore(directory: str | os.PathLike, *, max_entry_bytes: int = 1_048_576, max_steps: int = 10_000, on_event: Callable[[dict], None] | None = None)`: Filesystem-backed storage container.
- `CheckpointStore.open(run_id: str, *, on_divergence: Literal['raise','truncate'] = 'raise', break_lock: bool = False) -> RunLog`: Opens or creates a run log. `run_id` must match `^[A-Za-z0-9_-]{1,64}$`.
- `CheckpointStore.list_runs() -> list[tuple[str, str]]`: Lists all runs and their statuses, sorted by ID.
- `RunLog.step(name: str, inputs: Any, fn: Callable[[], T]) -> T`: Executes `fn` and records the result if not replaying.
- `RunLog.complete(result: Any = None)` / `RunLog.fail(code: str)`: Marks the run as terminated.
- `CheckpointError(code, message, step_index)`: Raised for `divergence`, `not_serializable`, `run_completed`, `locked`, `entry_too_large`, `too_many_steps`, `invalid_run_id`, or `corrupt_log`.
- `canonical_hash(value: Any) -> str`: SHA-256 hex digest of the canonical JSON of the value.

## Why not LangGraph checkpointers?

This library is framework-free, uses plain JSONL which is human-readable, and implements explicit divergence handling rather than relying on framework-specific state management.

## Documentation

See [docs/SECURITY.md](docs/SECURITY.md) for the threat model.