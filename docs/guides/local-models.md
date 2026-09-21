# Local models

Host Qwen or Gemma locally with vLLM using Echo’s packaged templates.
**Skip this guide if you already have a model server.**

## Start a server

Requires Docker with NVIDIA GPU support and downloaded model weights. The helper
validates existing weights; it does not download them. Review the selected profile's
GPU and context settings for your hardware before starting.

From the Echo checkout:

```bash
uv sync --locked
test -e .env || cp .env.example .env
```

Edit `.env` and set `ECHO_HF_HUB_CACHE` to your Hugging Face hub cache directory.
The cache must contain the model revision specified in the packaged `qwen.yaml` or `gemma.yaml` template.
Then start a model:

```bash
uv run python scripts/deploy_local_model.py models
uv run python scripts/deploy_local_model.py qwen check
uv run python scripts/deploy_local_model.py qwen up
```

Use `gemma` instead of `qwen` for Gemma. Both use the same inference service;
starting one replaces the other. `models` lists the model IDs, pinned revisions,
GPU counts, and cache variables without requiring Docker or a configured cache.

## Connect Echo

Run `echo-ai setup --edit` to select the matching profile in your user configuration
(`model-profile: builtin:qwen` or `model-profile: builtin:gemma`). Set `local-model.base_url`
to your server URL; the default is `http://127.0.0.1:8001/v1`.

From your target project:

```bash
echo-ai status
echo-ai
```

The checkout's `echo.yaml` is separate from installed user settings.
See [configuration](configuration.md) for local development.

## Manage the server

```bash
uv run python scripts/deploy_local_model.py status
uv run python scripts/deploy_local_model.py logs
uv run python scripts/deploy_local_model.py stop
```

These controls act on the shared server and do not require a model name or model
cache configuration. Existing commands such as `qwen status` still work.
`status` also shows stopped containers. Logs follow the server by default; use
`logs --no-follow --tail 200` to print recent output and exit. Ctrl-C exits the
log viewer without stopping the server.

Startup waits up to 1,200 seconds for readiness; change this with
`qwen up --wait-timeout 1800`. If startup fails or times out, inspect `status` and
`logs --no-follow`; the container may still be running. Use `stop` to stop it.

Use `--env-file /path/to/.env` to select an environment file explicitly (otherwise
`ECHO_ENV_FILE`, then the checkout's `.env`, is used). Shell environment variables
take precedence. The default `.env` is optional if the required variables are
already exported; an explicitly selected file must exist.

Run without arguments or with `--help` for usage examples.

Use `check` to validate weights and Compose configuration without starting the
server, or `config` to inspect the generated Compose configuration.

## Custom settings

Templates live in `src/echo_ai/config/templates/models/`; both Echo and the
launcher read them directly. There is no separate repository or user `models/`
folder to maintain. Built-in defaults follow the installed package version;
resumed sessions retain their saved runtime settings.

Put request overrides under `local-model` in your `echo.yaml`. For custom GPU or
server settings, copy a template to a file you own and pass it explicitly:

```bash
cp src/echo_ai/config/templates/models/qwen.yaml ./my-model.yaml
# Edit my-model.yaml for your hardware, then:
uv run python scripts/deploy_local_model.py qwen up --profile ./my-model.yaml
```

Set Echo's `model-profile` to that same file (absolute, or relative to your
`echo.yaml`) so client and server limits agree. Server changes require restarting
inference. Model weights stay in your external cache.

See [model verification](../development/model-verification.md) for integration checks.
