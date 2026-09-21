# Configuration

Choose your provider, model, endpoint, and token limits with **F4** or **`/model`**
in chat. Changes take effect next turn. **This session + future sessions** saves
preferences to `model.yaml`; **This session only** leaves future defaults unchanged.
For first-time setup, see [Getting started](getting-started.md).

## Settings and credentials

| Default path | Contents |
| --- | --- |
| `~/.config/echo-ai/echo.yaml` | Sandbox, agent, tool, and appearance settings |
| `~/.config/echo-ai/.env` | Shared API keys and environment overrides |
| `~/.local/share/echo-ai/model.yaml` | Model preferences saved through `/model` |
| `~/.local/share/echo-ai/sessions.sqlite3` | Sessions, messages, traces, and costs |

Use the global `.env` for credentials shared across projects. A project's `.env`
is optional; keep it out of version control. Shell variables take precedence.

```bash
echo-ai setup --edit                   # Edit global YAML; validate and back up changes
echo-ai setup --path ./echo.yaml --edit # Edit project YAML
echo-ai config                         # Show effective settings, sources, and paths
echo-ai status                         # Check model connection and advertised limits
```

## Which settings win?

- **YAML:** `ECHO_CONFIG_FILE` → current directory's `echo.yaml` → global `echo.yaml`.
  Echo selects one file without merging; omitted values use built-in defaults.
- **New-session model settings:** `ECHO_*` environment overrides → saved
  `model.yaml` → selected YAML → packaged defaults.
- **Credentials:** shell → project `.env` → global `.env`. Set `ECHO_ENV_FILE`
  to select a specific file instead of the project/global files.

Resumed sessions keep saved runtime settings; appearance comes from the current YAML.
`XDG_CONFIG_HOME` relocates the global config directory. `ECHO_STATE_DIR` relocates
model preferences and session state together.

## Reset settings

Run `echo-ai setup --reset` to restore starter YAML while keeping model preferences.
To reset model preferences too, delete `model.yaml` from your state directory.
Existing sessions retain their settings.

Deleting the entire state directory also removes sessions, traces, and recovery
data. Stop Echo first and only do this if you intend to discard that data.

For separate development settings, see [Development setup](../development/README.md#development-setup).
