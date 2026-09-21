# Local models

Host Qwen or Gemma with Echo's vLLM templates. Skip this guide if you use a cloud
provider or already have a model server.

## Start a server

Requires Docker with NVIDIA GPU support and downloaded model weights. The helper
validates weights but does not download them. From the Echo checkout:

```bash
uv sync --locked
test -e .env || cp .env.example .env
uv run python scripts/deploy_local_model.py models
```

`models` lists model IDs, pinned revisions, GPU requirements, and cache variables.
Review these against your hardware. Set `ECHO_HF_HUB_CACHE` in `.env` to the Hugging
Face hub cache containing the selected revision, then run:

```bash
uv run python scripts/deploy_local_model.py qwen check
uv run python scripts/deploy_local_model.py qwen up
```

Use `gemma` instead of `qwen` for Gemma. Both share one inference service;
starting one replaces the other. Startup waits up to 1,200 seconds; use
`qwen up --wait-timeout 1800` to allow longer.

## Connect Echo

Run `echo-ai` from your project and open `/model`. Select Qwen or Gemma, set the
endpoint, and save for this session and future sessions. An empty endpoint uses
`ECHO_INFERENCE_PORT`, defaulting to `http://127.0.0.1:8001/v1`.
Run `echo-ai status` from another terminal to check the saved connection.

## Manage the server

```bash
uv run python scripts/deploy_local_model.py status
uv run python scripts/deploy_local_model.py logs
uv run python scripts/deploy_local_model.py stop
```

These commands act on the shared server without requiring a model name or cache
configuration. Logs follow by default; use `logs --no-follow --tail 200` for recent
output. Ctrl-C exits the log viewer without stopping the server.

If startup fails or times out, check `status` and `logs --no-follow`. The container
may still be running; use `stop` to stop it.

## Custom settings

The launcher reads `--env-file /path/to/.env`, then `ECHO_ENV_FILE`, then the
checkout's optional `.env`. Shell variables take precedence. An explicitly selected
file must exist.

For custom GPU or server settings, copy and edit a packaged template:

```bash
cp src/echo_ai/config/presets/qwen.yaml ./my-model.yaml
uv run python scripts/deploy_local_model.py qwen up --profile ./my-model.yaml
```

Use `/model` to set matching model IDs and token limits in Echo. Request overrides
can also go under `local-model` in `echo.yaml`. Server changes require restarting
inference; weights stay in your external cache.

Use `--help` for command options, `check` to validate without starting, or `config`
to inspect generated Compose configuration. For development checks, see
[Model verification](../development/model-verification.md).
