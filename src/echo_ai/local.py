"""Host tools with a separate, session-owned Git baseline."""

import asyncio
import json
import os
import shutil
import signal
import sys
from pathlib import Path

from .sandbox import Sandbox, _copy_repository


class LocalWorkspace(Sandbox):
    mode = "local"

    def __init__(self, workspace, state_path, config=None):
        super().__init__(workspace, config)
        self.state_path = Path(state_path)
        self._process = None

    @classmethod
    def create(cls, repo, state_dir, config=None):
        baseline = Sandbox.create(repo, state_dir, config)
        return cls(repo, baseline.workspace.parent, baseline.config)

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
        snapshot = self.state_path / "workspace"
        shutil.rmtree(snapshot)
        snapshot.mkdir()
        _copy_repository(self.workspace, snapshot, self.config.max_workspace_bytes)
        return Sandbox(snapshot, self.config).diff()
