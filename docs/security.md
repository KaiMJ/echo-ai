# Sandbox boundaries

Echo is intended for trusted single-user development with fallible generated
commands. Docker reduces accidental damage; it is not a guarantee against
hostile code or kernel vulnerabilities.

The model server and tool containers are separate. Only the host CLI controls
Docker. Tool containers receive a disposable copy of repository files, never
the original checkout, Docker socket, home directory, session database, or
baseline Git metadata.

Each tool call runs in a fresh container with:

- Host user's non-root UID/GID, all capabilities dropped, no privilege escalation.
- Read-only root filesystem and no network.
- 1 GiB memory, two CPUs, 128 processes, and a maximum 120-second execution time.
- 128 MiB temporary filesystem and 64 MiB maximum individual file size.
- At most 32 KiB captured output; extra output is drained and discarded.

Cancellation and timeout remove the entire tool container, including background
processes. The disposable copy persists for resume. Read/write/edit paths must
resolve inside the workspace. Bash can change anything in that copy.

**Disk limitation:** the 512 MiB workspace limit is checked before and after
execution; it is not a hard filesystem quota. A command can create many files
before the next check and consume host disk. Run on a dedicated quota-limited
filesystem or in a VM if hard aggregate disk isolation is required. Completed
session workspaces also accumulate until removed manually.

Docker shares the host kernel. A container escape remains possible. Docker
group membership grants host-level administrative capability to the CLI user.
The GPU inference service additionally needs NVIDIA devices and drivers.

Git ignore rules are not a complete secrets filter. Review what is tracked and
nonignored before opening a repository. Echo excludes symlinks and common
credential directories, but cannot identify every sensitive file.

There is no automatic patch application or network access from tools. Review
patches and run your project's checks before applying changes. Independent
benchmark tests help detect mistakes but do not prove arbitrary generated code
safe.
