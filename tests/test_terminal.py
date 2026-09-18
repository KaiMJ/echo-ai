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


@pytest.mark.parametrize(
    "tool,path,output,expected",
    [
        (
            "read",
            "README.md",
            "1: ## Welcome\n2: \n3: **Hello** world\n",
            ["Welcome", "Hello world"],
        ),
        ("list", ".", "__init__.py\n*literal*.md\nsrc/", ["__init__.py", "*literal*.md", "src/"]),
        (
            "bash",
            "",
            "# literal heading\nline one\nline two",
            ["# literal heading", "line one", "line two"],
        ),
        ("read", "app.py", "7: def main():\n8:     return 42\n", ["def main():", "    return 42"]),
    ],
)
def test_tool_details_preserve_content_structure(chat, tool, path, output, expected):
    chat.renderer.emit("tool_start", tool)
    chat.renderer.emit("tool_detail", {"name": tool, "args": {"path": path}})
    chat.renderer.emit("tool_end", {"output": output})
    chat.open_details(chat.entries[-1])
    rendered = lines(chat.details)
    for text in expected:
        assert any(text in line for line in rendered)
    if path.endswith(".md"):
        assert "**Hello**" not in "\n".join(rendered)
        assert "3: " not in "\n".join(rendered)


def test_copy_mode_releases_mouse_and_freezes_output_until_resumed(chat):
    chat.renderer.emit("text", "Original answer")
    chat.toggle_copy()
    before = lines(chat.transcript)
    assert not chat.app.mouse_support()
    assert chat.editor.read_only()
    chat.renderer.emit("text", "\n\nNew output")
    assert lines(chat.transcript) == before
    chat.toggle_copy()
    assert chat.app.mouse_support()
    assert not chat.editor.read_only()
    assert "New output" in "\n".join(lines(chat.transcript))


def test_copy_mode_keeps_open_tool_stable_during_completion(chat):
    chat.renderer.emit("tool_start", "bash")
    chat.renderer.emit("tool_output", "Still running")
    chat.open_details(chat.entries[-1])
    chat.toggle_copy()
    before = lines(chat.details)
    chat.renderer.emit("tool_end", {"output": "Finished"})
    assert lines(chat.details) == before
    chat.toggle_copy()
    assert "Finished" in "\n".join(lines(chat.details))


def test_spinner_animates_and_stops_on_completion(chat, monkeypatch):
    monkeypatch.setattr("echo_ai.terminal.time.monotonic", lambda: 1.0)
    chat.renderer.emit("tool_start", "list")
    before = lines(chat.transcript)[0]
    monkeypatch.setattr("echo_ai.terminal.time.monotonic", lambda: 1.2)
    assert lines(chat.transcript)[0] != before
    chat.renderer.emit("tool_end", {"output": "file.md"})
    assert lines(chat.transcript)[0].startswith("✓ ")
    assert any(style == "class:key" and text == "Alt+y" for style, text in chat.composer_hint())


def test_drag_highlights_and_copies_without_opening_details(chat):
    import base64

    chat.renderer.emit("text", "Alpha beta gamma")
    lines(chat.transcript)
    for kind, x in (
        (MouseEventType.MOUSE_DOWN, 0),
        (MouseEventType.MOUSE_MOVE, 10),
        (MouseEventType.MOUSE_UP, 10),
    ):
        chat.transcript.mouse_handler(
            MouseEvent(Point(x=x, y=1), kind, MouseButton.LEFT, frozenset())
        )
    assert chat.transcript.selected_text() == "Alpha beta"
    assert chat.selected is None
    content = chat.transcript.create_content(80, 30)
    assert any("class:selection" in part[0] for part in content.get_line(1))
    chat.renderer.emit("text", " streamed later")
    assert "streamed later" not in "\n".join(lines(chat.transcript))
    written = []
    chat.app.output.write_raw = written.append
    assert chat.copy_selection()
    assert written == ["\x1b]52;c;" + base64.b64encode(b"Alpha beta").decode() + "\x07"]
    chat.transcript.clear_selection()
    assert "streamed later" in "\n".join(lines(chat.transcript))


async def test_details_and_copy_commands_do_not_need_function_keys(chat):
    chat.renderer.emit("reasoning", "Inspect first")
    await chat.submit("/details")
    assert chat.selected is chat.entries[0]
    chat.close_details()
    await chat.submit("/copy")
    assert chat.copy_mode and not chat.app.mouse_support()


def test_reverse_multiline_drag_in_details_preserves_unicode(chat):
    entry = chat.add("notice", "Result", "Alpha 界\n\nBeta")
    chat.open_details(entry)
    rendered = lines(chat.details)
    first = next(i for i, line in enumerate(rendered) if "Alpha" in line)
    last = next(i for i, line in enumerate(rendered) if "Beta" in line)
    for kind, x, y in (
        (MouseEventType.MOUSE_DOWN, 4, last),
        (MouseEventType.MOUSE_MOVE, 0, first),
        (MouseEventType.MOUSE_UP, 0, first),
    ):
        chat.details.mouse_handler(MouseEvent(Point(x=x, y=y), kind, MouseButton.LEFT, frozenset()))
    assert chat.details.selected_text() == "Alpha 界\n\nBeta"
    assert chat.selected is entry


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
        # Drag over the answer, then copy without cancelling or closing the view.
        process.send("\x1b[<0;3;8M\x1b[<32;9;8M\x1b[<0;9;8m")
        process.sendcontrol("c")
        process.expect_exact("\x1b]52;c;QW5zd2Vy\x07")  # "Answer", base64 encoded.
        process.send("\x1b")
        # User Markdown is one paragraph (first/second), placing reasoning on row 5.
        process.send("\x1b[<0;5;5M\x1b[<0;5;5m")
        process.expect("Trace details")
        process.expect("Trace body only visible in popup")
        process.send("\x1bOR")  # F3 releases terminal mouse reporting for native selection.
        process.expect_exact("\x1b[?1000l")
        process.send("\x1bOR")
        process.expect_exact("\x1b[?1000h")
        process.send("\x1b")
        process.sendcontrol("l")
        process.expect("Answer ready")
        process.send("\x1bd")  # Alt+d works when terminal function keys are intercepted.
        process.expect("Trace details")
        process.send("\x1by")
        process.expect_exact("\x1b[?1000l")
        process.send("\x1by")
        process.expect_exact("\x1b[?1000h")
        process.send("\x1b")
        process.sendline("/exit")
        process.expect(pexpect.EOF)
        process.close()
        assert process.exitstatus == 0
    finally:
        process.close(force=True)
