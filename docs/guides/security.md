# Security essentials

Echo is designed for trusted, single-user development. Review commands and changes before approving them.

- **Local mode runs on your machine.** Shell commands have your account's permissions, network access, and environment variables, including API keys. There is no OS isolation.
- **Sandbox mode works on a copy.** Use `--sandbox` to run tools in Docker without network access. It reduces accidental damage, but is not a guarantee against malicious code or container escapes. Disk usage is not strictly capped.
- **Approvals matter.** A reusable approval permits later matching commands; it does not make them safe. Prefer one-time approval when unsure. `--yolo` bypasses approval checks.
- **Protect your data.** Repository text and tool output can be saved in transcripts and sent to your configured model provider, even in sandbox mode. Git ignore rules do not catch every secret.
- **Review changes and keep backups.** Use `/diff` before `/apply`. `/undo`, `/diff`, and `/apply` cover recorded agent edits and writes, not changes made through shell commands.

See [Workspaces and file changes](workspaces-and-changes.md) for execution details and [Security in the README](../../README.md#security) for vulnerability reporting.
