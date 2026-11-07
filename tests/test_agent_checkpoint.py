"""Comprehensive tests for agent_checkpoint."""

import json
import math
from pathlib import Path
from typing import Any

import pytest

from agent_checkpoint import CheckpointError, CheckpointStore, canonical_hash


def test_acceptance_1_first_run_and_replay(tmp_path: Path) -> None:
    store1 = CheckpointStore(tmp_path)
    calls_fn = 0

    def fn() -> str:
        nonlocal calls_fn
        calls_fn += 1
        return "x"

    with store1.open("r1") as log1:
        res = log1.step("fetch", {"url": "a"}, fn)
        assert res == "x"
        assert calls_fn == 1

    store2 = CheckpointStore(tmp_path)
    calls_fn2 = 0
    calls_fn3 = 0

    def fn2() -> str:
        nonlocal calls_fn2
        calls_fn2 += 1
        return "x2"

    def fn3() -> str:
        nonlocal calls_fn3
        calls_fn3 += 1
        return "y"

    with store2.open("r1") as log2:
        res1 = log2.step("fetch", {"url": "a"}, fn2)
        assert res1 == "x"
        assert calls_fn2 == 0
        res2 = log2.step("process", {"val": 1}, fn3)
        assert res2 == "y"
        assert calls_fn3 == 1


