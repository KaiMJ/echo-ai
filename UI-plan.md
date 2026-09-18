# Echo AI - Next-Generation TUI Architecture & Implementation Plan

This document outlines the design, architectural integration, and implementation plan for a state-of-the-art Terminal User Interface (TUI) for **Echo**.

---

## 1. Executive Summary & Design Principles

Echo is a small, local coding agent designed for Linux. It runs **Gemma on local vLLM** and executes tools inside **disposable, isolated Docker workspaces**, leaving the host repository checkout untouched.

An ideal TUI for Echo must not resemble a generic web chat box. It is designed as an **autonomous engineering cockpit** centered on five principles:

1. **Inference Telemetry Transparency**: Live metrics on Time-To-First-Token (TTFT), tokens/sec, KV cache utilization, and segmented token budget.
2. **Container Sandbox Security**: Clear, visual boundaries between the host repository and the isolated Docker container workspace.
3. **Subagent Topology Visibility**: Real-time tracking of parent orchestration vs. read-only child review subagents with distinct call budgets.
4. **Differential Safety & Hunk Staging**: Side-by-side diff inspection comparing the host checkout against the disposable sandbox before patches are applied.
5. **Session Time-Travel & Interruption Safety**: Interactive replay and branching powered by Echo's SQLite WAL persistence layer.

---

## 2. ASCII Mockups & Interface Specifications

### View 1: The 3-Column Master Cockpit (110 Columns)
The primary interface for monitoring the model loop, tool executions, subagents, and telemetry simultaneously.

```text
╭─ Echo ── [sess_8f3a] ───┬─ Agent Stream (Turn 4/20) ───────────────────────────────┬─ Telemetry & Diffs ───╮
│ REPOSITORY & SESSION    │ > User: Fix toolbar overflow when model name is long.    │ INFERENCE (vLLM)      │
│ repo: echo-ai (main)    │                                                          │ Model: gemma-4-26B-AWQ│
│ sess: 8f3a9e12-c5f0     │ ▼ Thought Stream (3.1s) ...................... [F2 Trace]│ TTFT: 142ms · 39 tok/s│
│ db: SQLite WAL active   │   • Inspected ui.py; candidates list exceeds width.      │ vLLM KV Cache: 38%    │
├─────────────────────────┤   • Truncating candidates[:width] prevents wrapping.     │ GPU VRAM: 14.8/24 GB  │
│ AGENT TOPOLOGY          │                                                          ├───────────────────────┤
│ ● Echo [Parent Orchestr]│ ✓ Tool: edit src/echo_ai/ui.py .................... [Done]│ CONTEXT WINDOW        │
│   status: waiting       │   - 271: candidates = [f"{self.model} · {details}"]      │ Tokens: 42.1k / 262.1k│
│   budget: 6/20 steps    │   + 271: candidates = [f"{self.model} · {details}"[:w]]    │ [████░░░░░░░░░░░░░░]16%│
│ └─● Reviewer [Child]    │                                                          │ Guard: 3 chars/token  │
│     mode: read-only     │ ▼ Subagent: Reviewer [Child] ................... [Running]│ Out Reserve: 16k tok  │
│     status: inspecting  │   Mission: "Verify diff edge cases on 80-col terminal"    ├───────────────────────┤
│     calls: 2/8 limit    │   → read src/echo_ai/ui.py (lines 255-285)               │ DOCKER ISOLATION      │
├─────────────────────────┤   Findings: "Patch is safe; no index out-of-bounds."    │ Image: echo-sandbox   │
│ WORKING TREE DELTA      │                                                          │ Network: Disabled     │
│  ● M src/echo_ai/ui.py  │ ✓ Tool: bash `pytest tests/test_ui.py` ............. [Done]│ Mount: Copy (42.1MB)  │
│  ● + tests/test_ui.py   │   tests/test_ui.py::test_narrow_screen PASSED      [100%]│ Diff: 2 files changed │
│ [Press ^D for Diff View]│                                                          ├───────────────────────┤
├─────────────────────────┤ ● Echo: Truncation patch verified by Reviewer subagent.  │ HOTKEYS & SHORTCUTS   │
│ TIMELINE DAG            │   All 12 terminal tests passed inside Docker sandbox.    │ ^D Diff   ^T Shell    │
│  ✓ T1: User prompt      │   Ready to export patch or apply to host checkout.       │ ^S Store  ^R Review   │
│  ✓ T2: search "toolbar" │                                                          │ ^C Cancel ^P Palette  │
│  ✓ T3: edit ui.py       │                                                          │ [Tab] Focus Next Pane │
│  ▶ T4: delegate review  │                                                          │ [F1] Help  [F2] Trace │
│  ○ T5: run pytest       │                                                          │ [Esc] Normal Mode     │
╰─────────────────────────┴──────────────────────────────────────────────────────────┴───────────────────────╯
╭─ Mode: [NORMAL] ─────────────────────────── Command / Prompt Bar ──────────────────────── Press 'i' to Insert ─╮
│ echo › /diff                                                                                                   │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

---

### View 2: Side-by-Side Git Diff & Hunk Stager (`Ctrl+D`)
Provides side-by-side inspection of the disposable sandbox workspace against the host Git baseline with hunk-level controls.

```text
╭─ Original Checkout (Git Baseline: HEAD) ────────────┬─ Docker Sandbox (Disposable Copy) ───────────────────╮
│ File: src/echo_ai/ui.py [Hunk 1 of 2]   •   Reviewer: "Bounds check valid. No regressions."                │
├─────────────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ 269: def toolbar(self, *, streaming=False):         │ 269: def toolbar(self, *, streaming=False):          │
│ 270:     active = self.active                       │ 270:     active = self.active                         │
│ 271:     context = self.active_context_text()       │ 271:     context = self.active_context_text()         │
│ 272:     hint = "Ctrl-C cancel" if streaming...     │ 272:     hint = "Ctrl-C cancel" if streaming...       │
│ 273: -   candidates = [f"{self.model} · {det}"]     │ 273: +   # Truncate model candidate to width safe   │
│      -                                              │ 274: +   full = f"{self.model} · {details}"           │
│      -                                              │ 275: +   candidates = [full[:width], details, ctx]  │
│ 274:     if active.context is not None:             │ 276:     if active.context is not None:               │
│ 275:         prefix = "~" if active.estimated...    │ 277:         prefix = "~" if active.estimated...       │
├─────────────────────────────────────────────────────┴──────────────────────────────────────────────────────┤
│ HUNK ACTIONS:  [y] Stage Hunk   [n] Skip   [a] Accept All   [p] Export .patch   [Esc] Return to Chat       │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

