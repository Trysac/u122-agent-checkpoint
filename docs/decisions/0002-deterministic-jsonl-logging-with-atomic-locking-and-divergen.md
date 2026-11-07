# Deterministic JSONL Logging with Atomic Locking and Divergence Handling

Status: accepted (generated, pending human review)

## Context

Agent workflows frequently need to resume from failure points without repeating costly external API calls. Existing checkpointers often rely on framework coupling, non-deterministic serialization, or unsafe binary formats like pickle. A robust checkpointing utility needs atomic filesystem persistence, deterministic canonical serialization, divergence resolution, and crash resilience.

## Decision

Implement CheckpointStore and RunLog using append-only JSONL files with SHA-256 canonical hashing of [name, inputs]. Implement mutual exclusion via O_CREAT | O_EXCL lockfiles. On replay, detect torn tail lines and truncate them before appending. Support both strict failure and atomic truncation on step divergence.

## Consequences

Runs achieve deterministic replay and crash safety with zero runtime dependencies. Single-process locking ensures file integrity without distributed lock complexity. Arbitrary object persistence is intentionally disallowed in favor of standard JSON serialization.
