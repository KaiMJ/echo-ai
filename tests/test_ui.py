import asyncio

from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from echo_ai.cli import make_prompt, safe_text


async def test_multiline_and_next_prompt(tmp_path):
    with create_pipe_input() as pipe:
        prompt = make_prompt(tmp_path, input=pipe, output=DummyOutput())
        task = asyncio.create_task(prompt.prompt_async("echo › "))
        pipe.send_text("first\x1b\rsecond\r")
        assert await asyncio.wait_for(task, 2) == "first\nsecond"
        task = asyncio.create_task(prompt.prompt_async("echo › "))
        pipe.send_text("/exit\r")
        assert await asyncio.wait_for(task, 2) == "/exit"


def test_output_is_not_terminal_commands():
    assert "\x1b" not in safe_text("\x1b]52;c;secret\x07")


def test_c1_controls_are_removed():
    assert safe_text("a\x00\x1b\x7f\x85\x9bb\n\t") == "ab\n\t"


def test_workspace_lock_rejects_second_opener_and_releases(tmp_path):
    import pytest

    from echo_ai.cli import workspace_lock

    workspace = tmp_path / "workspace"
    with (
        workspace_lock(workspace),
        pytest.raises(RuntimeError, match="another Echo process"),
        workspace_lock(workspace),
    ):
        pass
    with workspace_lock(workspace):
        pass


async def test_resume_preserves_child_permissions_and_lock_during_close(tmp_path, monkeypatch):
    import argparse
    from dataclasses import asdict

    import pytest

    from echo_ai import cli, sandbox
    from echo_ai.config import Config
    from echo_ai.store import Store

    store = Store(tmp_path / "sessions.sqlite3")
    workspace = tmp_path / "workspace"
    parent = store.create(workspace, asdict(Config()))
    child = store.create(workspace, asdict(Config()), parent)
    store.close()
    seen = []

    class FakeSandbox:
        @classmethod
        def resume(cls, path):
            instance = cls()
            instance.workspace = path
            return instance

        async def close(self):
            with (
                pytest.raises(RuntimeError, match="another Echo process"),
                cli.workspace_lock(self.workspace),
            ):
                pass
            seen.append("closed")

    async def fake_chat(agent, root):
        assert agent.child
        assert {t["function"]["name"] for t in agent.tools} == {"read", "search", "list"}
        seen.append("chat")

    monkeypatch.setattr(cli, "state_dir", lambda: tmp_path)
    monkeypatch.setattr(sandbox, "Sandbox", FakeSandbox)
    monkeypatch.setattr(cli, "chat", fake_chat)
    assert await cli.execute(argparse.Namespace(command="resume", session=child)) == 0
    assert seen == ["chat", "closed"]
    with cli.workspace_lock(workspace):
        pass


def test_terminal_stream_cancel_and_next_prompt(tmp_path):
    """Exercise rendering and Ctrl-C in a real PTY without needing a model server."""
    import sys

    import pexpect

    program = """
import asyncio, sys
from pathlib import Path
from echo_ai.cli import chat, render
class Sandbox:
    workspace = Path("/disposable/workspace")
class Agent:
    sandbox = Sandbox()
    session_id = "test-session"
    async def run(self, prompt):
        render("text", "streamed ")
        await asyncio.sleep(.05)
        render("text", "response")
        if prompt == "wait":
            await asyncio.sleep(60)
        return {"status": "completed"}
asyncio.run(chat(Agent(), Path(sys.argv[1])))
"""
    process = pexpect.spawn(
        sys.executable, ["-c", program, str(tmp_path)], encoding="utf-8", timeout=10
    )
    try:
        process.expect("echo ›")
        process.sendline("hello")
        process.expect("streamed response")
        process.expect("echo ›")
        process.sendline("wait")
        process.expect("streamed response")
        process.sendcontrol("c")
        process.expect("Cancelled")
        process.expect("echo ›")
        process.sendline("/status")
        process.expect("Session: test-session")
        process.expect("echo ›")
        process.sendline("/exit")
        process.expect(pexpect.EOF)
        process.close()
        assert process.exitstatus == 0
    finally:
        process.close(force=True)