---

### View 3: Live In-Container Sandbox Terminal Split (`Ctrl+T`)
Enables direct, interactive PTY access into the running Docker container (`docker exec -it echo-sbx-... bash`) without leaving the TUI.

```text
╭─ Echo Agent Stream ──────────────────────────────────────────────────────────────────────────── [Turn 4/20] ─╮
│ ✓ Tool: edit src/echo_ai/ui.py ..................................................................... [Done] │
│   Edited candidate string truncation logic in `src/echo_ai/ui.py`.                                          │
│ ● Echo: Sandbox workspace is ready. You can inspect or run test suites in the shell below.                 │
├─ Docker Container Shell: echo-sbx-8f3a9e [isolated · no-net] ────────────────────────── [Ctrl+T to toggle] ─┤
│ root@sandbox:/workspace# uv run pytest tests/test_ui.py -k "test_toolbar" -vv                               │
│ ===================================== test session starts =====================================            │
│ tests/test_ui.py::test_toolbar_narrow_screen PASSED                                                 [100%] │
│ ====================================== 1 passed in 0.42s ======================================             │
│ root@sandbox:/workspace# git status -s                                                                      │
│  M src/echo_ai/ui.py                                                                                        │
│ ?? tests/test_toolbar_regression.py                                                                        │
│ root@sandbox:/workspace# █                                                                                  │
╰─────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

---

### View 4: SQLite Session Time-Travel & Interruption Reconciler (`Ctrl+S`)
Visualizes the SQLite DAG tree, past turns, parent-child sessions, and interruption states.

```text
╭─ Echo AI ── [SESSION TIME-TRAVEL & INTERRUPT RECONCILER] ───────────────────────────────────────────╮
│ SQLite Store: ~/.local/share/echo-ai/echo.db (WAL Mode)  •  Lock: Acquired (PID: 40182)             │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ SESSION DAG & REPLAY TREE:                                                                          │
│  ● sess_3c1b82 (2 hours ago) [Completed · 14 steps · Exported patch: fix_cli.patch]                 │
│  ▼ sess_8f3a9e12 (CURRENT ACTIVE SESSION · 5/20 steps)                                              │
│    ├─ Turn 1 [User Prompt]: "Fix toolbar overflow on narrow terminals" (Tokens: +420)               │
│    ├─ Turn 2 [Model Call]: Thought + Tool Call `search` (TTFT: 142ms, +180 tokens)                  │
│    ├─ Turn 3 [Sandbox Edit]: Modified `src/echo_ai/ui.py` (+4, -2 lines)                            │
│    ├─ Turn 4 [Subagent Fork: sess_8f3a9e12_child1] (Read-only review subagent)                      │
│    │    ├─ Child Turn 1: `read(path="src/echo_ai/ui.py", offset=255, limit=30)`                    │
│    │    └─ Child Return: "Findings: Truncation check prevents IndexError. Safe to proceed."         │
│    └─ Turn 5 [Sandbox Bash]: `uv run pytest tests/test_ui.py` [IN PROGRESS ●]                       │
│         └─ Observation: Unknown outcome recovery ready if interrupted (^C).                         │
├─────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ TIME-TRAVEL ACTIONS:                                                                                │
│  [r] Replay Turn    [b] Fork New Branch at Step    [c] Inspect Checkpoint Diff    [Esc] Back to Chat│
╰─────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

