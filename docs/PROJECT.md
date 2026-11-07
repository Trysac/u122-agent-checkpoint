# Project record

## Objective

Checkpoint and resume agent runs from an append-only JSONL log: recorded steps replay without re-execution, divergence detection, torn-tail recovery and terminal states.

## Scope

- Persistence of deterministic agent steps.
- Handling of divergence via raising errors or log truncation.
- Recovery from interrupted writes (torn tails).
- Managing terminal run states (completed, failed).
- Standard library only; no runtime dependencies.

## Out of Scope

- Concurrent writers.
- Remote storage.
- Encryption.
- Automatic retries.
- Checkpointing of arbitrary Python objects (pickle is never used).

## Factory run u122 (measured from API usage)

| Phase | Model | Batch | Input | Output | Cache write | Cache read | Cost (USD) |
|---|---|---|---|---|---|---|---|
| generation | gemini-3.8-flash | yes | 4305 | 10277 | 0 | 0 | 0.0209 |
| fix-1 | gemini-3.8-flash | no | 55015 | 1729 | 0 | 233352 | 0.0652 |
| fix-2 | gemini-3.8-flash | no | 24632 | 1316 | 0 | 55221 | 0.0276 |
| fix-3 | gemini-3.8-flash | no | 101003 | 1424 | 0 | 663251 | 0.1308 |
| fix-4 | gemini-3.8-flash | no | 61969 | 1273 | 0 | 259745 | 0.0707 |
| audit | gemini-3.1-flash-lite | no | 48139 | 369 | 0 | 111906 | 0.0154 |
| docs | gemini-3.1-flash-lite | no | 179648 | 1383 | 0 | 0 | 0.0470 |

Total: $0.3776. Prices: Anthropic list prices.
