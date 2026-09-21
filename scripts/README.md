# Shared scripts

Run these from the Echo checkout after `uv sync --locked`:

```bash
uv run python scripts/deploy_local_model.py models
uv run python scripts/deploy_local_model.py qwen check
uv run python scripts/deploy_local_model.py qwen up
uv run python scripts/deploy_local_model.py status
uv run python scripts/deploy_local_model.py stop
```

Use `gemma` instead of `qwen` to select Gemma. See the
[local model guide](../docs/guides/local-models.md) for prerequisites and custom profiles.

Personal host utilities, experiments, notes, and credentials live in the ignored
`local-dev/` directory. They are not required to install or run Echo.
