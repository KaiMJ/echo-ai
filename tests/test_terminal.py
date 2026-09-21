from io import StringIO
from types import SimpleNamespace

import pytest
from prompt_toolkit.data_structures import Point
from prompt_toolkit.input import DummyInput
from prompt_toolkit.mouse_events import MouseButton, MouseEvent, MouseEventType
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from echo_ai.ui.renderer import Renderer
from echo_ai.ui.terminal import TerminalChat


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


async def test_permission_correction_keeps_draft_and_cursor(chat):
    import asyncio

    chat.editor.text = "unfinished draft"
    chat.editor.buffer.cursor_position = 4
    pending = asyncio.create_task(
        chat.ask_permission("bash", {"command": "pytest tests/unit"}, "pytest *")
    )
    await asyncio.sleep(0)
    assert chat.approval is not None
    assert chat.editor.text == "unfinished draft"
    assert chat.editor.buffer.cursor_position == 4
    chat.approval_correction = True
    chat.permission_input.text = "Run a smaller test"
    chat.resolve_approval("deny", chat.permission_input.text)
    assert await pending == ("deny", "Run a smaller test")
    assert chat.editor.text == "unfinished draft"
    assert chat.editor.buffer.cursor_position == 4


def test_mode_label_fits_above_composer(chat):
    for yolo in (False, True):
        chat.agent.permissions.yolo = yolo
        label = "".join(fragment[1] for fragment in chat.mode_label())
        assert len(label) <= 26
        assert ("Auto approve" if yolo else "Ask first") in label
        assert label.endswith("Shift+Tab")


def test_header_orb_only_appears_when_busy_and_freezes_for_copy(chat, monkeypatch):
    def text():
        return "".join(p[1] for p in chat.header())

    assert not any(0x2800 <= ord(c) <= 0x28ff for c in text())
    chat.task = SimpleNamespace(done=lambda: False)
    monkeypatch.setattr("echo_ai.ui.terminal.time.monotonic", lambda: 0.0)
    first = text()
    assert any(0x2800 <= ord(c) <= 0x28ff for c in first)
    monkeypatch.setattr("echo_ai.ui.terminal.time.monotonic", lambda: 0.5)
    assert text() != first
    chat.toggle_copy()
    frozen = text()
    monkeypatch.setattr("echo_ai.ui.terminal.time.monotonic", lambda: 1.0)
    assert text() == frozen
    chat.toggle_copy()
    chat.task = None
    assert not any(0x2800 <= ord(c) <= 0x28ff for c in text())


def test_layout_uses_full_terminal_width_with_small_gutters(chat):
    from prompt_toolkit.data_structures import Size

    chat.app.output.get_size = lambda: Size(rows=40, columns=180)
    assert 180 - 2 * chat.side_padding() == 176
    chat.app.output.get_size = lambda: Size(rows=20, columns=40)
    assert chat.side_padding() == 2
    assert "\n" not in "".join(p[1] for p in chat.header())


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
    monkeypatch.setattr("echo_ai.ui.terminal.time.monotonic", lambda: 1.0)
    chat.renderer.emit("tool_start", "list")
    before = lines(chat.transcript)[0]
    monkeypatch.setattr("echo_ai.ui.terminal.time.monotonic", lambda: 1.2)
    assert lines(chat.transcript)[0] != before
    chat.renderer.emit("tool_end", {"output": "file.md"})
    assert lines(chat.transcript)[0].startswith("✓ ")
    assert any(style == "class:key" and text == "Ctrl+J" for style, text in chat.composer_hint())


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