def test_acceptance_2_divergence_raise_and_truncate(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)

    with store.open("r1") as log:
        log.step("fetch", {"url": "a"}, lambda: "step0")
        log.step("next", {"url": "x"}, lambda: "step1")

    with store.open("r1", on_divergence="raise") as log_div:
        with pytest.raises(CheckpointError) as exc_info:
            log_div.step("fetch", {"url": "b"}, lambda: "step0_div")
        assert exc_info.value.code == "divergence"
        assert exc_info.value.step_index == 0

    calls_fn = 0

    def fn_new() -> str:
        nonlocal calls_fn
        calls_fn += 1
        return "new_step0"

    with store.open("r1", on_divergence="truncate") as log_trunc:
        out = log_trunc.step("fetch", {"url": "b"}, fn_new)
        assert out == "new_step0"
        assert calls_fn == 1

    with open(tmp_path / "r1.jsonl", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 1
    assert lines[0]["output"] == "new_step0"
    assert lines[0]["i"] == 0


def test_acceptance_3_canonical_hash_and_floats() -> None:
    h1 = canonical_hash(["step", {"b": 1, "a": 2}])
    h2 = canonical_hash(["step", {"a": 2, "b": 1}])
    assert h1 == h2

    h_int = canonical_hash(["step", 1])
    h_float = canonical_hash(["step", 1.0])
    assert h_int != h_float

    with pytest.raises(CheckpointError) as exc_info:
        canonical_hash(float("nan"))
    assert exc_info.value.code == "not_serializable"


def test_acceptance_4_torn_tail_recovery(tmp_path: Path) -> None:
    run_file = tmp_path / "r_torn.jsonl"
    run_hash = canonical_hash(["step0", None])
    valid_record = json.dumps({"v": 1, "i": 0, "name": "step0", "hash": run_hash, "output": 42})
    torn_tail = '{"v":1,"i":1,'
    run_file.write_bytes(f"{valid_record}\n{torn_tail}".encode())

    store = CheckpointStore(tmp_path)
    with store.open("r_torn") as log:
        assert log._current_index == 0
        assert len(log._records) == 1
        out = log.step("step0", None, lambda: 99)
        assert out == 42
        out1 = log.step("step1", None, lambda: 100)
        assert out1 == 100

    with open(run_file, encoding="utf-8") as f:
        for line in f:
            line_str = line.strip()
            if line_str:
                parsed = json.loads(line_str)
                assert isinstance(parsed, dict)


def test_acceptance_5_terminal_states_and_refusal(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)

    with store.open("r_term") as log:
        log.step("start", None, lambda: 1)
        log.complete("done")
        assert log.status == "completed"

        with pytest.raises(CheckpointError) as exc1:
            log.step("after_done", None, lambda: 2)
        assert exc1.value.code == "run_completed"

        with pytest.raises(CheckpointError) as exc2:
            log.complete("again")
        assert exc2.value.code == "run_completed"

        with pytest.raises(CheckpointError) as exc3:
            log.fail("some_error")
        assert exc3.value.code == "run_completed"

    with store.open("r_term") as log_reopened:
        assert log_reopened.status == "completed"
        with pytest.raises(CheckpointError) as exc_reopened:
            log_reopened.step("any", None, lambda: 3)
        assert exc_reopened.value.code == "run_completed"

    with store.open("r_fail") as log_fail:
        log_fail.fail("tool_error")
        assert log_fail.status == "failed"
        with pytest.raises(CheckpointError) as exc_fail:
            log_fail.step("any", None, lambda: 4)
        assert exc_fail.value.code == "run_completed"

    with store.open("r_fail") as log_fail_reopened:
        assert log_fail_reopened.status == "failed"
        with pytest.raises(CheckpointError) as exc_fail_reopened:
            log_fail_reopened.fail("other_error")
        assert exc_fail_reopened.value.code == "run_completed"


def test_acceptance_6_locking_and_break_lock(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)
    log1 = store.open("r1")
    try:
        with pytest.raises(CheckpointError) as exc:
            store.open("r1")
        assert exc.value.code == "locked"

        log_break = store.open("r1", break_lock=True)
        log_break.close()
    finally:
        log1.close()

    log2 = store.open("r1")
    log2.close()


def test_acceptance_7_limits_and_validation(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, max_entry_bytes=100, max_steps=2)

    with pytest.raises(CheckpointError) as exc_inv1:
        store.open("../x")
    assert exc_inv1.value.code == "invalid_run_id"

    with pytest.raises(CheckpointError) as exc_inv2:
        store.open("")
    assert exc_inv2.value.code == "invalid_run_id"

    with store.open("r_lim") as log:
        big_data = "x" * 200
        with pytest.raises(CheckpointError) as exc_large:
            log.step("too_big", big_data, lambda: big_data)
        assert exc_large.value.code == "entry_too_large"

        log.step("step0", None, lambda: 1)
        log.step("step1", None, lambda: 2)
        with pytest.raises(CheckpointError) as exc_steps:
            log.step("step2", None, lambda: 3)
        assert exc_steps.value.code == "too_many_steps"
        assert exc_steps.value.step_index == 2


def test_acceptance_8_list_runs_and_events(tmp_path: Path) -> None:
    events: list[dict[str, Any]] = []

    def record_event(e: dict[str, Any]) -> None:
        events.append(e)

    store = CheckpointStore(tmp_path, on_event=record_event)
    assert store.list_runs() == []

    sentinel = "SENTINEL-cp2"
    with store.open("r2") as log2:
        log2.step("s1", {"key": sentinel}, lambda: {"out": sentinel})

    with store.open("r1") as log1:
        log1.step("s0", None, lambda: 10)
        log1.complete("done")

    runs = store.list_runs()
    assert runs == [("r1", "completed"), ("r2", "running")]

    for evt in events:
        evt_str = json.dumps(evt)
        assert sentinel not in evt_str
        if "step" in evt:
            assert "step" in evt
            assert "name" in evt
            assert "replayed" in evt
        if "status" in evt:
            assert evt["status"] in ("completed", "failed")


def test_adversarial_and_edge_cases(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path)

    # Unicode step names and None output
    with store.open("r_unicode") as log:
        out = log.step("🚀-step-üñîçødé", None, lambda: None)
        assert out is None
        log.complete()

    with store.open("r_unicode") as log_reopened:
        assert log_reopened.status == "completed"
        out_replayed = log_reopened._records[0]["output"]
        assert out_replayed is None

    # Zero steps then complete
    with store.open("r_zero") as log:
        log.complete(42)
    with store.open("r_zero") as log_reopened:
        assert log_reopened.status == "completed"

    # Re-closing is safe
    log.close()
    log.close()

    # Middle corruption raises corrupt_log
    corrupt_file = tmp_path / "r_corrupt.jsonl"
    corrupt_file.write_bytes(b'not_valid_json\n{"v":1}')
    with pytest.raises(CheckpointError) as exc_corrupt:
        store.open("r_corrupt")
    assert exc_corrupt.value.code == "corrupt_log"

    # Not v1 record raises corrupt_log
    v2_file = tmp_path / "r_v2.jsonl"
    v2_file.write_bytes(b'{"v":2}')
    with pytest.raises(CheckpointError) as exc_v2:
        store.open("r_v2")
    assert exc_v2.value.code == "corrupt_log"

    # Non-serializable inputs or outputs in step
    with store.open("r_nonserial") as log:
        with pytest.raises(CheckpointError) as exc_ns:
            log.step("s", math.nan, lambda: 1)
        assert exc_ns.value.code == "not_serializable"

        with pytest.raises(CheckpointError) as exc_ns2:
            log.step("s", 1, lambda: math.nan)
        assert exc_ns2.value.code == "not_serializable"

        with pytest.raises(CheckpointError) as exc_term_ns:
            log.complete(math.nan)
        assert exc_term_ns.value.code == "not_serializable"

    # Step function exception propagates and is not recorded
    with store.open("r_ex") as log:

        def fail_fn() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            log.step("step_fail", None, fail_fn)

        assert len(log._records) == 0
        out = log.step("step_fail", None, lambda: "success")
        assert out == "success"

    # Step on closed log
    with pytest.raises(CheckpointError) as exc_closed:
        log.step("next", None, lambda: 1)
    assert exc_closed.value.code == "locked"

    # Invalid on_divergence argument
    with pytest.raises(ValueError, match="Invalid on_divergence"):
        store.open("r_inv_div", on_divergence="invalid")  # type: ignore[arg-type]
