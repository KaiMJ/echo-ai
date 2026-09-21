# Skills & Tool Architecture: MCP Host & Dynamic Tool Genesis

## 1. Pluggable Tool Engine Overview

Echo’s tool engine is built on two core principles:
1. **Industry-Standard Model Context Protocol (MCP)**: Any Anthropic MCP server (PostgreSQL, GitHub, Slack, Google Drive) connects out of the box.
2. **Self-development and generated tools**: The agent can help implement Echo itself. New tools are tested and loaded in separate workers inside the Docker development sandbox. Core runtime changes use a controlled restart with session recovery.

```text
┌────────────────────────────────────────────────────────┐
│                   TOOL REGISTRY                        │
│                                                        │
│  ┌──────────────────────┐    ┌──────────────────────┐  │
│  │  Built-in Tools      │    │  Anthropic MCP Host  │  │
│  │  - read_file         │    │  - GitHub Server     │  │
│  │  - edit_chunk (AST)  │    │  - Slack Server      │  │
│  │  - run_bash          │    │  - Google Drive      │  │
│  └──────────────────────┘    └──────────────────────┘  │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │   Generated Tools (Separate Worker Processes)   │  │
│  │   - crypto_tracker/tools.py                      │  │
│  │   - travel_planner/tools.py                      │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## 2. Dynamic Tool Genesis Lifecycle

When a developer asks Echo to perform a task outside its core capabilities:
> *"Echo, build a skill that checks Solana gas fees and token liquidity using the DexScreener API, and track price slippage."*

Echo executes the following **4-stage self-extension pipeline**:

### Stage 1: Synthesis
The agent uses its core file tools to generate the skill package in `~/.config/echo/skills/dex_screener/`:
* `SKILL.md`: System prompt instructions, error recovery rules, and parameter formatting.
* `tools.py`: Python code defining `@tool` functions with strict Pydantic schemas.
* `test_tools.py`: Unit tests verifying API connectivity and schema validation.

### Stage 2: Verification in the Development Sandbox
Run tool tests in a separate process inside Docker. On failure, retain the previous working tool version while the agent repairs the candidate. Passing tests is a correctness check, not proof that code is safe or bug-free.

### Stage 3: Replace the Tool Worker
Start a worker for the tested tool version, load its schema, and perform a health check. Register it only after successful startup. The daemon exchanges structured requests/results with the worker rather than importing generated Python into its own process.

Initially, launching a fresh subprocess for each invocation is sufficient. A persistent worker can be added if startup cost matters. Worker processes contain crashes and import state; Docker and mount permissions provide the development filesystem boundary.

At replacement, let existing calls finish on the old version or explicitly cancel them; pin each invocation to a version. If startup fails, keep the old version active. Activate schema changes between model requests so an in-flight request retains the tool contract it was given.

### Stage 4: Use the New Version
Subsequent turns can invoke the new worker without restarting the daemon. Preserve tool versions and call results in the session record for diagnosis.

### Updating Echo's Core Runtime
For changes to the agent loop, session store, or daemon itself: edit the repository, test the candidate in a separate process, stop at a safe turn boundary, persist state, and restart the daemon. Resume the conversation after restart; reconcile interrupted tool calls before retrying. A file watcher may automate restarts later, but live-patching core Python objects is outside the initial design. Database changes need an explicit migration/recovery path before activation.

---

## 3. Anthropic Model Context Protocol (MCP) Host

Echo implements the official MCP Client specification. Community MCP servers are configured in `~/.config/echo/mcp_servers.json`:

```json
{
  "mcpServers": {
    "github": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "ghp_..."
      }
    },
    "postgres": {
      "command": "docker",
      "args": ["run", "-i", "--rm", "mcp/postgres", "postgresql://localhost/mydb"]
    }
  }
}
```

On daemon initialization, Echo discovers all tools exposed by the configured MCP servers, translates their JSON schemas into Echo-compatible tool specifications, and binds them to the universal ReAct execution loop.