@pytest.mark.parametrize("command", ["/keys", "/details", "/copy", "/status details"])
async def test_removed_commands(chat, command):
    from echo_ai.ui.commands import COMMANDS

    assert command not in COMMANDS
    await chat.submit(command)
    assert chat.entries[-1].title == "Unknown command"
    assert chat.selected is None and not chat.copy_mode


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
        process.send("first\nsecond\r")
        process.expect("Answer ready")
        # Drag over the answer, then copy without cancelling or closing the view.
        process.send("\x1b[<0;3;13M\x1b[<32;9;13M\x1b[<0;9;13m")
        process.send("\x03")
        process.expect_exact("\x1b]52;c;QW5zd2Vy\x07")  # "Answer", base64 encoded.
        process.send("\x1b")
        # Start on a blank row, beyond its text, and drag back into the answer.
        process.send("\x1b[<0;23;14M\x1b[<32;3;13M\x1b[<0;3;13m")
        process.send("\x03")
        process.expect_exact("\x1b]52;c;QW5zd2VyIHJlYWR5Cg==\x07")
        process.send("\x1b")
        # The three-row header and user bubble place reasoning on row 10.
        process.send("\x1b[<0;5;10M\x1b[<0;5;10m")
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
        process.send("/exit\r")
        process.expect(pexpect.EOF)
        process.close()
        assert process.exitstatus == 0
    finally:
        process.close(force=True)


def test_selection_paints_empty_rows_without_copying_padding(chat):
    chat.add("text", "Echo", "Alpha")
    chat.add("text", "Echo", "Beta")
    rendered = lines(chat.transcript)
    first = next(i for i, line in enumerate(rendered) if "Alpha" in line)
    last = next(i for i, line in enumerate(rendered) if "Beta" in line)
    control = chat.transcript
    control.selection_rows = control.rows
    control.anchor, control.selection_end = (first, 0), (last, 4)
    content = control.create_content(80, 30)
    empty = next(i for i in range(first + 1, last) if not rendered[i].strip())
    assert "".join(part[1] for part in content.get_line(empty)) == " " * 80
    assert all("class:selection" in part[0] for part in content.get_line(empty))
    assert "\n\n" in control.selected_text()
    assert " " * 80 not in control.selected_text()


async def test_help_and_formatted_status(chat):
    await chat.submit("/help")
    assert "/sessions" in chat.selected.text and "Ctrl+Shift+C" in chat.selected.text
    chat.close_details()
    await chat.submit("/status")
    entry = chat.entries[-1]
    assert "Session: test" in entry.text and "Input counts" not in entry.text
    assert entry.renderable is not None
    rendered = entry.markdown_lines(80)
    assert entry.renderable.renderable.columns[0].style == f"bold {chat.theme.accent}"
    assert any("bold" in part[0] for line in rendered for part in line)
    assert "Session status" in "\n".join("".join(p[1] for p in line) for line in rendered)


@pytest.mark.parametrize("mode", ["local", "sandbox"])
async def test_diff_shows_file_summary_and_literal_patch(chat, mode):
    patch = (
        "diff --git a/code.py b/code.py\n"
        "--- a/code.py\n+++ b/code.py\n@@ -1 +1 @@\n-old\n+new\n"
        "diff --git a/new.txt b/new.txt\nnew file mode 100644\n"
        "--- /dev/null\n+++ b/new.txt\n@@ -0,0 +1 @@\n+created\n"
    )
    chat.agent.sandbox.mode = mode
    chat.agent.store = SimpleNamespace(active_tool_changes=lambda _: [{"patch": patch}])
    await chat.submit("/diff")
    entry = chat.selected
    assert entry not in chat.entries
    rendered = "\n".join("".join(part[1] for part in line) for line in entry.markdown_lines(80))
    assert "Agent edit and write changes" in rendered
    assert "Modified code.py" in rendered
    assert "Added    new.txt" in rendered
    assert "-old" in rendered and "+new" in rendered
    assert entry.text == patch


async def test_diff_shows_only_recorded_agent_changes(chat):
    patch = "diff --git a/a.txt b/a.txt\n--- a/a.txt\n+++ b/a.txt\n@@ -1 +1 @@\n-a\n+b\n"
    chat.agent.sandbox.mode = "local"
    chat.agent.store = SimpleNamespace(active_tool_changes=lambda _: [{"patch": patch}])
    chat.agent.sandbox.diff = lambda: pytest.fail("agent diff should not use live workspace diff")
    await chat.submit("/diff")
    assert chat.selected.text == patch
    assert "Agent edit and write changes" in "\n".join(lines(chat.details))


