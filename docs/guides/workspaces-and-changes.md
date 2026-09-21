# Workspaces and file changes

Echo has two execution modes. Both use private Git checkpoints for agent file
changes. The project can be a Git repository or an ordinary directory.

| Mode | Where tools run | Where files change |
| --- | --- | --- |
| Local (default) | On the host | In the original checkout or directory |
| Sandbox (`--sandbox`) | In a fresh Docker container for each tool call | In a session copy mounted at `/workspace` |

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

| Command | Behavior |
| --- | --- |
| `/diff` | Show recorded agent `edit` and `write` patches on the active conversation branch. It is a change history, not a single patch to apply. |
| `/undo` | Move to the previous conversation head and reverse the latest completed turn's recorded file changes. |
| `/redo` | Return to the just-undone branch and replay its recorded file changes. |
| `/apply` | In sandbox mode, merge the active branch's recorded agent changes into the original project. |

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
