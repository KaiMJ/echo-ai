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
        process.expect("response")
        process.expect("/help")
        process.sendline("wait")
        process.expect("response")
        process.sendcontrol("c")
        process.expect("Cancelled")
        process.sendline("/status")
        process.sendcontrol("l")  # Repaint for a complete line, rather than cursor diffs.
        process.expect("Session: test-session")
        process.sendline("/exit")
        process.expect(pexpect.EOF)
        process.close()
        assert process.exitstatus == 0
    finally:
        process.close(force=True)


def test_renderer_plain_stream_and_child_visibility():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    output = StringIO()
    ui = Renderer(Console(file=output, width=100))
    ui.start()
    ui.emit("text", "Main response")
    ui.emit("child", "review-123")
    ui.emit("child_task", "Inspect sandbox cleanup")
    ui.emit(
        "child_model_start",
        {
            "context_chars": 300,
            "context_tokens": 1000,
            "remaining": 8,
            "max_steps": 10,
        },
    )
    ui.emit("child_tool_start", "read")
    ui.emit("child_tool_detail", {"name": "read", "args": {"path": "sandbox.py"}})
    ui.emit("child_tool_end", {"error": "cannot read file"})
    ui.emit("child_text", "Review findings")
    ui.emit("child_run_end", {"status": "failed", "metrics": {}})
    ui.stop("completed")
    text = output.getvalue()
    assert "\x1b" not in text
    assert "review-123" in text and "Inspect sandbox cleanup" in text
    assert "sandbox.py" in text and "cannot read file" in text
    assert "Review findings" in text and "Failed" in text
    assert text.count("Main response") == 1
    assert ui.live is None


def test_context_uses_latest_prompt_not_cumulative_usage():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    ui = Renderer(Console(file=StringIO()))
    request = {"context_chars": 600, "context_tokens": 1000, "remaining": 8, "max_steps": 10}
    ui.emit("model_start", request)
    assert ui.main.context == 200 and ui.main.estimated
    for prompt in (220, 350):
        ui.emit(
            "model_end",
            {
                "usage": {"prompt_tokens": prompt, "completion_tokens": 10},
                "metrics": {"prompt_tokens": 570},
            },
        )
    assert ui.main.context == 350
    assert not ui.main.estimated
    assert ui.output_tokens == 20
    assert "35%" in ui.main.context_text()
    ui.emit("child", "child")
    ui.emit("child_model_start", request)
    ui.emit("child_model_end", {"usage": {"prompt_tokens": 99}, "metrics": {}})
    assert ui.main.context == 350
    assert ui.child.context == 99


def test_dashboard_handles_resize_and_untrusted_text():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    output = StringIO()
    console = Console(file=output, width=120, height=35)
    ui = Renderer(console)
    ui.emit("child", "review")
    ui.emit("child_task", "[red]literal[/red]\x1b[2J")
    ui.emit("child_text", "Streaming review")
    for width, height in ((120, 35), (70, 30), (40, 12)):
        console.size = (width, height)
        console.print(ui.dashboard())
    text = output.getvalue()
    assert "\x1b" not in text
    assert "[red]literal[/red]" in text
    assert "Read-only subagent" in text
    assert text.count("Streaming review") >= 3


def test_context_display_follows_review_and_returns_to_parent():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    output = StringIO()
    console = Console(file=output, force_terminal=False)
    ui = Renderer(console)
    request = {"context_chars": 600, "context_tokens": 1000, "remaining": 8, "max_steps": 10}
    ui.emit("model_start", request)
    ui.emit("model_end", {"usage": {"prompt_tokens": 350}})
    ui.emit("child", "review-context")
    ui.emit("child_model_start", request)
    assert "Review Context [~200 / 1,000] 20%" in ui.toolbar()
    ui.emit("child_model_end", {"usage": {"prompt_tokens": 99}})
    assert "Review Context [99 / 1,000] 10%" in ui.toolbar()
    for width, height in ((120, 35), (70, 22), (40, 12)):
        console.size = (width, height)
        output.seek(0)
        output.truncate()
        console.print(ui.dashboard())
        displayed = output.getvalue()
        assert "Review Context" in displayed
        assert "99 / 1,000" in displayed
        assert "350 / 1,000" not in displayed

    ui.emit("child_run_end", {"status": "completed"})
    ui.emit("tool_end", {"findings": "Review complete"})
    assert "Echo Context [350 / 1,000] 35%" in ui.toolbar()
    assert "350 / 1,000" in ui.active_context_text()
    assert ui.child.context == 99
    ui.emit("model_start", request)
    assert "Echo Context [~200 / 1,000] 20%" in ui.toolbar()


