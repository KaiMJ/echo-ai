# Configuration

## Fresh setup

1. Run `echo-ai setup`. It creates `~/.config/echo-ai/echo.yaml` with the default
   sandbox image and resource limits. Existing files are preserved; omitted
   settings use built-in defaults.
2. If using a cloud model, add its API key to your project's `.env`, your shell,
   or `~/.config/echo-ai/.env`. For xAI:
   ```dotenv
   XAI_API_KEY=your-key
   ```
3. Launch `echo-ai` (or `uv run echo-ai` from the checkout). Enter **`/model`** or
   press **F4** to choose xAI, Qwen, or Gemma. Fresh startup defaults to Gemma;
   local models need a running server. See [Local models](local-models.md).
4. Save your selection. **This session + future sessions** saves model preferences
   to `model.yaml`. **This session only** leaves future defaults unchanged.

The model picker lets you edit the model ID, reasoning, token limits, sampling,
timeout, and endpoint. An empty local endpoint uses `ECHO_INFERENCE_PORT` (default
8001). Changes apply to the next turn; other existing sessions keep their settings.

## Where settings live

| Default path | Contents |
| --- | --- |
| `~/.config/echo-ai/echo.yaml` | Sandbox, agent, tool, and appearance settings |
| `~/.config/echo-ai/.env` | Optional global credentials and environment overrides |
| `~/.local/share/echo-ai/model.yaml` | Model preferences saved through `/model` |
| `~/.local/share/echo-ai/sessions.sqlite3` | Session settings, messages, traces, and costs |

`XDG_CONFIG_HOME` relocates the global config directory. `ECHO_STATE_DIR` relocates
model preferences and session state together. Bundled defaults live in
`src/echo_ai/config/presets/`: `echo.yaml` supplies the setup configuration, and
`gemma.yaml`, `qwen.yaml`, and `xai.yaml` supply model presets. You do not need to
copy or edit these files.

The checkout's `.env` is optional and ignored by Git. Echo reads it when launched
from this directory; the local deployment helper also uses it for model-cache paths
and the inference port. Use `.env.example` as a starting point. Put shared credentials
in the global `.env` if you want them available from other projects.

## Which settings win?

- **YAML:** `ECHO_CONFIG_FILE` → current directory's `echo.yaml` → global `echo.yaml`.
  Echo selects one file without merging; omitted values use built-in defaults.
- **New-session model settings:** `ECHO_*` environment overrides → saved
  `model.yaml` → selected YAML → packaged defaults.
- **Credentials:** shell → project `.env` → global `.env`. Set `ECHO_ENV_FILE`
  to select a specific file instead of the project/global files.

Edits to `.env` take effect on the next request. Resumed sessions keep their saved
runtime settings; appearance comes from the current YAML.

Run **`echo-ai config`** to see effective settings, their sources, and file locations.

## Edit and reset

```bash
echo-ai setup --edit                   # Edit global YAML; validate and back up changes
echo-ai setup --path ./echo.yaml --edit # Edit project YAML
echo-ai setup --reset                  # Restore starter YAML; keep model preferences
echo-ai status                         # Check the model connection and advertised limits
```

To reset model preferences, delete `model.yaml` from your state directory. Existing
sessions retain their settings. Deleting the entire state directory also removes
sessions, traces, and recovery data; stop Echo first, and only do this if you intend
to discard all of that data.

For isolated development, set `ECHO_STATE_DIR` to a scratch directory and
`XDG_CONFIG_HOME` to a separate config directory. `uv run echo-ai` uses the checkout;
an installed `echo-ai` uses its separately installed copy.

See [Sessions](sessions.md) for history and resume commands, and
[Security essentials](security.md) for execution and data privacy details.
