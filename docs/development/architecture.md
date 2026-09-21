# Architecture

```text
prompt_toolkit / batch command
              |
         agent loop ---- vLLM HTTP stream
          |     |
       SQLite   tool dispatcher ---- host tools / optional Docker container
          |
      parent / child sessions
```

The CLI owns one active turn. There is no daemon, message broker, or framework.
The loop is independent of terminal rendering, so tests can supply a fake model,
sandbox, and output callback.

| Module | Responsibility |
| --- | --- |
| `cli.py` | Commands, prompt, streaming display, cancellation, workspace lock |
| `config/` | .env loading, validation, and execution defaults |
| `model.py` | HTTP streaming, complete tool-call reconstruction, usage |
| `agent.py` | Sequential model/tool loop and review delegation |
| `tools.py` | JSON schemas for model requests and argument validation |
| `sandbox.py` | Repository copy, Docker lifecycle, private checkpoints |
| `store.py` | SQLite sessions, messages, runs, interruption reconciliation |
| `local.py` | Host tools, process cleanup, touched-file checkpoints |
| `runtime/revisions.py`, `workspace/revisions.py` | Conversation movement and three-way file restores |
| `commands.py` | Shared chat help, status, and session formatting |

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
cancels inference or tool execution. Cleanup kills the local tool process group
or removes the active Docker container.

Local mode edits the original checkout and runs shell tools on the host. It
checkpoints files touched by agent edit and write tools in a private Git directory.
Sandbox mode copies eligible project files and runs tools against that copy.
`/diff` shows recorded agent edits on the active conversation branch. `/undo` and
`/redo` move the branch and merge its file changes. Sandbox `/apply` merges those
recorded edits into the original project. Bash file changes are outside this
history. See [Workspaces and file changes](../guides/workspaces-and-changes.md) for the
design decisions and costs.

Sessions persist their mode, source repository, title, and last activity. Existing
sessions migrate as sandbox sessions; their source repository remains unknown.
`chat --resume` selects the last active parent session in the current repository.
Explicit IDs and unambiguous prefixes can select any session. `/sessions ID` asks
for confirmation, then ends the current idle chat, closes tools and releases its lock, and opens the selected
session with saved settings and restores user/assistant messages. Full traces stay
in SQLite. Switching is unavailable while a turn is running.
