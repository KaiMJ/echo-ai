# Architecture

```text
prompt_toolkit / batch command
              |
         agent loop ---- vLLM HTTP stream
          |     |
       SQLite   tool dispatcher ---- disposable Docker container
          |
      parent / child sessions
```

The CLI owns one active turn. There is no daemon, message broker, or framework.
The loop is independent of terminal rendering, so tests can supply a fake model,
sandbox, and output callback.

| Module | Responsibility |
| --- | --- |
| `cli.py` | Commands, prompt, streaming display, cancellation, workspace lock |
| `config.py` | Shared .env loading, validation, and execution defaults |
| `model.py` | HTTP streaming, complete tool-call reconstruction, usage |
| `agent.py` | Sequential model/tool loop and review delegation |
| `tools.py` | JSON schemas for model requests and argument validation |
| `sandbox.py` | Repository copy, Docker lifecycle, tools, baseline diff |
| `store.py` | SQLite sessions, messages, runs, interruption reconciliation |
| `benchmark.py` | Fixed tasks, independent acceptance checks, JSON results |

## Execution

Assistant text streams immediately. Tool calls execute only after a complete
response with a valid finish reason. Arguments must match the tool schema.
Errors are returned as tool results, allowing the model to correct its request.
Truncated or broken model streams never execute partial tool calls. Model
requests are not retried automatically.

A turn allows 20 model calls by default, shared with children. Review children
have at most eight calls, cannot delegate, and can only read, search, or list.
They inspect the same workspace sequentially; there are no concurrent writers.
Parent and child transcripts are separate, linked SQLite sessions. Delegation
returns findings and usage; the parent decides what to do with them. Review
findings are model output, not verified defects.

The model adapter reserves `ECHO_MAX_TOKENS` output tokens per model call (16,384 by default).
`ECHO_CONTEXT_TOKENS` sets total context (262,144 by default) in both the client
and Compose. The transcript guard estimates three characters per input token,
after reserving output and 1,500 tokens for template/tool-schema overhead.
`ECHO_MAX_CONTEXT_CHARS` can impose a stricter cap. This is a heuristic, not a
tokenizer: code, Unicode, and tool schemas can still exceed the server's limit.
Start a focused new session when the guard is reached. Automatic summarization
and exact tokenizer accounting are deferred.

## Persistence and interruption

Messages and run status are committed independently as work progresses. SQLite
uses WAL mode. API keys are read from the environment, not stored in session
configuration. Transcripts may contain sensitive repository content.
Partial streamed text is displayed but saved only when the model response completes.

A filesystem lock prevents two CLI processes from opening the same workspace,
including a parent and its review child. A resumed session retains its original
model settings and child capabilities.

If a process stops after recording a tool call but before recording its result,
resume records an **unknown outcome** observation. It never replays that tool
automatically. The model must inspect current files before retrying. Ctrl-C
cancels inference or tool execution and removes the active tool container.

The original repository is not modified. A Git baseline outside the container's
writable mount supports diffs including added files. Exported patches are applied
manually. Changes made to the original checkout after session creation are not
automatically synchronized.
