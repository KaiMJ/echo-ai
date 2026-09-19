"""Host tools with a separate, session-owned Git baseline."""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

from echo_ai.workspace.sandbox import Sandbox, _copy_repository, _git, _git_env


class LocalWorkspace(Sandbox):
    mode = "local"

    def __init__(self, workspace, state_path, config=None):
        super().__init__(workspace, config)
        self.state_path = Path(state_path)
        self._process = None

    @classmethod
    def create(cls, repo, state_dir, config=None):
        state_dir = Path(state_dir).resolve()
        workspace = state_dir / uuid.uuid4().hex / "workspace"
        workspace.mkdir(parents=True)
        _git(workspace, "init", "--quiet")
        _git(workspace, "-c", "user.name=Echo", "-c", "user.email=echo@localhost",
             "commit", "--quiet", "--allow-empty", "-m", "Empty local baseline")
        (workspace.parent / "partial-baseline").write_text("Agent file edits only\n")
        return cls(repo, workspace.parent, config)

    @classmethod
    def resume(cls, workspace, state_path, config=None):
        if not state_path or not Path(workspace).is_dir():
            raise ValueError("Session checkout or baseline is missing")
        Sandbox.resume(Path(state_path) / "workspace", config)
        return cls(workspace, state_path, config)

    def check_size(self):
        # The checkout can contain large ignored dependencies. Snapshot size is
        # bounded separately by _copy_repository when creating/exporting diffs.
        pass

    async def _start(self):
        pass

    async def _spawn(self, tool, args):
        env = os.environ.copy()
        env["ECHO_WORKSPACE_ROOT"] = str(self.workspace)
        env["ECHO_TOOL_LIMITS"] = json.dumps(
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
        )
        command = (
            ["bash", "-c", str(args["command"])]
            if tool == "bash"
            else [sys.executable, str(Path(__file__).with_name("sandbox_tools.py")), "--tool", tool]
        )
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                *command,
                cwd=self.workspace,
                env=env,
                start_new_session=True,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        )
        try:
            self._process = await asyncio.shield(spawning)
        except asyncio.CancelledError:
            self._process = await spawning
            raise
        return self._process

    async def close(self):
        if self._process is not None:
            process, self._process = self._process, None
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await asyncio.gather(process.stdout.read(), process.wait())

    def diff(self):
        if (self.state_path / "partial-baseline").exists():
            raise ValueError(
                "/diff all is unavailable for this local session: no full session-start "
                "snapshot was taken. Use /diff for recorded agent edits."
            )
        snapshot = self._refresh_snapshot()
        return Sandbox(snapshot, self.config).diff()

    def checkpoint(self, path):
        snapshot = self.state_path / "workspace"
        relative = self._recordable_path(path)
        if relative is None:
            raise ValueError(f"Cannot checkpoint path: {path}")
        source, target = self.workspace / relative, snapshot / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            _git(snapshot, "add", "-f", "--", str(relative))
        else:
            target.unlink(missing_ok=True)
            _git(snapshot, "rm", "--cached", "--ignore-unmatch", "--", str(relative))
        tree = _git(snapshot, "write-tree").strip()
        commit = _git(
            snapshot, "-c", "user.name=Echo", "-c", "user.email=echo@localhost",
            "commit-tree", tree, "-m", "Echo local file checkpoint",
        ).strip()
        _git(snapshot, "update-ref", f"refs/echo/checkpoints/{uuid.uuid4().hex}", commit)
        return commit


    def _refresh_snapshot(self):
        snapshot = self.state_path / "workspace"
        shutil.rmtree(snapshot)
        snapshot.mkdir()
        _copy_repository(self.workspace, snapshot, self.config.max_workspace_bytes)
        return snapshot

    def checkpoint_diff(self, before, after):
        return Sandbox(self.state_path / "workspace", self.config).checkpoint_diff(before, after)

    def checkout_id(self):
        def git(*args):
            result = subprocess.run(
                ["git", "-C", str(self.workspace), *args],
                env=_git_env(), capture_output=True, text=True, check=False,
            )
            return result.stdout.strip() if result.returncode == 0 else ""

        return "|".join((git("rev-parse", "--show-toplevel"),
                         git("symbolic-ref", "-q", "HEAD"),
                         git("rev-parse", "--verify", "HEAD")))
