"""Disposable Docker workspaces. Never mount the user's checkout into a container.

The bind-mounted copy survives restarts. File sizes, runtime, output, and container
resources are bounded, but aggregate workspace disk usage has no filesystem quota.
"""

from __future__ import annotations

import asyncio
import codecs
import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

from echo_ai.config import Config

IMAGE = "echo-ai-sandbox:local"


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


def _workspace_size(workspace: Path, max_bytes: int) -> int:
    size = 0
    for base, dirs, files in os.walk(workspace, followlinks=False):
        for name in files:
            size += (Path(base) / name).lstat().st_size
            if size > max_bytes:
                raise ValueError(
                    f"Workspace exceeds the {max_bytes:,}-byte limit; remove files before continuing"
                )
    return size


def _copy_repository(repo: Path, workspace: Path, max_bytes: int) -> None:
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
        if total > max_bytes:
            raise ValueError(f"Repository exceeds the {max_bytes:,}-byte workspace limit")
        target = workspace / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


class Sandbox:
    mode = "sandbox"

    def __init__(self, workspace: Path, config: Config | None = None):
        self.config = config or Config()
        self.workspace = workspace.resolve()
        self._container: str | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def create(cls, repo: Path, state_dir: Path, config: Config | None = None) -> Sandbox:
        config = config or Config()
        repo = repo.resolve()
        workspace = state_dir.resolve() / uuid.uuid4().hex / "workspace"
        workspace.mkdir(parents=True)
        _copy_repository(repo, workspace, config.max_workspace_bytes)
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
        return cls(workspace, config)

    @classmethod
    def resume(cls, workspace: Path, config: Config | None = None) -> Sandbox:
        workspace = workspace.resolve()
        if not workspace.is_dir() or not (workspace.parent / "baseline.git").is_dir():
            raise ValueError("Session workspace or baseline is missing")
        return cls(workspace, config)

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
            f"--pids-limit={self.config.sandbox_pids}",
            f"--memory={self.config.sandbox_memory_bytes}",
            f"--memory-swap={self.config.sandbox_memory_bytes}",
            f"--cpus={self.config.sandbox_cpus}",
            "--ulimit",
            f"fsize={self.config.sandbox_file_bytes}:{self.config.sandbox_file_bytes}",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--tmpfs",
            f"/tmp:rw,nosuid,nodev,size={self.config.sandbox_tmp_bytes},mode=1777",
            "--mount",
            f"type=bind,src={self.workspace},dst=/workspace",
            "--env",
            "HOME=/tmp",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "ECHO_TOOL_LIMITS="
            + json.dumps(
                {
                    name: getattr(self.config, name)
                    for name in (
                        "max_output_bytes",
                        "max_write_bytes",
                        "max_edit_bytes",
                        "read_max_lines",
                        "read_default_lines",
                        "search_max_matches",
                    )
                }
            ),
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

    async def execute_stream(self, tool: str, args: dict, on_output) -> dict:
        return await self.execute(tool, args, on_output=on_output)

    async def execute(self, tool: str, args: dict, *, on_output=None) -> dict:
        async with self._lock:
            try:
                self.check_size()
                await self._start()
                return await self._execute(tool, args, on_output=on_output)
            except asyncio.CancelledError:
                await asyncio.shield(self.close())
                raise
            except (ValueError, TypeError, KeyError, OSError, RuntimeError) as exc:
                await self.close()
                return {"error": str(exc)}

    def check_size(self):
        _workspace_size(self.workspace, self.config.max_workspace_bytes)

    async def _spawn(self, tool, args):
        command = (
            ["bash", "-lc", str(args["command"])]
            if tool == "bash"
            else ["python", "/opt/echo_sandbox.py", "--tool", tool]
        )
        return await asyncio.create_subprocess_exec(
            "docker",
            "exec",
            "-i",
            self._container,
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

    async def _execute(self, tool: str, args: dict, *, on_output=None) -> dict:
        timeout = min(
            max(float(args.get("timeout", self.config.tool_timeout)), 1),
            self.config.tool_max_timeout,
        )
        proc = await self._spawn(tool, args)
        try:
            proc.stdin.write(json.dumps(args).encode() if tool != "bash" else b"")
            await proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            proc.stdin.close()
        chunks = bytearray()
        truncated = False
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        async def collect() -> None:
            nonlocal truncated
            while block := await proc.stdout.read(8192):
                remaining = self.config.max_output_bytes - len(chunks)
                captured = block[: max(remaining, 0)]
                chunks.extend(captured)
                if on_output is not None and tool == "bash" and captured:
                    on_output(decoder.decode(captured))
                if len(block) > remaining:
                    truncated = True
            await proc.wait()
            if on_output is not None and tool == "bash":
                on_output(decoder.decode(b"", final=True))

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
        self.check_size()
        if tool != "bash" and not truncated:
            try:
                return json.loads(output)
            except json.JSONDecodeError:
                pass
        return {"output": output, "exit_code": proc.returncode, "truncated": truncated}

    def diff(self) -> str:
        # Include new files without changing the baseline. Configuration and hooks
        # live outside the writable container mount.
        self.check_size()
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
