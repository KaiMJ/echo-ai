# Echo

A small local coding agent for Linux. Qwen or Gemma runs on vLLM, with the LiteLLM SDK inside Echo; coding tools edit your checkout directly by default. Use `--sandbox` to work in a disposable Docker copy instead.

## Features

- **Interactive Chat**: Streamed terminal chat with terminal control.
- **Coding Tools**: Read, search, edit, write, and execute bash commands.
- **Session Management**: Persistent SQLite-backed sessions with the ability to resume.
- **Non-interactive Execution**: Run tasks and generate patches automatically.
- **Subagent Delegation**: Delegate bounded read, search, or review tasks.

## Quick Start

### 1. Setup
Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, Bash, and ripgrep. Docker with NVIDIA GPU support is needed for local inference; Docker also runs `--sandbox`.

```bash
# Sync dependencies
uv sync --locked

# Optional: build the image for --sandbox
docker build -t echo-ai-sandbox:local .

# Configure environment (copy .env.example to .env first)
cp .env.example .env
uv run echo-ai config
```

See [deployment and model profiles](models/README.md) to start or switch the GPU backend.

### 2. Usage

**Interactive Mode**
Start a chat session in your current repository:
```bash
uv run echo-ai
```


**Session Management**
Use `/new` inside chat for a fresh session in the same repository and execution
mode. The previous session remains available through `/sessions`.

Manage previous sessions and apply changes:
```bash
uv run echo-ai sessions             # List this repository
uv run echo-ai sessions --all       # Include other repositories and review sessions
uv run echo-ai chat --resume <ID>   # Resume latest session by default
uv run echo-ai resume <ID>          # Resume latest session by default
uv run echo-ai diff <SESSION_ID> --output change.patch # Export a patch
uv run echo-ai run                  # non-interactive
uv run echo-ai chat --sandbox       # run tools / edits in sandbox
```

## Security & Limits

**shell commands** Currenlty does not use docker.

With `--sandbox`:

- **Isolation**: Tools run in a Docker container with no network access.
- **Workspace Copy**: The agent works on a copy of your repository (up to 512 MiB). Symlinks and sensitive credential directories are excluded.
- **Filesystem**: The supplied image contains Python, `pytest`, Bash, Git, and `ripgrep`.

## Configuration

Choose `model-profile: models/qwen.yaml` or `models/gemma.yaml` in `echo.yaml`.
Model request and deployment settings live in that profile; agent, tool and UI settings stay in
`echo.yaml`. Environment variables override YAML. Resumed sessions keep their saved settings.

```bash
uv run echo-ai config
uv run python models/manage.py qwen up
uv run echo-ai doctor
```

See [deployment instructions](models/README.md) for cache paths, model switching,
reasoning settings, live smoke tests, and adding external providers.
