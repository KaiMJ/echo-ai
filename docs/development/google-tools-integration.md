# Google tools integration: minimal architecture

## Scope

Echo should let the agent find Google Drive files and read or update Google Sheets. A job applications tracker is the first workflow to exercise it, not a special case in the core. Start with one Google account per local Echo installation and user-provided Desktop OAuth credentials.

The first useful slice is: authenticate from the CLI, find an existing spreadsheet, inspect its tabs, read a range, and append or update rows. File uploads, downloads, sharing, deletion, Gmail, Calendar, service accounts, and multiple accounts can wait.

This is an implementation plan. The commands, environment-variable handling, modules, and Google tools below do not exist yet. It shares the tool-router design in [web and computer-use architecture](web-and-computer-use-architecture.md); implement that router once and attach Google as another host service.

## Current user workflow

The published [Google tools guide](../guides/google-tools.md) describes the working OAuth smoke test in [`examples/google_smoke_test.py`](../../examples/google_smoke_test.py), including Cloud Console setup, credential paths, automatic token generation, and troubleshooting. Keep instructions for running that example in the guide.

The example performs Drive discovery and Sheets metadata reads. It is not yet connected to Echo's agent loop and does not implement the CLI commands below. Its environment variables are supported by the example; runtime configuration still needs implementation.

## Distribution and configuration