async def test_session_list_switch_and_restored_conversation(chat, tmp_path, monkeypatch):
    from echo_ai.runtime.store import Store

    store = Store(tmp_path / "state.db")
    current = store.create(tmp_path, {}, repo=tmp_path)
    target = store.create(tmp_path, {}, repo=tmp_path)
    store.add(current, {"role": "user", "content": "Earlier question"})
    store.add(current, {"role": "assistant", "content": "Earlier answer"})
    store.add(target, {"role": "user", "content": "Other task"})
    chat.agent.store = store
    chat.agent.session_id = current
    await chat.submit("/sessions")
    assert "Other task" in chat.entries[-1].text
    await chat.submit("/sessions missing")
    assert chat.entries[-1].title == "Error"
    results = []
    monkeypatch.setattr(chat.app, "exit", lambda **kwargs: results.append(kwargs["result"]))
    await chat.submit("/sessions " + target[:8])
    assert results == []
    await chat.submit("Y")
    assert results == [target]

    async def run_async():
        assert any(entry.text == "Earlier question" for entry in chat.entries)
        assert any(entry.text == "Earlier answer" for entry in chat.entries)
        return target

    monkeypatch.setattr(chat.app, "run_async", run_async)
    assert await chat.run() == target
    store.close()


def test_command_completion_only_at_prompt_start():
    from prompt_toolkit.completion import CompleteEvent
    from prompt_toolkit.document import Document

    from echo_ai.ui.commands import COMMANDS, CommandCompleter

    def suggestions(text):
        return [c.text for c in CommandCompleter().get_completions(Document(text), CompleteEvent())]

    assert suggestions("/") == list(COMMANDS)
    assert suggestions("/he") == ["/help"]
    for text in ("please /", " /", "hello\n/", "/help\n/"):
        assert suggestions(text) == []


def test_exact_command_keeps_description_visible(chat):
    chat.editor.text = "/undo"
    hint = "".join(part[1] for part in chat.composer_hint())
    assert "/undo" in hint
    assert "Undo the latest completed turn" in hint


@pytest.mark.asyncio
async def test_history_write_does_not_block_enter(chat, monkeypatch):
    import asyncio
    import threading

    entered = threading.Event()
    release = threading.Event()

    def slow_store(self, string):
        entered.set()
        release.wait(timeout=2)

    monkeypatch.setattr("prompt_toolkit.history.FileHistory.store_string", slow_store)
    history = chat.editor.buffer.history
    history.append_string("hello")
    await asyncio.wait_for(asyncio.to_thread(entered.wait), timeout=1)
    assert history.get_strings()[-1] == "hello"
    release.set()
    await history.flush()


def test_transcript_rows_reused_when_only_editor_changes(chat):
    chat.add("text", "Echo", "Answer")
    lines(chat.transcript)
    cached = chat.transcript.row_cache
    chat.editor.text = "draft"
    lines(chat.transcript)
    assert chat.transcript.row_cache is cached
    chat.entries[0].text = "Updated"
    lines(chat.transcript)
    assert chat.transcript.row_cache is not cached


@pytest.mark.parametrize("kind", ["user", "text", "tool", "reasoning"])
def test_click_selects_full_block_and_alt_copy_uses_source(chat, kind):
    entry = chat.add(
        kind, "Block", "**Full body**", done=True, detail="arguments" if kind == "tool" else ""
    )
    lines(chat.transcript)
    for event in (MouseEventType.MOUSE_DOWN, MouseEventType.MOUSE_UP):
        chat.transcript.mouse_handler(MouseEvent(Point(0, 0), event, MouseButton.LEFT, frozenset()))
    control = chat.details if chat.selected else chat.transcript
    assert control.selected_text() == chat.entry_text(entry)
    assert any("class:block-selection" in p[0] for p in control.create_content(80, 30).get_line(0))
    copied = []
    chat.copy_text = copied.append
    chat.copy_output()
    assert copied == [chat.entry_text(entry)]