def test_stream_preview_keeps_latest_wrapped_lines_visible():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    for width, height in ((120, 35), (70, 22), (40, 12), (24, 8)):
        output = StringIO()
        console = Console(file=output, width=width, height=height, force_terminal=False)
        ui = Renderer(console)
        ui.main.text = "```python\n" + "long wrapped response " * 500 + "\nLATEST LINE"
        console.print(ui.dashboard())
        displayed = output.getvalue()
        assert "LATEST LINE" in displayed
        assert len(displayed.splitlines()) <= height


def test_plain_reasoning_is_separated_from_answer():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    output = StringIO()
    ui = Renderer(Console(file=output, force_terminal=False))
    ui.emit("reasoning", "Thinking.")
    ui.emit("text", "")
    ui.emit("text", "Answer")
    ui.emit("text", " continues.")
    ui.emit("model_end", {"usage": {}})
    assert output.getvalue() == "Thinking.\n\nAnswer continues.\n"


def test_streaming_footer_stays_at_bottom_with_actual_context_counts():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    for width in (120, 70, 40, 24):
        output = StringIO()
        console = Console(file=output, width=width, height=22, force_terminal=False)
        ui = Renderer(console)
        ui.model = "gemma-4-26B-A4B-it-AWQ-4bit"
        ui.main.context = 2620
        ui.main.capacity = 262144
        ui.main.estimated = False
        for response in ("", "Streaming", "Long response\n" * 100):
            ui.main.text = response
            output.seek(0)
            output.truncate()
            console.print(ui.dashboard())
            lines = output.getvalue().splitlines()
            assert len(lines) == 21
            assert "[2,620 / 262,144]" in lines[-1]
            assert "[2,620 / 262,144]" in ui.toolbar()
            if width == 120:
                assert ui.model in lines[-1]
                assert "Ctrl-C cancel" in lines[-1]
                assert "/help" in ui.toolbar()


def test_tool_preview_limits_lines_and_preserves_errors():
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui import Renderer

    output = StringIO()
    ui = Renderer(Console(file=output, force_terminal=False))
    ui.emit("tool_end", {"output": "line\n" * 100, "exit_code": 2})
    displayed = output.getvalue()
    assert "Exit 2" in displayed
    assert "Full result saved in session" in displayed
    assert len(displayed.splitlines()) <= 7


def test_live_review_resize_cancel_and_prompt_recovery(tmp_path):
    import sys

    import pexpect

    program = """
import asyncio, sys
from pathlib import Path
from echo_ai.cli import chat, render, renderer
from echo_ai.config import Config
class Sandbox:
    workspace = Path('/disposable/workspace')
class Model:
    config = Config()
class Agent:
    sandbox = Sandbox()
    model = Model()
    session_id = 'dashboard-test'
    async def run(self, prompt):
        render('child', 'review-123')
        render('child_task', 'Inspect cleanup')
        render('child_model_start', {
            'context_chars': 900, 'context_tokens': 16384, 'remaining': 18, 'max_steps': 20,
        })
        render('child_tool_start', 'read')
        render('child_tool_detail', {'name': 'read', 'args': {'path': 'sandbox.py'}})
        try:
            await asyncio.sleep(60)
        finally:
            render('child_run_end', {'status': 'cancelled', 'metrics': {}})
agent = Agent()
renderer.configure(agent)
asyncio.run(chat(agent, Path(sys.argv[1])))
"""
    process = pexpect.spawn(
        sys.executable,
        ["-c", program, str(tmp_path)],
        encoding="utf-8",
        timeout=10,
        dimensions=(30, 120),
    )
    try:
        process.expect("echo ›")
        process.sendline("review")
        process.expect("Read-only subagent")
        process.expect("Inspect cleanup")
        process.expect("sandbox.py")
        process.setwinsize(22, 70)
        process.expect("Context")
        process.sendcontrol("c")
        process.expect("Cancelled")
        process.sendline("/exit")
        process.expect(pexpect.EOF)
        process.close()
        assert process.exitstatus == 0
    finally:
        process.close(force=True)
