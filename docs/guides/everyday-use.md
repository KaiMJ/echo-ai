# Everyday use

Run `echo-ai` from your project and describe the task. Local mode runs commands
on your machine and edits the original files. Use `/help` to see chat commands.

## Sessions

Use `/sessions` to browse previous conversations. Click a session or enter
`/sessions ID`, then confirm with Y; N or Esc cancels. Use `/new` for a fresh
conversation in the same project and execution mode. Previous sessions stay available.

From a terminal:

```bash
echo-ai resume                          # Resume the latest non-empty chat in this project
echo-ai resume <SESSION_ID>             # Resume a specific session
echo-ai sessions                        # List this project's sessions
echo-ai sessions --all                  # Include other projects and review sessions
echo-ai run "Explain this project"      # Run a non-interactive task
```

## Review and undo changes

| Chat command | What it does |
| --- | --- |
| `/diff` | Show recorded agent edits on the active conversation branch |
| `/undo` | Undo the latest completed turn and restore its recorded file changes |
| `/redo` | Replay the changes from the most recent undo |
| `/apply` | In sandbox mode, merge recorded edits into the original project |

These commands track agent `edit` and `write` tools. **Changes made through shell
commands are not tracked.** Local shell changes affect your project directly;
sandbox shell changes stay in the copy and are not included in `/apply`.

If a restore or apply conflicts with your own edits, Echo reports the paths.
Review them before using `/undo force`, `/redo force`, or `/apply force`, which
replace conflicting files. A new turn after undo starts a new conversation branch.
Applying sandbox changes does not create an undo record in the original project.

You can also inspect a session from the terminal:

```bash
echo-ai diff <SESSION_ID>
echo-ai diff <SESSION_ID> --output changes.txt
```

Diff output is recorded change history, not a single patch ready to apply.

## Sandbox mode

Sandbox mode runs tools in Docker against a persistent session copy of your
project. Docker must be running. Build the default image from the Echo checkout:

```bash
docker build -t echo-ai-sandbox:local .
```

Then start Echo from your project:

```bash
echo-ai --sandbox
```

Review changes with `/diff` and use `/apply` to merge recorded edits back.
The copy survives tool calls and session resumes. It includes Git-tracked and
nonignored untracked files, excluding symlinks and common credential paths such
as `.env`, `.ssh`, and `.aws`. Ordinary directories also work; Git is not required
for the project itself.

Tools have no network access. The default image includes Python, Bash, Git,
ripgrep, and Echo's runtime and test dependencies. For other dependencies, create
`Dockerfile.echo` in your project:

```dockerfile
FROM echo-ai-sandbox:local
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
```

Build and select the image:

```bash
docker build -f Dockerfile.echo -t my-project-sandbox:local .
echo-ai --sandbox --sandbox-image my-project-sandbox:local
```

You can also set `sandbox.sandbox_image` in YAML or `ECHO_SANDBOX_IMAGE`.
Custom images must retain `/opt/echo_sandbox.py`. Rebuild for dependency changes;
source edits do not require rebuilding.

Sandbox copies have a 512 MiB limit checked around tool calls, not a strict disk
quota. Session copies and checkpoints remain on disk without automatic pruning.

## Safety

Echo is intended for trusted, single-user development. Review commands and changes
before approving them, and keep backups.

- **Local commands have your account's permissions**, network access, and environment variables, including API keys.
- **Sandbox isolation reduces accidental damage**, but does not guarantee protection from malicious code or container escapes.
- **Reusable approvals allow later matching commands.** Prefer one-time approval when unsure. `--yolo` bypasses approval checks.
- **Repository text and tool output may be saved in transcripts and sent to your model provider**, including in sandbox mode. Ignore rules do not catch every secret.

For vulnerability reporting, see [Security in the README](../../README.md#security).
