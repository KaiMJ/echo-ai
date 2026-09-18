# echo-ai

A local-first coding agent with a **prompt_toolkit REPL**, **Rich streaming renderer**, and a **Qwen model served by vLLM**.

**Status:** planning and host setup. The agent CLI is not implemented yet. The roadmap below is the current delivery plan; older design documents describe later possibilities where marked.

## Initial scope

Build one usable coding loop: enter a task, inspect repository context, edit files, run tests, and review the resulting diff. Start with one configured Qwen model and one active turn. Exact model IDs, revisions, and machine paths belong in local configuration.

```text
prompt_toolkit REPL → async agent loop → vLLM HTTP endpoint → configured Qwen model
                           │
                           ├─ coding tools → Docker sandbox / disposable checkout
                           ├─ SQLite session persistence
                           └─ typed events → Rich streaming renderer
```

The CLI owns the initial agent process. The loop, persistence, tools, and renderer have separate interfaces so a daemon or another client can be added later. A background daemon and IPC are not initial prerequisites.

- **Input:** multiline editing, history, basic commands, and cancellation through prompt_toolkit.
- **Output:** streamed assistant text, tool status, bounded tool output, errors, and diffs through Rich.
- **Inference:** an OpenAI-compatible vLLM endpoint; validate streaming and tool calling with the configured model.
- **Tools:** read, search, edit, and shell/test execution inside a disposable Docker workspace. Never give generated tools the host Docker socket.
- **State:** save messages, tool calls/results, turn status, and model/runtime configuration in SQLite. Start with sequential sessions; add branching and code restore after the loop works.

## Milestone roadmap

Progress is measured by working capabilities. All agent implementation milestones remain open.

- [ ] **M1: Working CLI coding agent**
  - Choose a compatible Qwen checkpoint and vLLM release; record revisions and launch settings. Keep the existing model cache on its data filesystem.
  - Build the prompt_toolkit REPL and Rich renderer with one active turn and deterministic terminal ownership.
  - Add streaming, validated tool calls, file editing, shell/test execution, cancellation, and basic SQLite persistence.
  - **Done when:** Echo completes a small repository change in the sandbox, runs tests, and presents an inspectable diff. A failed tool call is shown and handled; Ctrl-C returns to a usable prompt.
- [ ] **M2: Recoverable sessions and code checkpoints**
  - Resume saved sessions, reconcile interrupted tools, and add conversation branching.
  - Support explicit conversation-only, code-only, and combined restore with protection for newer user edits.
  - **Done when:** restart preserves the session without replaying uncertain side effects, and restore recovers the requested state without silently overwriting newer work.
- [ ] **M3: Echo helps build Echo**
  - Use Echo for small changes to its own repository with tests and diff review.
  - Generated tools use replaceable worker processes. Core changes use controlled CLI restart with session recovery.
  - **Done when:** Echo implements and tests a small improvement to itself and resumes after a required restart.
- [ ] **M4: Context and quality**
  - Add structured compaction, a small repeatable coding evaluation set, and usage/latency reporting.
  - **Done when:** longer tasks preserve essential context, and results and failure cases can be reproduced.
- [ ] **M5: Extensions and concurrency**
  - Add MCP and bounded subagents in worktrees when needed. Start with ordinary three-way merges and validate every integrated result.
  - **Done when:** a concurrent task produces a reviewed, tested integration with explicit conflict handling.

**Deferred:** Neovim, Web UI, daemon/IPC, model routing/Jev, alternative inference engines, prefix-cache tuning, speculative decoding, AST merging, and throughput optimization. Market and personal-assistant integrations remain future directions. Basic resource sizing and correctness checks are still required for M1.

## Setup and documentation

Host setup scripts are local utilities under `scripts/`; the entire directory is ignored by Git and is not included in a fresh clone. Weights and environments live outside the checkout. The vLLM/Qwen deployment still needs to be installed and validated. Local llama.cpp/GGUF and SGLang scripts are optional earlier experiments.

- [Current planning decisions and broader requirements](PROJECT.md)
- [CLI architecture](docs/architecture.md)
- [CLI interaction and rendering](docs/cli.md)
- [Local inference plan](docs/local-inference.md)
- [Session recovery and DAG](docs/sessions-and-dag.md)
- [Context engineering](docs/context-engineering.md)
- [UI resilience](docs/ui-resilience.md)
- [Evaluation and benchmarking](docs/evals-and-benchmarking.md)
- [Hooks and lifecycle](docs/hooks-and-lifecycle.md)
- [Skills and MCP](docs/skills-and-mcp.md)
- [Subagents and orchestration](docs/subagents-and-orchestration.md)
- [Multi-agent worktrees](docs/multi-agent-worktrees.md)
- [Deferred routing experiments](docs/system-one.md)
- [Deferred Neovim design](docs/neovim-integration.md)
