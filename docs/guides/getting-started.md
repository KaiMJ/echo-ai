# Getting started

Run these commands from your Echo checkout.

## Install and run

### 1. Setup
Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, Bash, and ripgrep. Docker with NVIDIA GPU support is needed for local inference; Docker also runs `--sandbox`.

```bash
# Sync dependencies
uv sync --locked

# Build the image for --sandbox (includes Echo's locked test dependencies)
docker build -t echo-ai-sandbox:local .

# Configure environment (copy .env.example to .env first)
cp .env.example .env
uv run echo-ai config
```

See [deployment and model profiles](../../models/README.md) to start or switch the GPU backend.

### 2. Usage

**Interactive Mode**
Start a chat session in your current repository:
```bash
uv run echo-ai
```


**Session Management**
Use `/sessions` to browse sessions, with the latest at the bottom. Click a session
or enter `/sessions ID`, then confirm with Y to resume or N/Esc to cancel.
Use `/new` inside chat for a fresh session in the same repository and execution
mode. The previous session remains available through `/sessions`.
Use `/diff` for agent `edit` and `write` changes on the active conversation
branch. Bash file changes in either mode are outside `/diff`, `/undo`, and
`/apply` tracking.
`/undo` and `/redo` move
the active conversation branch and restore the latest completed turn's files;
if edits overlap, use the reported conflict paths to review them before choosing
`/undo force` or `/redo force`. In a sandbox session, `/apply` merges recorded
agent edits into the source checkout and `/apply force` replaces conflicting files.

Manage previous sessions and apply changes:
```bash
uv run echo-ai sessions             # List this repository
uv run echo-ai sessions --all       # Include other repositories and review sessions
uv run echo-ai chat --resume        # Resume latest non-empty chat in this repository
uv run echo-ai resume               # Same as chat --resume; optionally pass an ID
uv run echo-ai diff <SESSION_ID>                # Recorded agent tool changes
uv run echo-ai diff <SESSION_ID> --output changes.txt # Export change history
uv run echo-ai run                  # non-interactive
uv run echo-ai chat --sandbox       # run tools / edits in sandbox
uv run echo-ai chat --sandbox --sandbox-image my-project-sandbox:local
```

## Security & Limits

In local mode, shell commands run in your checkout without Docker.

With `--sandbox`:

- **Isolation**: Tools run in a Docker container with no network access.
- **Workspace Copy**: The agent works on a copy of your repository (up to 512 MiB). Symlinks and sensitive credential directories are excluded.
- **Filesystem**: The supplied image contains Python, Bash, Git, `ripgrep`, and
  Echo's locked runtime and test dependencies. `/workspace/src` is on Python's
  import path, so tests use the sandbox's current source files.
- **Other project dependencies**: Build an image from `echo-ai-sandbox:local`
  and add that project's packages. Set `sandbox.sandbox_image` in `echo.yaml`,
  `ECHO_SANDBOX_IMAGE`, or `--sandbox-image` when starting a new sandbox session.
  Source edits use the mounted workspace immediately; rebuild only when the
  image's dependencies or tools change. The image must retain `/opt/echo_sandbox.py`.

For example, create `Dockerfile.echo` containing:

```dockerfile
FROM echo-ai-sandbox:local
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
```

Build it with `docker build -f Dockerfile.echo -t my-project-sandbox:local .`.

## Configuration

Choose `model-profile: models/qwen.yaml` or `models/gemma.yaml` in `echo.yaml`.
Model request and deployment settings live in that profile; agent, tool and UI settings stay in
`echo.yaml`. Environment variables override YAML. Resumed sessions keep their saved settings.

```bash
uv run echo-ai config
uv run python models/manage.py qwen up
uv run echo-ai doctor
```

See [deployment instructions](../../models/README.md) for cache paths, model switching,
reasoning settings, live smoke tests, and adding external providers.

### Install a standalone command

From the checkout, install Echo as a uv tool:

```bash
uv tool install --force --from . echo-ai
```

When running outside the checkout, set `ECHO_CONFIG_FILE` and `ECHO_ENV_FILE`
to the absolute paths of your configuration and `.env` files, then run `echo-ai`.

```bash
ECHO_CONFIG_FILE=/absolute/path/to/echo-ai/echo.yaml \
ECHO_ENV_FILE=/absolute/path/to/echo-ai/.env \
echo-ai
```

## Reset local state

To remove the default local state, stop all Echo processes first. The following
deletes the entire state directory, including saved sessions and their recovery
data; it cannot be undone. If you configured `ECHO_STATE_DIR`, use that location
instead.

```bash
rm -rf ~/.local/share/echo-ai/
```
