# Current Planning Decisions

Echo's primary focus is a terminal coding agent using a prompt_toolkit REPL and Rich streaming renderer. Neovim is deferred. The [milestone roadmap](README.md) is the delivery plan; the broader requirements below describe the longer-term direction. There is no 30-day deadline.

- **Self-development:** Echo should help build itself. Generated tools use separate replaceable workers; core runtime changes initially require a controlled CLI restart with persisted session recovery.
- **Restore:** Support conversation-only, code-only, and combined restore. Code checkpoints and newer user edits need explicit handling; external side effects are outside code rollback.
- **Development assumptions:** Trusted single-user development inside Docker. Deliberate adversarial attacks are outside the initial scope; accidental deletion, hard resets, and broken generated code remain relevant. Use a disposable checkout, restrict writable mounts, and keep recovery snapshots outside the tool worker's writable reach. A writable host bind mount is still writable host data. Do not expose the host Docker socket to generated tools.
- **Incremental design:** Fill in implementation details as each milestone needs them. Before completing recovery, decide interrupted-tool behavior and checkpoint consistency; before editor integration, decide stale-buffer behavior.
- **Evaluation:** Numerical goals are adjustable hypotheses. Measure correctness, cost, and latency without committing to unsupported performance thresholds.
- **Inference:** Start with vLLM and the Qwen model family. Keep exact model IDs, revisions, parser settings, and machine paths configurable. Validate streaming and tool calling before tuning performance. llama.cpp/SGLang and serving optimizations are deferred. See [local inference](docs/local-inference.md).
- **CLI:** One active turn, prompt_toolkit input, Rich streaming output, and SQLite persistence. The CLI owns the initial agent process; a background daemon is deferred. See [CLI interaction](docs/cli.md).
- **Later scope:** Neovim, daemon/IPC, routing/Jev, serving optimization, market/personal domains, and the Web HUD are future directions. Multi-agent integration starts with ordinary merges and validation on every path.

---

## Broader requirements (deferred unless included in the roadmap)

The sections below retain longer-term ideas. Daemon, editor, routing, and multi-interface requirements are not M1 dependencies; the decisions above and README roadmap govern current work.

## 1. The Unified Backbone Philosophy

Echo Core is a single, event-driven runtime that provides:

1. State & Session DAG: Branching, rollbacks, and persistence for all agent activities.
2. Context Engine: Token budgeting, auto-compaction, and long-term memory.
3. Dynamic Model Router: Cost/performance optimization across frontier, small, and local models.
4. Universal MCP Host: Plug-and-play tool execution conforming to Anthropic's Model Context Protocol.
5. Multi-Interface Event Bus: Streams events simultaneously to Ghostty Terminal, Neovim, and the Web HUD.

  ┌──────────────────────────────────────────────────────────────────────────┐
  │                           SURFACE INTERFACES                             │
  │       [Ghostty Terminal TUI]    [Neovim Plugin]    [Web Showcase HUD]    │
  └────────────────────────────────────┬─────────────────────────────────────┘
                                       │ Async RPC / WebSocket Stream
  ┌────────────────────────────────────▼─────────────────────────────────────┐
  │                             ECHO RUNTIME                                 │
  │  ┌───────────────────────┬───────────────────────┬────────────────────┐  │
  │  │      Session DAG      │   Context Compactor   │    Model Router    │  │
  │  │   (Branch/Rollback)   │    (Token Budget)     │  (Fast vs Strong)  │  │
  │  └───────────────────────┴───────────────────────┴────────────────────┘  │
  │  ┌────────────────────────────────────────────────────────────────────┐  │
  │  │                      Universal MCP Tool Host                       │  │
  │  └────────────────────────────────────────────────────────────────────┘  │
  └────────────────────────────────────┬─────────────────────────────────────┘
                                       │ Tool Calls
          ┌────────────────────────────┼────────────────────────────┐
          ▼                            ▼                            ▼
  ┌──────────────────┐       ┌──────────────────┐       ┌──────────────────┐
  │   Coding Tools   │       │   Market Tools   │       │  Personal Tools  │
  │ (read/edit/bash) │       │ (ticker/signals) │       │ (calendar/slack) │
  └──────────────────┘       └──────────────────┘       └──────────────────┘
──────
## 2. Primary Use Cases

### Use Case 1: Autonomous Coding (In-Editor & Terminal)

• Trigger: Developer submits a task through the terminal REPL.
• Flow: Echo reads repository context and git diff, edits files and runs tests in the sandbox, and renders progress and the resulting diff with Rich.
• Rollback: If a suggested fix fails, the developer branches off an earlier session node in the DAG without losing the context tree.

### Use Case 2: Market Intelligence & Research ("Personal Bloomberg")

• Trigger: Developer queries a ticker or schedules morning market prep (echo market research NVDA).
• Flow:
    1. Market tool fetches price action, volume, and technical indicators (yfinance).
    2. News tool pulls SEC filings and breaking headlines.
    3. Echo synthesizes a structured research thesis (catalysts, risks, valuation).
    4. Echo renders an interactive chart in the Web HUD and high-density telemetry in the terminal.


