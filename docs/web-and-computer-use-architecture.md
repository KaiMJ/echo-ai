# Web research and browser use: minimal architecture

## Scope

Echo should support research and general browser tasks. Job applications are the first workflow to exercise it, not a special case in the core. Keep the existing workspace `search` tool distinct from internet search.

The first useful slice is: search the web, read a result, open a page in a browser, inspect its interactive controls, fill fields, and stop before a consequential final action for user review. One agent loop and one browser session are enough. Task memory, multiple browser agents, a crawler, and a universal page model can wait.

## Boundaries

```text
agent loop + permissions + SQLite transcript
                  |
             tool router
             /         \
   workspace tools    web tools (host service)
   local / Docker       |             |
                 search + HTTP    Playwright browser
                    fetch         session
```

`Agent` continues to validate calls, check permissions, and record tool results. Add a small router to dispatch `web_*` and `browser_*` calls to host services; the workspace runner remains responsible for file and bash tools. A browser cannot be a fresh sandbox subprocess per call because tabs, cookies, and page state must persist. The router owns a `WebSearchService` and a client for the session-owned `BrowserSession`. Cancel the in-flight browser request on turn cancellation while preserving the page for inspection; close the context when the Echo session exits.

The browser uses Playwright's async Python API. Use a dedicated browser context with its own profile/state; do not silently attach to the user's ordinary browser. Default to a visible browser for application tasks so the user can inspect progress. Keep a single active tab initially, with explicit tab IDs only when a site opens another tab.

## Reuse from `KaiMJ/interface`

Reuse the desktop and handoff shell from the earlier project:

- Xvfb provides one fixed virtual display.
- A lightweight window manager keeps the Chromium window focused and correctly sized.
- Playwright launches headful Chromium on that display and owns the browser process.
- x11vnc exposes the same display, while noVNC/websockify makes it visible at a loopback URL such as `http://localhost:6080`.
- A single control token prevents the agent and user from sending input at the same time. The user can take over the same browser, including its cookies and partially completed form, then return control.

VNC is the viewing and human-handoff channel; it is not the model-facing automation protocol. Playwright should still perform browser actions, and the accessibility/DOM observation layer should tell the model which controls exist. This keeps routine browser use semantic and reliable while preserving visual inspection and takeover for CAPTCHAs, login, broken accessibility, and uncertain final steps.

The smallest deployment can be one long-lived `browser` container derived from the earlier `desktop` service. It contains Xvfb, the window manager, Chromium, Playwright, x11vnc, noVNC, and a small browser control server. Bind noVNC to `127.0.0.1:6080` on the host. Echo calls the control server over a private Compose network or a loopback-only host port. Do not put the browser inside Echo's short-lived workspace sandbox; its lifecycle and network policy differ, and it must survive across tool calls and human handoff.

The reusable pieces are the desktop packages and image setup, `backend/image/entrypoint.sh`, the headful Playwright launch and sizing logic in `backend/src/cua/action/browser.py`, the session/control-token idea, and the noVNC client. Leave the OCR, coordinate resolver, capability recording/replay, evidence UI, target app, and GPU dependencies out of the first Echo implementation. Those solve visual or desktop automation and can be added later as a fallback behind the same browser tool contract.

## Proposed repository structure

Keep browser infrastructure separate from the disposable coding sandbox:

```text
src/echo_ai/
  runtime/
    agent.py                 # validation, permission check, transcript
    tools.py                 # model-facing schemas
    tool_router.py           # route workspace, web, and browser calls
    permissions.py           # browser action review rules
  web/
    search.py                # SearchBackend + SearXNG implementation
    fetch.py                 # guarded HTTP fetch and redirects
    extract.py               # bounded readable text and links
    service.py               # web_search / web_open orchestration
  browser/
    client.py                # async HTTP client used by ToolRouter
    protocol.py              # request/result types and action names
  config/
    settings.py              # endpoint, limits, feature flags
    file.py                  # YAML names for those settings

browser_service/
  Dockerfile                 # Chromium and desktop image
  entrypoint.sh              # Xvfb -> window manager -> VNC -> API
  server.py                  # small loopback/private-network API
  session.py                 # Playwright context/page lifecycle
  observe.py                 # ARIA/DOM -> controls with refs
  actions.py                 # ref resolution and Playwright actions
  control.py                 # automation/user ownership token

tests/
  test_tool_router.py
  test_web_service.py
  test_web_fetch.py
  test_browser_client.py
  browser_service/
    test_observe.py
    test_actions.py
    fixture_site.html
```

`browser_service/` is intentionally a small service rather than part of `workspace/`. The existing workspace classes create short-lived subprocesses or containers and close them after a tool call. Browser state must outlive individual calls, and the browser requires network access that the coding sandbox intentionally lacks.

## Concrete integration changes

### Tool definitions

Add the five schemas to `src/echo_ai/runtime/tools.py`. Split the current `TOOLS` constant into `WORKSPACE_TOOLS`, `WEB_TOOLS`, and `BROWSER_TOOLS`, then let `tools_for(config)` include only enabled groups. Children should initially retain the current read-only workspace tools and receive no web or browser tools.

