# Configuration

## Edit or repair settings

```bash
echo-ai config                 # Selected paths and effective settings; credentials hidden
echo-ai setup --edit           # Edit global settings; validate and back up before saving
echo-ai setup --reset          # Back up current YAML and restore starter settings
echo-ai setup --path ./echo.yaml --edit  # Explicitly edit project settings
echo-ai status                 # Check model availability and context limits
```

Setup works even when active YAML or the credential-file path is broken. Invalid
edits preserve the original and report a saved draft for recovery. Reset selects the packaged starter profile without modifying any custom
profile files, so a broken custom profile cannot prevent recovery. Saving needs no network connection. This is an editor-based
workflow; an in-chat `/setup` menu is not implemented yet.

YAML discovery selects **one file**, without merging:

1. Explicit `ECHO_CONFIG_FILE` (missing files are errors).
2. `echo.yaml` in the current directory.
3. Global `echo.yaml`.
4. Built-in defaults.

`model-profile: builtin:qwen` and `builtin:gemma` use packaged templates directly.
Setup creates no copied profile directory. Existing configurations pointing to
custom files still work; switch to a built-in name explicitly to use the templates.
Relative `model-profile` file paths resolve beside the selected YAML. Project YAML
replaces global YAML entirely, so a theme-only project file uses runtime defaults.
Put model overrides such as `reasoning_effort` under `local-model` in the selected
YAML. Resumed sessions retain saved runtime settings.

Credentials load from global `.env`, or exclusively from `ECHO_ENV_FILE` when set.
Shell variables win; environment settings override YAML. Echo never automatically
loads the current project's `.env`. To create a private credential file:

```bash
# Use your XDG config location instead if customized.
(umask 077; touch ~/.config/echo-ai/.env)
chmod 600 ~/.config/echo-ai/.env
```

Edit that file and add only Echo credentials, using the variable named by
`api_key_env`. Never copy a development `.env` containing unrelated secrets.
New Echo configuration directories use mode 0700 and generated files use 0600.

### Keep local development separate

From the Echo checkout, explicitly select its source environment and files:

```bash
uv sync --locked
ECHO_CONFIG_FILE=./echo.yaml ECHO_ENV_FILE=./.env uv run echo-ai status
ECHO_CONFIG_FILE=./echo.yaml ECHO_ENV_FILE=./.env uv run echo-ai
```

These prefixes apply only to that command. `uv run` uses the checkout; installed
`echo-ai` uses a separate tool environment. Source edits do not update the installed
copy; reinstall with `uv tool install --force --from . echo-ai` when ready.
Setup targets global settings unless you supply `--path`, even when
`ECHO_CONFIG_FILE` points at development configuration. For independent scratch
settings and sessions, also set `XDG_CONFIG_HOME` and `ECHO_STATE_DIR` to temporary
development directories.

See [Security essentials](security.md) for execution risks, approvals, and data privacy.

## Other providers

For a LiteLLM provider, set `provider`, the unprefixed `model` name,
`request_format: standard`, and `api_key_env` under `local-model`. Use
`base_url: ""` for the provider's default endpoint, and set compatible context,
output, sampling, and reasoning limits. Keep `return_reasoning: false` until
the provider's history format has been tested. Cloud compatibility still needs
validation with actual credentials; `echo-ai status` currently checks a
server's `/models` endpoint and does not verify every cloud provider.

These settings can live directly in your user YAML; adding a file to the
package templates is unnecessary.

## Reset local state

To remove the default local state, stop all Echo processes first. The following
deletes the entire state directory, including saved sessions and their recovery
data; it cannot be undone. If you configured `ECHO_STATE_DIR`, use that location
instead.

```bash
rm -rf ~/.local/share/echo-ai/
```
