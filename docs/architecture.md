# Architecture: CLI coding agent

## Initial topology

The prompt_toolkit REPL, async single-agent loop, SQLite persistence, and Rich renderer run in one CLI process. A separate vLLM process serves the configured Qwen model over HTTP. Coding tools run within a Docker sandbox against a disposable checkout.

```text
CLI input → agent loop ↔ model adapter ↔ vLLM
                 ├─ session store (SQLite)
                 ├─ tool dispatcher ↔ sandbox
                 └─ typed events → renderer
```

Keep the loop independent of prompt_toolkit and Rich. The UI submits a task and cancellation requests; the loop emits events. A future daemon can reuse these interfaces without requiring IPC in M1.

## Responsibilities

- **Model adapter:** stream text, assemble tool-call fragments, expose finish/error conditions, and use configured endpoint/model settings.
- **Agent loop:** validate complete tool calls, sequence tool execution and follow-up inference, bound iteration, and track turn state.
- **Tool dispatcher:** enforce workspace scope, capture output, apply timeouts/cancellation, and return structured results. Generated tool processes cannot access the host Docker socket.
- **Session store:** persist messages, tool IDs/arguments/results, turn state, and configuration provenance. Record tool intent before execution and result afterward so interruption can be reconciled.
- **Renderer:** consume events and own terminal writes; it does not drive tools or alter session state.

Initial events include turn start, text delta, tool start, tool output, tool end, turn complete, cancellation, and error. Include session/turn IDs and ordering information. UI refresh batching must not lose semantic events or durable content.

## Later boundaries

Session branching and code checkpoints follow the working loop. Generated-tool workers and controlled core restart support self-development. Daemon IPC, Neovim, Web UI, routing, and concurrent agents are deferred. See the [roadmap](../README.md), [CLI contract](cli.md), and [recovery design](sessions-and-dag.md).
