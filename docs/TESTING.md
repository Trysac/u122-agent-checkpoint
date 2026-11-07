# Testing

Tests are located in `tests/test_agent_checkpoint.py`.

## Coverage

- **First run**: Verifies `log.step` calls `fn` and persists records.
- **Replay**: Verifies `step` returns stored results without calling `fn`.
- **Divergence**: Verifies `on_divergence='raise'` detects mismatches and `on_divergence='truncate'` recovers correctly.
- **Torn Tail**: Simulates partial JSON lines and verifies truncation on load.
- **Terminal states**: Verifies `complete()` and `fail()` prevent further steps.
- **Edge cases**: Handles floats/ints, `None` outputs, and Windows-safe file replacement.