def test_copy_latest_and_all_include_full_collapsed_traces(chat):
    chat.add("user", "You", "Question")
    chat.add("reasoning", "Reasoning", "Thought", done=True)
    chat.add("tool", "Tool", "Result", detail="Arguments", done=True)
    chat.add("text", "Echo", "Answer")
    copied = []
    chat.copy_text = copied.append
    chat.copy_output()
    assert copied == ["Answer"]
    chat.copy_output(all_entries=True)
    assert copied[-1] == 'user:\n"Question"\n\necho:\n"Answer"'


def test_drag_starting_on_empty_row(chat):
    chat.add("text", "Echo", "Alpha\n\nBeta")
    rendered = lines(chat.transcript)
    empty = next(i for i, line in enumerate(rendered[1:], 1) if not line.strip())
    # Blank rows must contain actual cells before selection, for terminal mouse hit testing.
    assert rendered[empty] == " " * 80
    for kind, x, y in (
        (MouseEventType.MOUSE_DOWN, 20, empty),
        (MouseEventType.MOUSE_MOVE, 4, empty + 1),
        (MouseEventType.MOUSE_UP, 4, empty + 1),
    ):
        chat.transcript.mouse_handler(MouseEvent(Point(x, y), kind, MouseButton.LEFT, frozenset()))
    assert chat.transcript.selected_text() == "\nBeta"


