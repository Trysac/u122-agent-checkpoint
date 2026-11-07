# agent-checkpoint

[![PyPI version](https://img.shields.io/pypi/v/trysac-agent-checkpoint)](https://pypi.org/project/trysac-agent-checkpoint/)
[![License: MIT](https://img.shields.io/pypi/l/trysac-agent-checkpoint)](LICENSE)
[![CI](https://github.com/Trysac/u122-agent-checkpoint/actions/workflows/ci.yml/badge.svg)](https://github.com/Trysac/u122-agent-checkpoint/actions/workflows/ci.yml)

Checkpoint and resume agent runs from an append-only JSONL log: recorded steps replay without re-execution, divergence detection, torn-tail recovery and terminal states

## Problem

Describe in two or three sentences the concrete problem this utility solves, who hits it, and what
they do today without it. Replace this paragraph when the first real feature lands.

## Install

```sh
pip install trysac-agent-checkpoint
# or
uv add trysac-agent-checkpoint
```

Requires Python 3.10 or newer. No runtime dependencies.

## Usage

```python
import agent_checkpoint

# normalize() trims surrounding whitespace and lower-cases the text.
print(agent_checkpoint.normalize("  Hello World "))  # -> "hello world"

# Blank input is rejected explicitly instead of returning an empty string.
try:
    agent_checkpoint.normalize("   ")
except ValueError as exc:
    print(f"rejected: {exc}")
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) and [decisions](docs/decisions/)
- [Testing](docs/TESTING.md) and [security](docs/SECURITY.md)
- [Project record](docs/PROJECT.md) and [stack](docs/STACK.md)
- [Changelog](CHANGELOG.md) and [contributing guide](CONTRIBUTING.md)

## License

[MIT](LICENSE) (c) 2026 Miguel Gomez
