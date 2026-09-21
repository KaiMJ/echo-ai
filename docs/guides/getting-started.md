# Getting started

Install once, configure once, and run Echo from any project.

Requires Linux, Python 3.12+, [uv](https://docs.astral.sh/uv/), Git, Bash, and ripgrep.

## 1. Install

```bash
git clone https://github.com/KaiMJ/echo-ai.git
cd echo-ai
uv tool install --from . echo-ai
```

## 2. Configure

```bash
echo-ai setup --edit
```

This creates settings in `~/.config/echo-ai/` (or `$XDG_CONFIG_HOME/echo-ai/`)
and opens your editor. Set your model and server URL. Existing settings are preserved
until you save an edit.

Echo needs a running model server. If you need to host one locally, follow the
[local model guide](local-models.md). Otherwise, skip that step.

## 3. Run

```bash
cd /path/to/your-project
echo-ai status
echo-ai
```

Describe what you want to change. Echo asks before running commands or editing
files in its default approval mode. Use `/help` for commands, `/sessions` for
previous conversations, and `/diff` to inspect recorded edits.

To change settings later, run `echo-ai setup --edit`. A project's `echo.yaml`
overrides your global configuration; `echo-ai config` shows which file is active.

## More

- [Configuration](configuration.md): credentials, repairs, and separate development settings.
- [Sessions](sessions.md): resume conversations and inspect changes.
- [Sandbox mode](workspaces-and-changes.md): work in a disposable Docker copy.
- [Security](security.md): approvals, execution risks, and data privacy.
