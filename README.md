# Echo

A small local coding agent for Linux. Qwen or Gemma runs on vLLM, with the LiteLLM SDK inside Echo; coding tools edit your checkout directly by default. Use `--sandbox` to work in a disposable Docker copy instead.

![Echo](docs/echo-ai.png)

## Features

- **Interactive Chat**: Streamed terminal chat with terminal control.
- **Coding Tools**: Read, search, edit, write, and execute bash commands.
- **Session Management**: Persistent SQLite-backed sessions with the ability to resume.
- **Non-interactive Execution**: Run tasks and generate patches automatically.
- **Subagent Delegation**: Delegate bounded read, search, or review tasks.

## Quick start

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, Bash, and ripgrep.
Run from a checkout of this repository:

```bash
uv sync --locked
cp .env.example .env  # First setup only; keep an existing .env
uv run echo-ai config
```

Configure and start an inference backend using the [model deployment instructions](models/README.md), then start a chat:

```bash
uv run echo-ai
```

See [Getting started](docs/guides/getting-started.md) for sandbox setup, configuration, sessions, and installation outside the checkout.

## Documentation

- [User guides](docs/guides/README.md): setup and available workflows.
- [Google tools setup](docs/guides/google-tools.md): run the standalone OAuth/API smoke test. Agent tools are still planned.
- [Development documentation](docs/development/README.md): current architecture, implementation plans, and experiments.
