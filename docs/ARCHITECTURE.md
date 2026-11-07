# Architecture

`agent_checkpoint` is designed as a filesystem-backed, deterministic execution logger and replay engine for agentic workflows.

## Data Layout

Runs reside inside a caller-specified directory with two files per run:
- `<directory>/<run_id>.jsonl`: Append-only newline-delimited JSON entries.
- `<directory>/<run_id>.lock`: Lock file opened with `os.O_CREAT | os.O_EXCL`.

Run IDs match `^[A-Za-z0-9_-]{1,64}$`, forbidding path traversal (`../`) and illegal filesystem characters.

## Log Format

Entries are written with `v: 1` versioning and serialized canonically using sorted keys, no whitespace, and `allow_nan=False`.

### Step Record
```json
{"hash":"<sha256>","i":0,"name":"fetch","output":"data","v":1}
```

### Terminal Records
```json
{"result":"done","status":"completed","v":1}
{"code":"tool_error","status":"failed","v":1}
```

## Canonical Hash

Step hashing computes the SHA-256 digest of canonical JSON for `[name, inputs]`. Floats and ints preserve their canonical string representations (e.g. `1` vs `1.0`), meaning different numeric representations hash differently.

## Divergence & Truncation

When a run is resumed, step calls indexed at `k` compare `(name, hash)` against recorded history. If they match, the stored output is returned immediately without invoking the step's callback.

If they differ:
- With `on_divergence="raise"` (default), a `CheckpointError(code="divergence", step_index=k)` is raised.
- With `on_divergence="truncate"`, the log is rewritten atomically via a temporary file and `os.replace` up to step `k`, discarding subsequent steps, and the live step executes.

## Torn Tail Recovery

If a process terminates mid-write, the final line may lack a trailing newline and fail JSON parsing. On initial read, `RunLog` detects this partial tail and truncates the file back to the last valid byte offset before appending new entries.
