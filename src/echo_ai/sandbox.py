"""Disposable Docker workspaces. Never mount the user's checkout into a container.

The bind-mounted copy survives restarts. File sizes, runtime, output, and container
resources are bounded, but aggregate workspace disk usage has no filesystem quota.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from .sandbox_tools import MAX_OUTPUT

IMAGE = "echo-ai-sandbox:local"
MAX_WORKSPACE = 512 * 1024 * 1024


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null")
    return env


def _git(workspace: Path, *args: str) -> str:
    return subprocess.check_output(
        [
            "git",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "core.fsmonitor=false",
            f"--git-dir={workspace.parent / 'baseline.git'}",
            f"--work-tree={workspace}",
            *args,
        ],
        env=_git_env(),
        text=True,
        stderr=subprocess.PIPE,
    )


def _workspace_size(workspace: Path) -> int:
    size = 0
    for base, dirs, files in os.walk(workspace, followlinks=False):
        for name in files:
            size += (Path(base) / name).lstat().st_size
            if size > MAX_WORKSPACE:
                raise ValueError(
                    "Workspace exceeds the 512 MiB limit; remove files before continuing"
                )
    return size


def _copy_repository(repo: Path, workspace: Path) -> None:
    # Git's ignore rules exclude virtualenvs, local utilities, and secrets such
    # as ignored .env files. Non-Git directories deliberately require setup.
    raw = subprocess.check_output(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(repo),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
        ],
        env=_git_env(),
    )
    total = 0
    for name in set(os.fsdecode(raw).split("\0")) - {""}:
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Invalid repository path")
        if any(part in {".git", ".ssh", ".aws", ".gnupg", ".env"} for part in relative.parts):
            continue
        source = repo / relative
        if source.is_symlink() or not source.is_file():
            continue
        if not source.resolve().is_relative_to(repo):
            continue
        total += source.stat().st_size
        if total > MAX_WORKSPACE:
            raise ValueError("Repository exceeds the 512 MiB workspace limit")
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


class Sandbox:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self._container: str | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def create(cls, repo: Path, state_dir: Path) -> Sandbox:
        repo = repo.resolve()
        workspace = state_dir.resolve() / uuid.uuid4().hex / "workspace"
        workspace.mkdir(parents=True)
        _copy_repository(repo, workspace)
        _git(workspace, "init", "--quiet")
        _git(workspace, "add", "--all")
        _git(
            workspace,
            "-c",
            "user.name=Echo",
            "-c",
            "user.email=echo@localhost",
            "commit",
            "--quiet",
            "--allow-empty",
            "-m",
            "Workspace baseline",
        )
        return cls(workspace)

    @classmethod
    def resume(cls, workspace: Path) -> Sandbox:
        workspace = workspace.resolve()
        if not workspace.is_dir() or not (workspace.parent / "baseline.git").is_dir():
            raise ValueError("Session workspace or baseline is missing")
        return cls(workspace)

    async def _docker(self, *args: str) -> tuple[int, str]:
        proc = await asyncio.create_subprocess_exec(
            "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        communication = asyncio.create_task(proc.communicate())
        try:
            output, _ = await asyncio.shield(communication)
        except asyncio.CancelledError:
            # Finish Docker's create/remove request before cleanup; otherwise a
            # late create can race the remove request and leave a container.
            await communication
            raise
        return proc.returncode or 0, output.decode(errors="replace")

    async def _start(self) -> None:
        if os.getuid() == 0:
            raise RuntimeError("Run Echo as a non-root user; sandbox tools must not run as root")
        if self._container:
            return
        name = "echo-" + uuid.uuid4().hex
        self._container = name
        code, output = await self._docker(
            "run",
            "--pull=never",
            "--detach",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--memory=1g",
            "--memory-swap=1g",
            "--cpus=2",
            "--ulimit",
            "fsize=67108864:67108864",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=128m,mode=1777",
            "--mount",
            f"type=bind,src={self.workspace},dst=/workspace",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            IMAGE,
        )
        if code:
            await self._docker("rm", "--force", name)
            raise RuntimeError(f"Cannot start sandbox: {output.strip()}")
        self._container = name

    async def close(self) -> None:
        if self._container:
            name, self._container = self._container, None
            await self._docker("rm", "--force", name)

    async def execute(self, tool: str, args: dict) -> dict:
        async with self._lock:
            try:
                _workspace_size(self.workspace)
                await self._start()
                return await self._execute(tool, args)
            except asyncio.CancelledError:
                await asyncio.shield(self.close())
                raise
            except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
                await self.close()
                return {"error": str(exc)}

    async def _execute(self, tool: str, args: dict) -> dict:
        timeout = min(max(float(args.get("timeout", 60)), 1), 120)
        command = (
            ["bash", "-lc", str(args["command"])]
            if tool == "bash"
            else ["python", "/opt/echo_sandbox.py", "--tool", tool]
        )
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "-i",
            self._container,
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        proc.stdin.write(json.dumps(args).encode() if tool != "bash" else b"")
        await proc.stdin.drain()
        proc.stdin.close()
        chunks = bytearray()
        truncated = False

        async def collect() -> None:
            nonlocal truncated
            while block := await proc.stdout.read(8192):
                remaining = MAX_OUTPUT - len(chunks)
                chunks.extend(block[: max(remaining, 0)])
                if len(block) > remaining:
                    truncated = True
            await proc.wait()

        try:
            await asyncio.wait_for(collect(), timeout)
        except (TimeoutError, asyncio.CancelledError) as exc:
            await asyncio.shield(self.close())
            if proc.returncode is None:
                proc.kill()
            await proc.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return {
                "error": f"Tool timed out after {timeout:g}s",
                "output": chunks.decode(errors="replace"),
            }
        # Kill background processes too; persistent state lives in the copy.
        await self.close()
        output = chunks.decode(errors="replace")
        if truncated:
            output += "\n[output truncated]"
        _workspace_size(self.workspace)
        if tool != "bash" and not truncated:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                pass
        return {"output": output, "exit_code": proc.returncode, "truncated": truncated}

    def diff(self) -> str:
        # Include new files without changing the baseline. Configuration and hooks
        # live outside the writable container mount.
        _workspace_size(self.workspace)
        _git(self.workspace, "add", "--all")
        return _git(
            self.workspace,
            "diff",
            "--cached",
            "--binary",
            "--no-ext-diff",
            "--no-textconv",
            "HEAD",
            "--",
        )
