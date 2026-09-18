from io import StringIO
from types import SimpleNamespace

import pytest
from prompt_toolkit.data_structures import Point
from prompt_toolkit.input import DummyInput
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from echo_ai.terminal import TerminalChat
from echo_ai.ui import Renderer


@pytest.fixture
def chat(tmp_path):
    renderer = Renderer(Console(file=StringIO(), force_terminal=False))
    agent = SimpleNamespace(session_id="test", sandbox=SimpleNamespace(workspace=tmp_path))
    instance = TerminalChat(agent, tmp_path, renderer, input=DummyInput(), output=DummyOutput())
    renderer.event_handler = instance.on_event
    return instance


def lines(control, width=80, height=30):
    content = control.create_content(width, height)
    return ["".join(part[1] for part in content.get_line(i)) for i in range(content.line_count)]


def test_answer_stays_in_place_at_completion(chat):
    chat.renderer.emit("reasoning", "**Plan**\n\nInspect the code.")
    chat.renderer.emit("text", "## Result\n\n" + "Answer text.\n" * 12)
    before = lines(chat.transcript)
    answer = chat.entries[-1]
    chat.renderer.emit("model_end", {"usage": {"prompt_tokens": 123}})
    chat.renderer.emit("run_end", {"status": "completed"})
    assert chat.entries[-1] is answer
    assert lines(chat.transcript) == before
    assert chat.entries[0].done
    assert "Inspect the code." not in "\n".join(before)


def test_click_completed_reasoning_opens_markdown_popup(chat):
    chat.renderer.emit("reasoning", "**Plan**\n\n- Inspect\n- Test")
    chat.renderer.emit("model_end", {"usage": {}})
    lines(chat.transcript)
    chat.transcript.mouse_handler(
        MouseEvent(
            position=Point(x=3, y=0),
            event_type=MouseEventType.MOUSE_UP,
            button=MouseButton.LEFT,
            modifiers=frozenset(),
        )
    )
    assert chat.selected is chat.entries[0]
    rendered = "\n".join(lines(chat.details))
    assert "Inspect" in rendered and "Test" in rendered
    assert "**Plan**" not in rendered
    chat.close_details()
    assert chat.selected is None


def test_tool_draft_stream_result_and_popup_keep_same_entry(chat):
    ui = chat.renderer
    ui.emit("tool_call_delta", {"index": 0, "name": "bash", "arguments": '{"com'})
    entry = chat.entries[0]
    assert "com" in "\n".join(lines(chat.transcript))
    ui.emit("model_end", {"usage": {}})
    ui.emit("tool_start", "bash")
    ui.emit("tool_detail", {"name": "bash", "args": {"command": "echo result"}})
    ui.emit("tool_output", "## Running\n\nFirst line")
    assert "First line" in "\n".join(lines(chat.transcript))
    ui.emit("tool_end", {"output": "## Finished\n\nFull result", "exit_code": 2})
    assert chat.entries == [entry]
    assert entry.done and "exit 2" in entry.status
    assert "Full result" not in "\n".join(lines(chat.transcript))
    chat.open_details(entry)
    assert "Full result" in "\n".join(lines(chat.details))
    assert "echo result" in "\n".join(lines(chat.details))


def test_child_tool_does_not_overwrite_parent_tool(chat):
    ui = chat.renderer
    ui.emit("tool_start", "delegate")
    parent = chat.entries[-1]
    ui.emit("child", "review")
    ui.emit("child_tool_start", "read")
    child = chat.entries[-1]
    ui.emit("child_tool_end", {"output": "child output"})
    ui.emit("tool_end", {"findings": "parent output"})
    assert parent.text == "parent output"
    assert child.text == "child output"


def test_scrolling_back_does_not_follow_new_output(chat):
    chat.renderer.emit("text", "\n\n".join(f"Line {n}" for n in range(50)))
    lines(chat.transcript, height=10)
    chat.transcript.scroll(-10)
    before = lines(chat.transcript, height=10)
    chat.renderer.emit("text", "\n\nNewest line")
    assert lines(chat.transcript, height=10) == before
    chat.transcript.follow = True
    assert "Newest line" in "\n".join(lines(chat.transcript, height=10))


def test_pty_mouse_popup_multiline_and_exit(tmp_path):
    import sys

    import pexpect

    program = """
import asyncio, sys
from pathlib import Path
from echo_ai.cli import chat, render
class Agent:
    session_id = 'popup-test'
    async def run(self, prompt):
        assert prompt == 'first\\nsecond', repr(prompt)
        render('reasoning', '**Plan**\\n\\nTrace body only visible in popup')
        render('text', 'Answer ready')
        render('model_end', {'usage': {}})
        render('run_end', {'status': 'completed'})
        return {'status': 'completed'}
asyncio.run(chat(Agent(), Path(sys.argv[1])))
"""
    process = pexpect.spawn(
        sys.executable,
        ["-c", program, str(tmp_path)],
        encoding="utf8",
        timeout=5,
        dimensions=(30, 100),
    )
    try:
        process.expect("echo ›")
        process.send("first\x1b\rsecond\r")
        process.expect("Answer ready")
        # User Markdown is one paragraph (first/second), placing reasoning on row 5.
        process.send("\x1b[<0;5;5M\x1b[<0;5;5m")
        process.expect("Trace details")
        process.expect("Trace body only visible in popup")
        process.send("\x1b")
        process.sendcontrol("l")
        process.expect("Answer ready")
        process.send("\x1bOQ")  # F2 reopens the last trace.
        process.expect("Trace details")
        process.send("\x1b")
        process.sendline("/exit")
        process.expect(pexpect.EOF)
        process.close()
        assert process.exitstatus == 0
    finally:
        process.close(force=True)