Use user-provided Desktop OAuth credentials for the first version. Each installation uses its owner's Cloud project and account. A shared public OAuth application is a separate distribution choice with consent-screen and verification requirements; see Google's [OAuth app state overview](https://developers.google.com/identity/protocols/oauth2/production-readiness/overview).

For the packaged integration, default credentials to `~/.config/echo-ai/google/credentials.json` and generated tokens to `~/.local/share/echo-ai/google/token.json`. Let `google auth` accept the downloaded client path and copy it into the private configuration directory. Users should not need to configure a token filename. Preserve `GOOGLE_CREDENTIALS_FILE` and `GOOGLE_TOKEN_FILE` as explicit development overrides; existing `scripts/` paths continue to work.

Expand `~`, respect existing process environment variables over `.env`, and reject relative paths in the packaged integration so workspace changes cannot silently select another account. The standalone example currently resolves relative paths from the checkout root.

Commit integration code, dependency metadata, placeholder configuration, documentation, and mocked tests. Never commit downloaded credentials, generated tokens, or personal Google data. The root ignore rules cover conventional credential/token filenames, `.env`, and `/scripts/`; they do not untrack previously committed files.

## Boundaries

```text
agent loop + permissions + SQLite transcript
                  |
             tool router
             /         \
    workspace tools    GoogleService (host)
    local / Docker       |             |
                     Sheets API     Drive API
                           \         /
                          GoogleAuth
                              |
                   local credentials + token
```

`Agent` continues to validate calls, check permissions, and record results. The router dispatches `google_*` calls to a host-owned `GoogleService`. Google clients and token refresh stay outside the disposable workspace sandbox, allowing the same tools in local and sandbox sessions without copying credentials into Docker.

Use `gspread` for Sheets and `google-api-python-client` for Drive, sharing credentials from `google-auth-oauthlib`. These clients are synchronous: run their operations off the async agent loop and serialize access to each service's clients. Set finite network timeouts. Cancellation of an awaiting task does not necessarily stop an in-flight HTTP request; preserve that distinction for writes.

Keeping tokens out of Google tool arguments prevents accidental model exposure, but `.gitignore` is not a security boundary. In local mode, Echo's existing file and bash tools can access files available to the process, including `scripts/`. Do not describe this arrangement as isolating secrets from arbitrary local code execution. Review workspace-copy behavior before sandbox support to ensure these files are excluded there too.

## Proposed repository structure

```text
src/echo_ai/
  google/
    auth.py                  # load, authorize, refresh, persist, revoke
    service.py               # bounded model-facing operations
    sheets.py                # gspread adapter
    drive.py                 # Drive API adapter
  runtime/
    tools.py                 # Google schemas and conditional registration
    tool_router.py           # shared workspace / web / browser / Google router
    permissions.py           # Google write authorization
  config/
    settings.py              # integration configuration
    file.py                  # environment paths and validation
  cli.py                     # google auth / status / disconnect

tests/
  test_google_auth.py
  test_google_service.py
  test_tool_router.py
  test_permissions.py

scripts/                     # ignored local files; not packaged code
  google_credentials.json    # downloaded from Google
  google_token.json          # generated by Echo after consent
```

Add Google dependencies as an optional `google` extra so the base coding agent does not need them. The implementation step would use:

```bash
uv add --optional google gspread google-auth-oauthlib google-api-python-client
```

After that extra exists, users install it with `uv sync --extra google`. Import Google libraries lazily and report a clear installation instruction when the extra is missing.

## Authentication commands

These are proposed CLI commands, not model-facing tools:

| Command | Behavior |
| --- | --- |
| `echo-ai google auth` | Validate configuration, open browser consent when needed, and save usable credentials |
| `echo-ai google status` | Report configured paths, token state, required scopes, and whether refresh succeeds; never initiate browser login |
| `echo-ai google disconnect` | Revoke the saved authorization and remove the local token; retain the downloaded client configuration |

Resolve credential and token paths using the private defaults above, with independent environment overrides. Enable Google tools when a client configuration exists; otherwise omit them. A missing token file is an unauthenticated state, not an invalid path configuration. If configured but unauthenticated, tool calls return `auth_required` with the CLI command to run; they must not unexpectedly open a browser during an agent turn.

`google auth` uses `InstalledAppFlow.from_client_secrets_file(...)` and `run_local_server(port=0)` with a loopback callback and a normal system browser. Validate that the downloaded client is a Desktop (`installed`) client. The initial milestone assumes Echo runs on the machine where the user can open the browser; remote/headless authorization needs an explicitly documented callback-forwarding flow later.

Token lifecycle:

1. Read an existing authorized-user token and validate its recorded scopes against the required set. Do not treat passing new scopes to a loader as proof that the user granted them.
2. Reuse a valid token. Refresh an expired access token when a refresh token is available.
3. If authorization is absent, revoked, or missing required scopes, return `auth_required` from normal tools. Only the explicit auth command initiates consent.
4. Persist new or refreshed credentials using an atomic replacement and owner-only file permissions (`0600`). Lock token updates across Echo processes to avoid concurrent refresh/write races.
5. Redact tokens and client secrets from logs, exceptions, tool results, and transcripts. Report malformed JSON with a filename and remedy, without echoing its contents.

Do not automatically erase a token on transient network failures. If revocation fails during disconnect, report that remote authorization may remain active; do not claim a completed disconnect. Scope changes require fresh consent when the current grant is insufficient.

## OAuth scopes

The first milestone needs spreadsheet edits plus discovery of existing files across the account. Request:

```python
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]
```

The Sheets scope allows spreadsheet reads and writes. Drive metadata access supports discovery without granting Drive file-content downloads, uploads, deletion, or sharing. It still exposes account-wide file metadata and is classified as restricted by Google.

Google recommends the narrower `drive.file` scope for files created by or explicitly opened/selected for an app. That is a useful later design with a file-selection flow, but it is not a drop-in replacement for searching arbitrary existing Drive files. Merely passing an arbitrary file ID does not grant per-file access. See the [Drive scope guide](https://developers.google.com/workspace/drive/api/guides/api-specific-auth) and [Google API scope reference](https://developers.google.com/identity/protocols/oauth2/scopes).

Keep scopes fixed in the service initially; the model cannot request broader permissions. Enabling the Drive API does not mean full `drive` scope is required.

## Model-facing tools

Add a `GOOGLE_TOOLS` group to `runtime/tools.py`, enabled when the client configuration exists. Child agents retain their existing workspace-only tool set initially.

| Tool | Input | Result |
| --- | --- | --- |
| `google_drive_search` | `name_contains`, optional `mime_type`, `parent_id`, `limit`, `page_token` | File IDs, names, MIME types, links when available, next page token |
| `google_sheets_info` | `spreadsheet_id` | Spreadsheet title and bounded tab IDs, titles, and dimensions |
| `google_sheets_read` | `spreadsheet_id`, `range` | Resolved range and bounded rows of cell values |
| `google_sheets_append` | `spreadsheet_id`, `range`, `values` | Updated range and row/cell counts |
| `google_sheets_update` | `spreadsheet_id`, `range`, `values` | Updated range and row/cell counts |

Use a spreadsheet ID after discovery; do not reopen by title because titles are not unique. Require fully qualified A1 ranges such as `'Applications'!A1:F50`. For append, the range identifies the table to append to, such as `'Applications'!A:F`; return Google's actual updated range so the caller knows where rows landed.

Build Drive query syntax inside the adapter, escape user-supplied names, and exclude trashed files. Request only the metadata fields used by the response. Return a page token rather than silently fetching every file. Keep conservative limits beside the implementation: for example, 20 search results by default, at most 100 per page, and 1,000 cells per Sheets read or write. Bound serialized output as well as item counts and explicitly report truncation. Reject oversized writes before dispatch.

Use `RAW` value input for writes initially so supplied strings are stored as data rather than interpreted as formulas. Require rectangular value arrays and validate update dimensions against the target range. Do not expose arbitrary Sheets batch requests, Drive query expressions, or API method names to the model.

Example append call:

```json
{
  "spreadsheet_id": "SPREADSHEET_ID",
  "range": "'Applications'!A:F",
  "values": [["Google", "Senior Engineer", "Applied", "2026-09-20", "", ""]]
}
```

## Concrete integration changes

### Dispatch and lifecycle

Attach `GoogleService` to the shared `ToolRouter` proposed by the browser architecture. If it has not been implemented yet, add the narrow router first and preserve workspace streaming behavior. Replace workspace-only execution dispatch in `Agent` with router execution while retaining the existing workspace object for revisions and delegation.

Construct the Google service lazily in the CLI and close its clients during existing cleanup paths. Keep browser authorization outside service construction. A revoked token should produce a useful tool error without preventing unrelated workspace work.

### Permissions and external writes

The current `Permissions.check` only gates `bash`, `write`, and `edit`; adding Google schemas alone would allow Google writes without review. Extend this path before registering append/update tools. Reads can proceed under the user's configured Google authorization. Writes should use the existing permission mechanism, respecting authorization already given for the concrete operation.

Before a write, present the spreadsheet, tab/range, operation, and bounded value preview. Any reusable authorization must be scoped to the operation and spreadsheet/range, not all Google tools. Define noninteractive behavior and how the existing `--yolo` bypass applies explicitly; keep behavior consistent with Echo's permission model.

Google writes are external changes. Workspace `/undo` and `/redo` cannot reverse them. Record the actual updated range and outcome in the transcript without recording authentication material. For updates, a preflight read can inform review, but it does not provide an atomic compare-and-swap guarantee against concurrent human edits.

### Errors, retries, and cancellation

Return stable error categories such as `auth_required`, `permission_denied`, `not_found`, `invalid_range`, `rate_limited`, and `outcome_unknown`, with short actionable messages. A missing API enablement or insufficient grant should not be reported as a missing spreadsheet.

Use bounded backoff for safe reads on transient errors. Do not blindly retry an append after timeout or cancellation: the row may already exist. Reconcile by reading the affected table before another attempt, and report uncertainty when duplicate-looking rows cannot be distinguished. Treat interrupted updates as potentially completed too; inspect current values before repeating a write. Disable automatic mutation retries that could duplicate external effects.

Drive names and spreadsheet cells are untrusted task data, not instructions that can change permissions. Tool results become part of Echo's transcript and may be sent to the configured model provider; fetch only the ranges needed for the task.

## Build order

1. Add the optional dependency extra, environment-path handling, ignore rules, and `.env.example` placeholders. Implement `auth`, `status`, and `disconnect`; verify missing files, first consent, cached tokens, refresh, insufficient scopes, and redaction with mocks.
2. Add or reuse `ToolRouter`, preserving workspace behavior. Implement Drive search plus Sheets info/read. Test query escaping, pagination, limits, range validation, and unauthenticated tool results.
3. Extend permissions and add append/update with exact target previews and `RAW` input. Test denied writes, bounded payloads, API outcomes, and timeout/cancellation handling without duplicate retries.
4. Confirm sandbox workspace copies exclude credential and token files and that Google calls remain host-side. Keep delegated children without Google tools in the first version.
5. Run a manual smoke test against a user-owned disposable spreadsheet: authenticate, find it, inspect tabs, read cells, approve an append, update a known range, and read back the result. Keep live credentials and personal data out of CI.

The first milestone is an agent that can find an existing tracker, read its contents, and perform an authorized row change while keeping authentication entirely in the host integration.
