# Echo

A small local coding agent for Linux. Gemma runs on vLLM; coding tools run in disposable Docker workspaces. Your original checkout is never mounted into a tool container.

## Features

- **Interactive Chat**: Streamed terminal chat with terminal control.
- **Coding Tools**: Read, search, edit, write, and execute bash commands.
- **Session Management**: Persistent SQLite-backed sessions with the ability to resume.
- **Non-interactive Execution**: Run tasks and generate patches automatically.
- **Subagent Delegation**: Delegate bounded read, search, or review tasks.

## Quick Start

### 1. Setup
Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, and Docker.

```bash
# Sync dependencies
uv sync --locked

# Build the sandbox image
docker build -t echo-ai-sandbox:local .

# Configure environment (copy .env.example to .env first)
cp .env.example .env
uv run echo-ai config
```

### 2. Usage

**Interactive Mode**
Start a chat session in your current repository:
```bash
uv run echo-ai chat --repo .
```
*   `Enter`: Send message.
*   `Alt+Enter`: Newline.
*   `Ctrl-C`: Cancel current turn.
*   `Ctrl-D`: Exit.
*   Commands: `/help`, `/status`, `/diff`, `/details`, `/copy`, `/exit`.

Tool arguments stream as the model generates them. Shell output streams as the
process flushes it; structured file-tool results appear at completion. Trace popups
retain this chat's reasoning in memory. Completed reasoning traces, tool results,
and conversation messages are saved in SQLite; trace popups are not restored
after restarting.

Input and generated counts use `~` for character-based estimates until server
usage arrives. They are per-request, not cumulative usage or live tokenizer
measurements. `/status` explains the counts and shows the generation limit.
Thinking consumes the output budget. By default, its trace is not sent back to
the model and does not count against the client prompt context guard. With
`local-model.return_reasoning: true`, saved traces are sent in request history
and included in the input estimate and context guard. The call budget
is shared with review subagents.

Use `uv run echo-ai chat --repo . --plain` (also available for `run` and `resume`)
to disable live redraws. Redirected output is automatically append-only. Color
follows the terminal and respects `NO_COLOR`. Slash commands support Tab completion.

**Automated Mode**
Run a task without an interactive terminal:
```bash
uv run echo-ai run --repo . "Find and fix a small bug, then run relevant tests."
```

**Session Management**
Manage previous sessions and apply changes:
```bash
uv run echo-ai sessions             # List sessions
uv run echo-ai resume <SESSION_ID>   # Resume a session
uv run echo-ai diff <SESSION_ID> --output change.patch # Export a patch
```

## Security & Limits

- **Isolation**: Tools run in a Docker container with no network access.
- **Workspace Copy**: The agent works on a copy of your repository (up to 512 MiB). Symlinks and sensitive credential directories are excluded.
- **Filesystem**: The supplied image contains Python, `pytest`, Bash, Git, and `ripgrep`.

## Documentation

- [Architecture](docs/architecture.md): Code map and session behavior.
- [Inference](docs/inference.md): GPU deployment and resizing.
- [Sandbox limits](docs/security.md): Isolation details and risks.

## Configuration

Edit `echo.yaml` in the current directory. Settings are grouped under
`local-model`, `agent`, `sandbox`, and `tools`. The `local-model` section controls reasoning,
context and output limits, sampling, and model timeout; `agent` controls the call budget. The same file
also controls workspace size, tool read/write/output limits, tool timeouts,
subagent steps, and Docker CPU, memory, process, file, and temporary-disk limits.
`tools` has `defaults`, `read`, `search`, `write`, `edit`, and `bash` sections.
Defaults apply to all sandbox tools, including `list`. The edit size limit applies
to the resulting file. Sizes use bytes and timeouts use seconds. Rebuild the sandbox image after this
update so file tools receive the configured limits:
`docker build -t echo-ai-sandbox:local .`. Set
`ECHO_CONFIG_FILE=/path/to/config.yaml` to select another file. Unknown keys and
invalid values are rejected. Precedence is exported environment variables,
`.env`, YAML, then built-in defaults. Existing `ECHO_*` overrides still work;
remove them from `.env` when moving those settings to YAML.

`reasoning_enabled: false` disables thinking through the server's chat template.
`return_reasoning: false` (the default) excludes saved reasoning from requests;
set it to `true` to send traces from previous calls and user turns back to the
model. This is independent of `reasoning_enabled`, which controls generation.
Completed reasoning traces are saved in SQLite in either mode.
`ECHO_RETURN_REASONING=true` provides an environment override.
API credentials remain in `ECHO_API_KEY`, outside the YAML file.
`uv run echo-ai config` shows effective settings for new sessions. Resumed
sessions retain their saved configuration.

Docker Compose still reads server deployment settings from `.env`, including
`ECHO_CONTEXT_TOKENS` and `ECHO_MODEL`. The YAML context limit controls the client;
it does not resize the inference server. Keep it within the server's limit and
use `uv run echo-ai doctor` to check.