Make stale observations explicit in the action contract:

```json
{
  "action": "fill",
  "page_id": "p1",
  "observation_id": "o17",
  "target": "e4",
  "value": "person@example.com"
}
```

The service must reject a target when `observation_id` is no longer current. A new observation replaces the ref table. Refs are opaque identifiers, never CSS or XPath supplied by the model.

### Dispatch

Create `src/echo_ai/runtime/tool_router.py` with one narrow interface:

```python
class ToolRouter:
    async def execute(self, name: str, args: dict, on_output=None) -> dict: ...
    async def preflight(self, name: str, args: dict) -> dict: ...
    async def close(self) -> None: ...
```

`execute` routes `list/read/search/write/edit/bash` to the existing workspace, `web_*` to `WebService`, and `browser_*` to `BrowserClient`. `preflight` is normally a pass-through. For `browser_act`, it asks the browser service to resolve the referenced control and returns its role, accessible name, form type, URL, and risk classification before Echo asks for permission.

Change `src/echo_ai/runtime/agent.py` to accept a router alongside the existing `sandbox`. Keep `sandbox` because revisions and delegation still use it. Replace only the `sandbox.execute[_stream]` call with `router.execute`. The current validation, metrics, transcript recording, unknown-outcome recovery, and edit checkpoints remain in `Agent`.

Create the router in `src/echo_ai/cli.py` after the Echo session ID is known. Construct `BrowserClient` with that ID so the service can associate the browser context with the Echo session. Close the router in every existing cleanup path next to `sandbox.close()`. On Ctrl-C, cancel the active request but retain the browser context; on CLI exit, request a clean context close. A service crash makes the next browser call return `browser session unavailable` rather than falling back to a different page silently.

### Browser service

The service owns a `BrowserSession` containing Playwright, browser context, active page, current observation/ref table, and control token. Start with one active session and serialize its operations with an `asyncio.Lock`. Return HTTP `409` if another Echo session owns the browser. This matches the earlier project's one-display constraint and avoids interleaved actions.

Minimum private API:

```text
POST /sessions/{echo_session_id}/open
POST /sessions/{echo_session_id}/observe
POST /sessions/{echo_session_id}/preflight
POST /sessions/{echo_session_id}/act
POST /sessions/{echo_session_id}/control/yield
POST /sessions/{echo_session_id}/control/resume
DELETE /sessions/{echo_session_id}
GET  /health
```

`observe.py` should walk visible interactive elements in the page, derive role and accessible name, and create a server-side mapping from each ref to a Playwright locator recipe or element handle. Include visible headings and a bounded text excerpt for context. Limit control count, text size, DOM traversal time, and iframe depth. Include same-origin frames first; report inaccessible cross-origin frames rather than flattening them incorrectly.

`actions.py` resolves the ref inside the current observation, requires one visible enabled target, performs the Playwright action, waits for DOM content or a short quiet interval, then returns a new observation. Use Playwright locators for actionability and retry behavior. Do not accept JavaScript, selectors, coordinates, keyboard shortcuts, or arbitrary CDP commands from the model in the initial API.

Copy the earlier desktop startup sequence into `browser_service/entrypoint.sh`: start Xvfb, wait for the display, start the window manager, x11vnc, noVNC/websockify, then the browser API. Copy only the Chromium launch, sizing, and display-origin checks needed by `session.py`. The API listens inside the Compose network; publish it as `127.0.0.1:8002` only if Echo runs on the host.

### Docker Compose

Add `browser` and later `searxng` services to `compose.yaml`. The browser service needs a larger shared-memory allocation for Chromium. Publish only noVNC and the optional control endpoint on loopback:

```yaml
browser:
  build: ./browser_service
  shm_size: 1gb
  ports:
    - "127.0.0.1:6080:6080"
    - "127.0.0.1:8002:8002"
  volumes:
    - browser-state:/data/browser
```

Do not publish raw VNC port 5900. The internal noVNC proxy can reach it inside the container. Store per-session Playwright profiles beneath `/data/browser`, with directory permissions `0700`. Add an explicit command to clear them because they can contain authenticated cookies. For the first milestone, retaining state across tool calls is required; retaining it across container restarts can remain configurable.

### Configuration

Start with two public settings:

```yaml
tools:
  web:
    searxng_url: ""       # for example http://127.0.0.1:8888
  browser:
    service_url: ""       # for example http://127.0.0.1:8002
```

Add `searxng_url` and `browser_service_url` to `src/echo_ai/config/settings.py` and map those two names in `src/echo_ai/config/file.py`. A non-empty URL enables the corresponding tool group; an empty value disables it. This removes separate feature flags and prevents enabled-but-unconfigured states.

Keep result counts, response sizes, extraction length, control count, redirect count, and timeouts as conservative constants beside the code that enforces them. Promote one to `RuntimeSettings` only when users have a real reason to tune it. Private-network navigation is a security policy rather than a convenience setting: deny it by default in the fetcher and browser service, and add a deliberate allowlist later if local-site automation becomes a requirement.

### Permission path

