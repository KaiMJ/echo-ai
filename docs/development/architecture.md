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
history. See [Everyday use](../guides/everyday-use.md) for commands and sandbox setup.

Sessions persist their mode, source repository, title, and last activity. Existing
sessions migrate as sandbox sessions; their source repository remains unknown.
`chat --resume` selects the last active parent session in the current repository.
Explicit IDs and unambiguous prefixes can select any session. `/sessions ID` asks
for confirmation, then ends the current idle chat, closes tools and releases its lock, and opens the selected
session with saved settings and restores user/assistant messages. Full traces stay
in SQLite. Switching is unavailable while a turn is running.

## Sandbox copy and image

The sandbox copy lives in Echo's session state directory on the host. It stays
there when a tool container exits, so a session can resume. The Docker image
supplies Python, packages, and tool programs; it does not contain the project
copy. `sandbox_tools.py` runs Echo's read, list, search, edit, and write tools
inside the container. Bash runs through the container's shell.

| Decision | Behavior | Reason |
| --- | --- | --- |
| Select project files | Copy Git-tracked files and nonignored untracked files. For a non-Git directory, use Git's ignore rules with a temporary index. | Keep generated files and ignored packages out of the copy. |
| Exclude sensitive paths | Skip symlinks and common credential paths such as `.env`, `.ssh`, and `.aws`. | Avoid copying common secrets or links outside the project. |
| Keep Git metadata private | Put `baseline.git` beside the copy, outside the container mount. Do not copy the project's `.git` into the container. | File history survives restarts without exposing it to Bash. |
| Keep the workspace mounted | Reuse the same copy across tool calls; start a new container each time. | Edited code is available to the next command without rebuilding the image. |
| Install packages in an image | The default image has Echo's locked runtime and test packages. Other projects can select an image with their own packages. | The container has no network access while tools run. |

Changing source files does not require an image rebuild. Changing image packages,
system tools, or the copied `sandbox_tools.py` does. The sandbox currently refuses
a project copy larger than 512 MiB.

## Private file history

Echo stores conversation branches in SQLite. It stores file versions as private
Git objects in the session's `baseline.git`. This Git directory is separate from
the project's repository, index, branches, and commits.

| Step | Sandbox | Local |
| --- | --- | --- |
| Session start | Copy eligible files and make one frozen baseline commit. | Make an empty private baseline; do not copy the whole project. |
| Agent `edit` or `write` | Checkpoint the touched file before and after the tool call. | Copy only the touched file into session state, then checkpoint it before and after. |
| Record change | Save the checkpoint IDs and patch with the tool call in SQLite. | Same. |
| Restore change | Read the saved file versions and merge against the current sandbox file. | Merge against the current host file. |

Checkpoints store file contents, including the whole contents of a touched file.
Git compresses and reuses objects, but editing a large file still costs more than
editing a small one. A local session does not need the project to be a Git repo.

Bash may change files, but those changes are not recorded for `/diff`, `/undo`,
`/redo`, or `/apply`. Sandbox Bash changes remain in the copy. In local mode,
Bash runs on the host, so its file changes remain in the original project.

Undo and redo use a three-way merge when the current file differs from its saved
version. Independent manual edits can survive. An overlapping edit stops the
operation and lists the conflicting paths; `force` replaces conflicting files.
File restores use a small on-disk journal so an interrupted restore can be
recovered when the session resumes. Starting a new turn after undo creates a new
conversation branch; the old branch stays in SQLite. Redo only follows the most
recent undo. Applying sandbox changes does not create a host undo record.

## Cost and limits

| Operation | Current cost |
| --- | --- |
| Start a sandbox | Copy eligible files and create a compressed Git baseline. Time and disk use grow with project size. |
| Start a local session | Create an empty private Git baseline. No full project copy. |
| Agent edit or write | Checkpoint one touched file before and after the tool call. Large files cost more. |
| `/diff`, `/undo`, `/redo` | Read recorded patches or affected files. They do not recopy the whole project. |
| Sandbox tool call | Start a container and scan workspace size before and after execution. This can dominate small tool calls. |

The 512 MiB workspace limit is checked around sandbox tool calls, not enforced
as a filesystem quota. Private checkpoints and completed session copies remain
on disk until cleaned up; there is no automatic pruning yet.