### Use Case 3: Personal Assistant & Unified Notifications

• Trigger: A high-priority event arrives (e.g. Slack mention, calendar conflict) or user issues a voice/text prompt.
• Flow: Inbound event is normalized → Echo routes to a cheap fast model → evaluates urgency → pushes a non-intrusive notification to Neovim / Ghostty →
drafts a context-aware response.
──────
## 3. Functional Requirements (FRs)

### Subsystem 1: Echo Core Runtime (The Backbone)

• FR 1.1 (Session DAG): Must store all interactions as a Directed Acyclic Graph (DAG) in SQLite. Every turn must link to a parent_id, allowing branching
and arbitrary rollbacks.
• FR 1.2 (Token Budgeting & Compactor): Must track active tokens. When context hits 70% of the model window, an automated background summarization pass
must condense previous turns into a structured state checkpoint.
• FR 1.3 (Dynamic Model Router): Must route prompts based on task type:
    • Heuristics/Classification/Summaries: Configured low-latency model tier.
    • Complex Code & Deep Analysis: Configured high-capability model tier.
    • Local Offline: Configured local inference endpoint.
• FR 1.4 (MCP Host Integration): Must implement the official Model Context Protocol (MCP) client specification to load external tools dynamically via
JSON configuration.
• FR 1.5 (Streaming Event Bus): Must emit real-time event types (on_token, on_tool_start, on_tool_end, on_compaction, on_state_change) over WebSockets
and standard RPC.

### Subsystem 2: Coding Domain

• FR 2.1 (Filesystem & Shell Tools): Core tools for read_file, write_file, edit_chunk (exact regex/string replacement), and execute_bash.
• FR 2.2 (Deferred Neovim RPC Client - echo.nvim): Lua plugin communicating over Unix domain socket to:
    • Extract visual selection and file context.
    • Stream inline virtual text and side-by-side diff buffers.


### Subsystem 3: Market Research Domain

• FR 3.1 (Market Data Aggregation): Pull real-time quotes, historical candles, and technical indicators via Python data libraries.
• FR 3.2 (Research Agent Pipeline): Automated multi-turn synthesis that gathers data, checks sentiment/filings, and outputs a formatted Markdown
investment memo.
• FR 3.3 (Dual Visualization): Dense text/ASCII rendering for Ghostty Terminal; interactive TradingView Lightweight Charts on the Web HUD.

### Subsystem 4: Personal Intelligence & Infrastructure

• FR 4.1 (Tailscale Mesh Access): Echo daemon must be configurable to bind exclusively to the local machine or Tailscale IP (100.x.y.z), enabling secure
zero-trust remote access from phone/laptop without exposing ports to the public internet.
• FR 4.2 (Standard MCP Connectors): Provide pluggable connectors for Google Calendar, Slack (Socket Mode), and local system notifications.
──────
## 4. Non-Functional Requirements (NFRs)

• NFR 1 (Latency & Streaming): Measure Time-to-First-Token (TTFT) for configured models; set numerical goals after baseline measurements. Event bus streaming to terminal and Neovim must not block
the main event loop.
• NFR 2 (Memory & Footprint): Measure Echo Core daemon idle memory separately from inference servers and tool workers; adjust targets after baseline measurements.
• NFR 3 (Local-First Privacy): All API keys, SQLite databases, and session logs must be stored locally under ~/.config/echo/ or user-defined paths. No
telemetry sent to 3rd-party servers except model providers.
• NFR 4 (Developer Experience & Documentation):
    • 1-command startup (pip install -e . && echo start).
    • Comprehensive README.md with architecture diagrams and API specs.
    • High test coverage on the Session DAG and Compaction logic.

──────
## 5. Non-Requirements (Outside the Initial Coding-Agent Scope)

The initial release prioritizes the coding workflow. The following are excluded, alongside market/personal domains and the Web HUD:

 Feature                                   │ Why It Is Deferred                             │ Alternative / Phase 2
───────────────────────────────────────────┼──────────────────────────────────────────────────────┼──────────────────────────────────────────────────────
 Real-Money Brokerage Execution            │ Risk management, exchange APIs, compliance, and      │ Focus strictly on research, signal alerts, and data
                                           │ financial liability traps.                           │ synthesis.
 Bespoke iMessage / WhatsApp Scrapers      │ Apple sandbox workarounds, WhatsApp session bans,    │ Use Slack Socket Mode and Webhooks as reference
                                           │ and fragile unofficial protocols.                    │ integrations; add phone bridges later.
 Custom Chart Rendering Engine in Terminal │ Writing custom ANSI rendering loops from scratch     │ Use established terminal plotting libraries (rich /
                                           │ takes weeks.                                         │ plotext) + TradingView's open-source library for
                                           │                                                      │ Web.
 Multi-Tenant Cloud SaaS Infrastructure    │ Requires user auth, billing (Stripe), AWS multi-     │ Echo is a self-hosted, local-first power tool (like
                                           │ region setups.                                       │ Ollama or Aider).
 Training / Fine-Tuning Models             │ Costly and irrelevant to systems-level agent         │ Use dynamic routing, structured prompts, and context
                                           │ architecture.                                        │ compaction.
──────