Extend `src/echo_ai/runtime/permissions.py` after router preflight. Navigation, observation, scrolling, and ordinary field entry can run without a prompt. Require an interactive approval for an action classified as `external_commit`, including form submission, sending a message, purchasing, accepting terms, deleting data, or changing an account. Uploads receive a separate file-access check.

The browser service performs its own conservative classification from the resolved element and surrounding form metadata. The model cannot lower the risk by choosing an argument. Permission details shown in `src/echo_ai/cli.py` should include page URL, control name, action, and a redacted summary of values that will be committed. The service checks the observation ID again after approval, so the approved target cannot be replaced by a changed page.

## Model-facing tools

Keep calls narrow and results bounded. Suggested first schemas:

| Tool | Input | Result |
| --- | --- | --- |
| `web_search` | `query`, optional `limit` | Ranked title, URL, snippet, fetch status, short extracted text, timestamp |
| `web_open` | `url` | HTTP page title, final URL, readable text, links, fetch status |
| `browser_open` | `url` | Browser observation |
| `browser_observe` | optional `focus` | Browser observation |
| `browser_act` | `action`, `target`, optional `value` | Action outcome and fresh observation |

`browser_act.action` starts with `click`, `fill`, `select`, `check`, `uncheck`, and `upload` (from an explicitly allowed local path). Navigation can use `browser_open`. Do not expose arbitrary JavaScript evaluation to the model in the first version. Keep screenshots as an optional observation field for pages whose accessible structure is inadequate; do not make screenshots the only interface.

An observation should include `page_id`, `url`, `title`, a short readable page excerpt, and a bounded list of visible controls. Each control gets a transient `ref` plus role, accessible name or label, state, and useful attributes such as required/options. The agent acts on a `ref` from the latest observation. Resolve it to a Playwright locator, require one actionable match, and return a fresh observation after each action. If the page changed, the ref is stale: return an error and ask for a new observation. Prefer role/label locators and Playwright auto-waiting to coordinate with dynamic pages. An ARIA snapshot can seed the observation, but Echo's refs and structured fields should be its own small representation so the model-facing contract is stable.

Example:

```json
{
  "page_id": "p1",
  "url": "https://example.org/apply",
  "title": "Apply",
  "controls": [
    {"ref": "e4", "role": "textbox", "name": "Email", "required": true},
    {"ref": "e5", "role": "button", "name": "Submit application"}
  ],
  "text": "Application for Software Engineer ..."
}
```

## Research path

Implement the existing [web search plan](web-search-plan.md) first: local SearXNG for discovery, then bounded HTTP fetching and readable-text extraction. Preserve the difference between a search snippet and content actually fetched from a page. Return source URL and fetch time with each text excerpt. `web_open` handles a known URL and lets the agent follow links or inspect a page in more depth without repeating a search. Use the browser for JavaScript-rendered or interactive pages only when HTTP content is insufficient.

The search backend and page fetcher need narrow interfaces (`search(query, limit)` and `fetch(url)`); there is no need for a general plugin system yet. Search results can later point to cached content without changing model-facing tools.

## Action policy and sensitive data

Page text, labels, and links are untrusted observations. They may inform the task but must not override the user's instructions or tool policy. Apply URL validation to arbitrary HTTP fetches as described in the web search plan. Browser navigation also needs a policy for allowed schemes and local/private addresses; any intentional local site use should be an explicit configuration choice.

Classify browser actions before execution. Reading, navigating, and filling fields are routine. `browser_act` must pause for user review before a final submit, purchase, message send, account change, or other consequential action. Show the current page, intended action, and relevant filled values for review. A job application is complete only after the user approves submission and the agent observes the resulting confirmation. Uploads should be limited to user-provided or explicitly selected files. Keep credentials in browser state or an explicit user handoff, not in tool arguments or persistent transcripts when avoidable.

Reuse Echo's permission hook for action approval, but provide richer browser context than a bare tool name. Record the approval decision and action outcome in the session log. If execution is interrupted after a potentially consequential action, treat the outcome as unknown and inspect the site before retrying, matching Echo's current tool-call recovery behavior.

## Build order

1. Add `src/echo_ai/web/`, the `web_search`/`web_open` schemas, and configuration. Verify against a fake SearXNG response and fixture pages; no browser container is needed for this slice.
2. Add `runtime/tool_router.py` and route the existing workspace tools through it. Keep behavior identical and run the current suite before attaching new services. This isolates the main agent-loop change.
3. Add `browser_service/`, `browser/client.py`, and Compose wiring. Implement `open`, `observe`, and `click` on a local fixture site. Verify observations, refs, stale refs, exclusive session ownership, cancellation, and VNC visibility.
4. Add form actions (`fill`, `select`, `check`, `upload`) and permission preflight. Exercise a realistic multi-page application fixture, including validation errors, user takeover, return of control, final-action approval, and a confirmation page.
5. Try one real application site with a user-controlled test profile. Use failures to improve observation quality or action resolution before adding memory, multiple tabs, or broader automation.

The first milestone is an agent that can find a page, read it, navigate to an application form, fill it, and present the completed form for review. That validates both research and computer use without making the core architecture job-specific.
