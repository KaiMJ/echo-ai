# Getting started

Requires Linux, Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, Bash, and ripgrep.

## 1. Install

```bash
git clone https://github.com/KaiMJ/echo-ai.git
cd echo-ai
uv tool install --from . echo-ai
echo-ai setup
```

Setup creates `~/.config/echo-ai/echo.yaml` and preserves an existing file.

## 2. Connect a model

Choose one:

- **Cloud:** add your provider's API key to `~/.config/echo-ai/.env`. For xAI, use `XAI_API_KEY=your-key`.
- **Local:** start an existing model server, or follow [Local models](local-models.md) to host Qwen or Gemma.

Open Echo from the project you want to work on:

```bash
cd /path/to/your-project
echo-ai
```

Press **F4** or enter **`/model`** to select your provider and model. For a local
server, set its endpoint; the default is `http://127.0.0.1:8001/v1`. Save with
**This session + future sessions** to reuse the selection. Fresh installs default
to Gemma, which needs a running local server.

## 3. Send a prompt

Try: `Explain how this project is organized.` Then describe a change you want.
Echo asks before running commands or editing files in its default approval mode.
Local mode edits your project directly.

Use `/help` for commands and `/diff` to review recorded edits. If the model does
not connect, run `echo-ai status` from another terminal in the same project.

Continue with [Everyday use](everyday-use.md) for sessions, undo, and sandbox mode.
See [Configuration](configuration.md) to change settings or diagnose which ones are active.