---

## 3. Module & Codebase Mapping

The proposed TUI components directly bind to Echo's existing architecture:

| UI Component | Underlying Module | Data Sources & Callbacks |
|---|---|---|
| **Agent Stream & Reasoning** | `src/echo_ai/terminal.py` & `src/echo_ai/ui.py` | `Renderer.emit()` receives `reasoning`, `text`, `model_start`, `model_end`. Rendered via Rich Markdown with syntax highlighting. |
| **Tool Execution Cards** | `src/echo_ai/sandbox_tools.py` | Events: `tool_start`, `tool_detail`, `tool_output`, `tool_end`. Tracks arguments, diffs, and exit codes. |
| **Agent Topology Panel** | `src/echo_ai/agent.py` | Tracks parent `session_id` vs. child `delegate` invocations. Enforces call limits (20 parent vs. 8 child). |
| **Diff & Hunk Stager** | `src/echo_ai/sandbox.py` | Calls `Sandbox.diff()`, extracting unified diffs between the baseline Git reference and the container copy. |
| **Inference Telemetry** | `src/echo_ai/model.py` & `src/echo_ai/config.py` | Consumes `usage` payloads (`prompt_tokens`, `completion_tokens`, `ttft`), calculates token/sec and context ratio. |
| **Session Time-Travel** | `src/echo_ai/store.py` | Reads `sessions`, `runs`, and `messages` tables from SQLite WAL database; manages interruption reconciliation. |
| **Sandbox PTY Shell** | `src/echo_ai/sandbox.py` | Direct `docker exec -it <container_id> bash` attached via an asynchronous PTY wrapper. |

---

## 4. Interaction Model & Keyboard Ergonomics

The TUI supports standard modal workflows (`NORMAL`, `INSERT`, `DIFF_VIEW`, `SHELL_VIEW`, `DAG_VIEW`):

| Hotkey | Context | Action |
|---|---|---|
| `i` / `Enter` | Normal Mode | Enter **INSERT** mode to compose prompt. |
| `Esc` | Any Mode | Return to **NORMAL** mode or dismiss current modal/overlay. |
| `Alt+Enter` | Insert Mode | Insert a newline without sending prompt. |
| `Ctrl+D` | Global | Toggle **Side-by-Side Diff Inspector**. |
| `Ctrl+T` | Global | Toggle **Live Docker Sandbox Terminal Split**. |
| `Ctrl+S` | Global | Toggle **Session Time-Travel & DAG Replay**. |
| `Ctrl+C` | Running Turn | Safely interrupt turn (commits unknown outcome, cleans tool container). |
| `Tab` / `Shift+Tab` | Normal Mode | Cycle focus between Navigation, Main Stream, and Telemetry panes. |
| `F1` | Global | Open Keyboard Shortcuts & Slash Commands Help. |
| `F2` | Global | Expand/collapse the latest reasoning trace or tool execution output. |
| `PgUp` / `PgDn` | Stream Pane | Scroll conversation and execution history. |
| `Ctrl+End` | Stream Pane | Resume auto-following the newest streamed output. |

---

## 5. Phased Implementation Roadmap

### Phase 1: 3-Column Split & Rich Telemetry Layout
- Refactor `TerminalChat` to use a 3-column `prompt_toolkit` layout (`HSplit` and `VSplit`).
- Add visual gauges for context window tokens (`active.context / active.capacity`) and step budgets.
- Add real-time hardware telemetry display (TTFT, tokens/sec, vLLM endpoint health).

### Phase 2: Interactive Side-by-Side Diff Inspector
- Implement a two-column diff visualizer component using `prompt_toolkit.layout.Window` and Rich syntax rendering.
- Add hunk-navigation shortcuts (`[y]` stage, `[n]` skip, `[a]` accept all).
- Implement direct patch exporting to file (`echo-ai diff --output change.patch`) and direct application to host git repo.

### Phase 3: Interactive Sandbox PTY Terminal Split
- Implement an asynchronous PTY multiplexer in Python (`pty`, `os.openpty`) connecting to `docker exec -it <container> bash`.
- Allow hotkey-driven collapsing and expanding (`Ctrl+T`).
- Keep environment isolated so host repository is never mounted.

### Phase 4: Session DAG Visualizer & Time-Travel Replay
- Query SQLite database for all turns in current and parent/child sessions.
- Render tree structure showing model events, tool outputs, and child agent delegations.
- Provide turn rollback and branch session commands (`:fork <step_id>`).
