# Security and Threat Model

## Threat Model

- **Defended**: Path traversal via `run_id` (enforced by regex). State tampering/corruption via torn writes (enforced by recovery). Resource exhaustion via payload size and step count limits. Secrets leakage in event listeners.
- **Not Defended**: Concurrent access (no thread safety, handled by file locking). Remote state injection.

## Limits

- **Run ID**: Must match `^[A-Za-z0-9_-]{1,64}$`.
- **Entry Size**: Max `1_048_576` bytes by default.
- **Steps**: Max `10_000` steps per run by default.
- **Serialization**: `allow_nan=False` prevents invalid JSON encoding; arbitrary object pickling is strictly forbidden.