async def test_typing_and_newline_while_streaming_and_slash_menu(tmp_path):
    import asyncio

    from prompt_toolkit.input import create_pipe_input

    started, finish = asyncio.Event(), asyncio.Event()
    received = []

    async def run(prompt):
        received.append(prompt)
        instance.on_event("text", "Streaming answer")
        started.set()
        await finish.wait()
        return {"status": "completed"}

    async def until(predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    with create_pipe_input() as pipe:
        agent = SimpleNamespace(session_id="test", run=run)
        renderer = Renderer(Console(file=StringIO()))
        instance = TerminalChat(agent, tmp_path, renderer, input=pipe, output=DummyOutput())
        copied = []
        instance.copy_text = copied.append
        task = asyncio.create_task(instance.run())
        try:
            await until(lambda: instance.app.is_running)
            pipe.send_text("first\r")
            await started.wait()
            pipe.send_text("draft\nsecond")
            await until(lambda: instance.editor.text == "draft\nsecond")
            pipe.send_text("\r")
            await asyncio.sleep(0.05)
            assert received == ["first"]
            assert instance.editor.text == "draft\nsecond"
            pipe.send_text("\x03")
            await until(lambda: copied == ["Streaming answer"])
            assert instance.editor.text == "draft\nsecond" and instance.busy
            pipe.send_text("\x1b")
            await asyncio.sleep(0.7)
            assert instance.editor.text == "draft\nsecond" and instance.busy
            pipe.send_text("\x1b[99;6u")
            await until(lambda: len(copied) == 2)
            assert copied[-1] == 'user:\n"first"\n\necho:\n"Streaming answer"'
            finish.set()
            await until(lambda: not instance.busy)
            pipe.send_text("\r")
            await until(lambda: received == ["first", "draft\nsecond"])
            await until(lambda: not instance.busy)
            pipe.send_text("/")
            await until(lambda: instance.editor.buffer.complete_state is not None)
            assert "/help" in [c.text for c in instance.editor.buffer.complete_state.completions]
            instance.editor.text = ""
            pipe.send_text("hello /")
            await until(lambda: instance.editor.text == "hello /")
            await asyncio.sleep(0.05)
            assert instance.editor.buffer.complete_state is None
        finally:
            instance.app.exit()
            await task


@pytest.mark.parametrize("kind", ["user", "text", "reasoning", "tool"])
def test_second_click_clears_block_selection(chat, kind):
    entry = chat.add(kind, "Block", "Content", done=True)
    if entry.expandable:
        chat.open_details(entry)
    control = chat.details if chat.selected else chat.transcript
    lines(control)
    for _ in range(2):
        for event in (MouseEventType.MOUSE_DOWN, MouseEventType.MOUSE_UP):
            control.mouse_handler(MouseEvent(Point(0, 0), event, MouseButton.LEFT, frozenset()))
        if _ == 0:
            assert control.selected_text() == "Content"
        else:
            assert control.selected_text() == ""
            assert control.selection_rows is None
            assert not any(
                "class:block-selection" in p[0] for p in control.create_content(80, 30).get_line(0)
            )


@pytest.mark.parametrize("width", [20, 80, 120])
def test_user_right_and_model_left_without_backgrounds(chat, width):
    chat.add("user", "You", "Question")
    chat.add("reasoning", "Reasoning", "Thinking", done=True)
    chat.add("tool", "Tool", "Result", done=True)
    chat.add("text", "Echo", "Answer")
    content = chat.transcript.create_content(width, 30)
    for i, (_, entry) in enumerate(chat.transcript.rows):
        line = content.get_line(i)
        text = "".join(p[1] for p in line)
        assert not any("class:turn-" in p[0] or "bg:" in p[0] for p in line)
        if entry is not None:
            if entry.kind == "user":
                assert text.lstrip().startswith(("╭", "│", "╰"))
                assert len(text) == width
            else:
                assert not text.startswith(" ")


def test_right_aligned_selection_omits_layout_padding_preserves_indentation(chat):
    entry = chat.add("user", "You", "def example():\n    return '界'")
    rendered = lines(chat.transcript)
    assert "def example():" in rendered[2] and "return" in rendered[3]
    control = chat.transcript
    control.selection_rows = control.rows
    control.anchor = (2, 0)
    control.selection_end = (3, 80)
    assert control.selected_text() == entry.text
    control.clear_selection()
    control.select_entry(entry)
    assert control.selected_text() == entry.text
    assert not any(
        "class:block-selection" in style and "class:alignment-gutter" in style
        for style, _ in control.create_content(80, 30).get_line(1)
    )


def test_wrapped_user_block_copy_keeps_original_text(chat):
    text = "A long message with **literal Markdown** and Unicode 界 " * 3
    entry = chat.add("user", "You", text)
    assert len(lines(chat.transcript, width=40)) > 4
    chat.transcript.select_entry(entry)
    copied = []
    chat.copy_text = copied.append
    chat.copy_output()
    assert copied == [text]


async def test_sessions_are_formatted_with_current_marker(chat, tmp_path):
    from echo_ai.runtime.store import Store

    store = Store(tmp_path / "sessions.db")
    try:
        current = store.create(tmp_path, {}, repo=tmp_path)
        other = store.create(tmp_path, {}, repo=tmp_path)
        store.add(other, {"role": "user", "content": "[red]literal title[/red]"})
        chat.agent.store, chat.agent.session_id = store, current
        await chat.submit("/sessions")
        assert all(entry.renderable is not None for entry in chat.entries)
        rendered = "\n".join(
            "".join(p[1] for p in line)
            for entry in chat.entries for line in entry.markdown_lines(80)
        )
        assert "current" in rendered and current in rendered and other in rendered
        assert "[red]literal title[/red]" in rendered
        assert "/sessions ID to switch" in rendered
        assert [entry.session_target["id"] for entry in chat.entries] == [current, other]
    finally:
        store.close()


async def test_new_command_exits_to_fresh_session(chat, monkeypatch):
    from echo_ai.ui.commands import NEW_SESSION

    results = []
    monkeypatch.setattr(chat.app, "exit", lambda **kwargs: results.append(kwargs["result"]))
    chat.add("text", "Echo", "Previous answer")
    await chat.submit("/new")
    assert results == [NEW_SESSION]
    assert chat.entries[-1].text == "Previous answer"


async def test_click_session_confirms_and_cancel_restores_draft(chat, monkeypatch):
    target = {"id": "other-session", "title": "Earlier work"}
    chat.add("notice", "Sessions", "Earlier work", session_target=target)
    chat.editor.text = "unfinished draft"
    chat.editor.buffer.cursor_position = 4
    results = []
    monkeypatch.setattr(chat.app, "exit", lambda **kwargs: results.append(kwargs["result"]))

    def click():
        lines(chat.transcript)
        chat.transcript.mouse_handler(MouseEvent(
            position=Point(x=3, y=0), event_type=MouseEventType.MOUSE_UP,
            button=MouseButton.LEFT, modifiers=frozenset(),
        ))

    click()
    assert chat.pending_session == target and results == []
    assert chat.app.layout.has_focus(chat.session_choices)
    confirmation = "".join(part[1] for part in chat.session_confirmation_text())
    assert "Earlier work" in confirmation and "Resume" in confirmation and "Cancel" in confirmation
    for _ in range(3):
        click()
    assert len(chat.entries) == 1
    assert chat.editor.text == "unfinished draft"
    assert chat.editor.buffer.cursor_position == 4
    await chat.submit("maybe")
    assert chat.pending_session == target and results == []
    assert len(chat.entries) == 1
    chat.app.key_bindings.get_bindings_for_keys(("N",))[-1].handler(None)
    assert chat.pending_session is None and results == []
    assert chat.editor.text == "unfinished draft"
    assert chat.editor.buffer.cursor_position == 4
    assert chat.app.layout.has_focus(chat.editor)
    click()
    chat.app.key_bindings.get_bindings_for_keys(("Y",))[-1].handler(None)
    assert results == [target["id"]]


def test_session_popup_escape_cancels_without_transcript_messages(chat):
    from prompt_toolkit.keys import Keys

    chat.confirm_session({"id": "other-session", "title": "Earlier work"})
    chat.confirm_session({"id": "another-session", "title": "Another task"})
    assert chat.pending_session["id"] == "other-session"
    chat.app.key_bindings.get_bindings_for_keys((Keys.Escape,))[-1].handler(None)
    assert chat.pending_session is None
    assert chat.entries == []
    assert chat.app.layout.has_focus(chat.editor)


@pytest.mark.parametrize("command", ["/exit", "/new"])
async def test_exit_commands_do_not_write_input_history(tmp_path, command):
    import asyncio

    from prompt_toolkit.input import create_pipe_input

    with create_pipe_input() as pipe:
        instance = TerminalChat(
            SimpleNamespace(session_id="test", permissions=SimpleNamespace(ask=None, yolo=False)), tmp_path,
            Renderer(Console(file=StringIO())), input=pipe, output=DummyOutput(),
        )
        pipe.send_text(command + "\r")
        await asyncio.wait_for(instance.run(), timeout=2)
        assert not (tmp_path / "input-history").exists()


def test_block_selection_fills_blank_lines_and_preserves_colors(chat):
    from prompt_toolkit.styles import Style

    entry = chat.add("text", "Echo", "Alpha\n\nBeta")
    rendered = lines(chat.transcript)
    blank = next(i for i, row in enumerate(rendered[1:-1], 1) if not row.strip())
    chat.transcript.select_entry(entry)
    line = chat.transcript.create_content(80, 30).get_line(blank)
    assert "".join(p[1] for p in line) == " " * 80
    assert all("class:block-selection" in p[0] for p in line)
    style = Style.from_dict(chat.theme.styles())
    selected = style.get_attrs_for_style_str("fg:#ff0000 bold class:block-selection")
    assert selected.color == "ff0000" and selected.bold
    assert selected.bgcolor == chat.theme.selection_background.lstrip("#")


def test_user_bubble_border_is_not_copied(chat):
    entry = chat.add("user", "You", "Hello\n\n    world")
    rendered = lines(chat.transcript)
    assert "╭" in rendered[0] and "╰" in rendered[-2]
    control = chat.transcript
    control.selection_rows = control.rows
    control.anchor = (2, 0)
    control.selection_end = (len(rendered) - 2, 80)
    assert control.selected_text() == entry.text
    control.select_entry(entry)
    assert control.selected_text() == entry.text


def test_escape_dismisses_ui_without_clearing_draft_or_selection(chat):
    from prompt_toolkit.completion import Completion
    from prompt_toolkit.keys import Keys

    escape = chat.app.key_bindings.get_bindings_for_keys((Keys.Escape,))[-1].handler
    chat.editor.text = "/he"
    chat.editor.buffer._set_completions([Completion("/help", start_position=-3)])
    escape(None)
    assert chat.editor.buffer.complete_state is None
    assert chat.editor.text == "/he"

    entry = chat.add("text", "Echo", "Answer")
    chat.editor.text = "keep draft"
    chat.transcript.select_entry(entry)
    escape(None)
    assert chat.transcript.selected_text() == "Answer" and chat.editor.text == "keep draft"

    chat.open_details(entry)
    chat.details.select_entry(entry)
    escape(None)
    assert chat.selected is None and chat.editor.text == "keep draft"

    chat.toggle_copy()
    escape(None)
    assert not chat.copy_mode and chat.editor.text == "keep draft"
    escape(None)
    assert chat.editor.text == "keep draft"


def test_clear_input_button_and_copy_preserve_independent_state(chat):
    from prompt_toolkit.keys import Keys

    entry = chat.add("text", "Echo", "Answer")
    chat.transcript.select_entry(entry)
    chat.editor.text = "Draft\nsecond line"
    copied = []
    chat.copy_text = copied.append
    copy = chat.app.key_bindings.get_bindings_for_keys((Keys.ControlC,))[-1]
    assert copy.eager()
    copy.handler(None)
    copy.handler(None)
    assert copied == ["Answer", "Answer"]
    assert chat.editor.text == "Draft\nsecond line"
    assert chat.transcript.selected_text() == "Answer"
    hint = chat.composer_hint()
    button = next(part for part in hint if "Clear input" in part[1])
    button[2](MouseEvent(Point(0, 0), MouseEventType.MOUSE_UP, MouseButton.LEFT, frozenset()))
    assert chat.editor.text == ""
    assert chat.transcript.selected_text() == "Answer"


def test_copy_from_editor_selection_does_not_cut_or_deselect(chat):
    from prompt_toolkit.keys import Keys

    chat.editor.text = "keep this draft"
    chat.editor.buffer.cursor_position = 0
    chat.editor.buffer.start_selection()
    chat.editor.buffer.cursor_position = 4
    copied = []
    chat.copy_text = copied.append
    chat.app.key_bindings.get_bindings_for_keys((Keys.ControlC,))[-1].handler(None)
    assert copied == ["keep"]
    assert chat.editor.text == "keep this draft"
    assert chat.editor.buffer.selection_state is not None


@pytest.mark.parametrize(
    "sequence", ["\x1b[117;6u", "\x1b[85;6u", "\x1b[27;6;117~", "\x1b[27;6;85~"]
)
async def test_shift_ctrl_u_clears_draft_but_ctrl_u_keeps_line_editing(tmp_path, sequence):
    import asyncio

    from prompt_toolkit.input import create_pipe_input

    async def until(predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    with create_pipe_input() as pipe:
        instance = TerminalChat(
            SimpleNamespace(session_id="test"),
            tmp_path,
            Renderer(Console(file=StringIO())),
            input=pipe,
            output=DummyOutput(),
        )
        entry = instance.add("text", "Echo", "Keep selected answer")
        task = asyncio.create_task(instance.run())
        try:
            await until(lambda: instance.app.is_running)
            instance.transcript.select_entry(entry)
            pipe.send_text("first\nsecond")
            await until(lambda: instance.editor.text == "first\nsecond")
            pipe.send_text("\x15")  # Ctrl+U: delete only to the start of the current line.
            await until(lambda: instance.editor.text == "first\n")
            pipe.send_text("second")
            await until(lambda: instance.editor.text == "first\nsecond")
            assert "Ctrl+Shift+U" in "".join(p[1] for p in instance.composer_hint())
            pipe.send_text(sequence)
            await until(lambda: instance.editor.text == "")
            assert instance.transcript.selected_text() == "Keep selected answer"
        finally:
            instance.app.exit()
            await task


async def test_up_recalls_latest_submitted_input(tmp_path):
    import asyncio

    from prompt_toolkit.input import create_pipe_input

    submitted = []

    async def run(prompt):
        submitted.append(prompt)
        return {"status": "completed"}

    async def until(predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    with create_pipe_input() as pipe:
        instance = TerminalChat(
            SimpleNamespace(session_id="test", run=run),
            tmp_path,
            Renderer(Console(file=StringIO())),
            input=pipe,
            output=DummyOutput(),
        )
        task = asyncio.create_task(instance.run())
        try:
            await until(lambda: instance.app.is_running)
            pipe.send_text("first\r")
            await until(lambda: submitted == ["first"] and not instance.busy)
            pipe.send_text("second\r")
            await until(lambda: submitted == ["first", "second"] and not instance.busy)
            pipe.send_text("\x1b[A")
            await until(lambda: instance.editor.text == "second")
            pipe.send_text("\x1b[A")
            await until(lambda: instance.editor.text == "first")
            pipe.send_text("\x1b[B")
            await until(lambda: instance.editor.text == "second")
        finally:
            instance.app.exit()
            await task


def test_help_uses_actions_without_terminal_protocol_jargon(chat):
    text = chat.help_entry().text
    assert all(f"**{action}:**" in text for action in ("Select", "Copy", "Paste", "Clear input"))
    assert "Ctrl+Shift+U" in text and "Clear input" in text
    assert "CSI-u" not in text and "modifyOtherKeys" not in text
    assert "Cmd+V" in text


@pytest.mark.parametrize(
    "kind,body,tool,path",
    [
        ("text", "Plain text with `inline code`", "", ""),
        ("text", "```text\nplain_identifier\n```", "", ""),
        ("tool", "1: plain_identifier", "read", "file.py"),
    ],
)
def test_text_and_code_do_not_force_white_on_terminal_background(chat, kind, body, tool, path):
    entry = chat.add(kind, "Echo", body, tool=tool, path=path, done=True)
    fragments = [p for line in entry.markdown_lines(80) for p in line]
    assert not any(
        "ansiwhite" in p[0] or "ansibrightwhite" in p[0] or "bg:" in p[0] for p in fragments
    )


async def test_drag_input_border_resizes_without_editing_or_selecting(tmp_path):
    import asyncio

    from prompt_toolkit.input import create_pipe_input

    async def until(predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    with create_pipe_input() as pipe:
        instance = TerminalChat(
            SimpleNamespace(session_id="resize"),
            tmp_path,
            Renderer(Console(file=StringIO())),
            input=pipe,
            output=DummyOutput(),
        )
        instance.add("text", "Echo", "Answer stays selectable")
        task = asyncio.create_task(instance.run())
        try:
            await until(lambda: instance.editor.window.render_info is not None)
            pipe.send_text("draft\nsecond line")
            await until(lambda: instance.editor.text == "draft\nsecond line")
            top = instance.editor.window.render_info._y_offset  # one-based border row
            pipe.send_text(f"\x1b[<0;10;{top}M\x1b[<32;10;{top - 5}M\x1b[<0;10;{top - 5}m")
            await until(lambda: instance.editor.window.render_info.window_height == 8)
            assert instance.resize_drag is None
            assert instance.editor.text == "draft\nsecond line"
            assert instance.transcript.selected_text() == ""
            top = instance.editor.window.render_info._y_offset
            bottom = instance.app.output.get_size().rows
            pipe.send_text(f"\x1b[<0;10;{top}M\x1b[<32;10;{bottom}M\x1b[<0;10;{bottom}m")
            await until(lambda: instance.editor.window.render_info.window_height == 1)
            assert instance.editor.text == "draft\nsecond line"
        finally:
            instance.app.exit()
            await task


@pytest.mark.parametrize("width", [40, 80, 120])
def test_composer_hints_have_clean_separators_and_clickable_clear(chat, width):
    from prompt_toolkit.data_structures import Size

    chat.app.output.get_size = lambda: Size(rows=30, columns=width)
    chat.editor.text = "draft"
    fragments = chat.composer_hint()
    text = "".join(p[1] for p in fragments)
    assert " · " in text and "Clear input" in text
    assert "[" not in text and "]" not in text and "_" not in text
    assert not any("underline" in p[0] for p in fragments)
    assert len(text) <= width
    assert any(len(p) == 3 and "Clear input" in p[1] for p in fragments)
