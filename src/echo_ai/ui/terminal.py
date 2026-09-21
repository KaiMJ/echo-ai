"""Persistent interactive transcript; Rich formats Markdown, prompt_toolkit owns the screen."""

import asyncio
import base64
import json
import re
import shlex
import time
from dataclasses import dataclass, field, replace
from io import StringIO
from pathlib import PurePath

import httpx
from prompt_toolkit import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.history import FileHistory
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import ConditionalKeyBindings, KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import (
    ConditionalContainer,
    DynamicContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.utils import explode_text_fragments
from prompt_toolkit.mouse_events import MouseButton, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from echo_ai.config import load_theme
from echo_ai.runtime.permissions import Permissions
from echo_ai.runtime.revisions import apply_sandbox, move_turn
from echo_ai.ui.appearance import CODE_THEME, MARKDOWN_THEME, orb_frame
from echo_ai.ui.commands import (
    COMMANDS,
    NEW_SESSION,
    CommandCompleter,
    help_text,
    session_rows_panel,
    status_panel,
    status_text,
)
from echo_ai.ui.model_settings import ModelSettings
from echo_ai.ui.renderer import safe_text

# prompt_toolkit has no Ctrl+Shift+letter key token. Reserve F24 internally for
# the CSI-u / modifyOtherKeys sequences terminals can forward for Ctrl+Shift+C.
for sequence in ("\x1b[99;6u", "\x1b[67;6u", "\x1b[27;6;99~", "\x1b[27;6;67~"):
    ANSI_SEQUENCES[sequence] = Keys.F24
# Keep Ctrl+U distinct: only explicitly shifted sequences clear the entire draft.
for sequence in ("\x1b[117;6u", "\x1b[85;6u", "\x1b[27;6;117~", "\x1b[27;6;85~"):
    ANSI_SEQUENCES[sequence] = Keys.F23


def fit_text(value, width):
    """Clip chrome by terminal cells, including wide Unicode characters."""
    text = Text(safe_text(value).replace("\n", " ").replace("\t", " "))
    text.truncate(max(0, width), overflow="ellipsis")
    return text.plain


def key_highlights(value, width):
    text = fit_text(value, width)
    keys = r"(Ctrl\+Shift\+[CU]|Ctrl-End|Ctrl\+[cCdDJ]|/help|Alt\+[dy]|PgUp/PgDn|Enter|Esc|F[23])"
    return [
        ("class:key" if re.fullmatch(keys, part) else "class:muted", part)
        for part in re.split(keys, text)
        if part
    ]


def diff_renderable(patch):
    """Show a compact file list above the unmodified session patch."""
    heading = Text("Agent edit and write changes", style="bold")
    files = []
    current = None
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                files.append(current)
            paths = shlex.split(line.removeprefix("diff --git "))
            current = ["Modified", paths[-1].removeprefix("b/")]
        elif current is not None:
            if line.startswith("new file mode "):
                current[0] = "Added"
            elif line.startswith("deleted file mode "):
                current[0] = "Deleted"
            elif line.startswith("rename to "):
                current[:] = ["Renamed", line.removeprefix("rename to ")]
    if current is not None:
        files.append(current)
    summary = Text("\n".join(f"{status:8} {path}" for status, path in files))
    return Group(
        heading,
        summary,
        Text(""),
        Syntax(patch, "diff", word_wrap=True, theme=CODE_THEME, background_color="default"),
    )


@dataclass
class Entry:
    kind: str
    title: str
    text: str = ""
    detail: str = ""
    done: bool = False
    status: str = ""
    tool: str = ""
    path: str = ""
    renderable: object = None
    session_target: dict | None = None
    cache_key: tuple | None = None
    cache: list = field(default_factory=list)

    @property
    def expandable(self):
        return self.kind in {"reasoning", "tool"}

    def markdown_lines(self, width):
        source = self.detail + self.text
        key = (width, source, self.tool, self.path)
        if key != self.cache_key:
            output = StringIO()
            console = Console(
                file=output,
                width=max(1, width),
                force_terminal=True,
                color_system="truecolor",
                highlight=False,
                theme=MARKDOWN_THEME,
            )
            if self.renderable is not None:
                console.print(self.renderable)
            elif self.kind == "user":
                # User input is literal: preserve newlines and code indentation.
                console.print(Text(source))
            elif self.kind == "tool":
                if self.detail:
                    console.print(Text("Arguments", style="dim"))
                    console.print(
                        Syntax(
                            self.detail,
                            "json",
                            word_wrap=True,
                            theme=CODE_THEME,
                            background_color="default",
                        )
                    )
                    console.print()
                console.print(Text("Output", style="dim"))
                body = self.text or ("No output." if self.done else "Waiting for output…")
                if self.tool == "read" and not self.status.startswith("Failed"):
                    # Read results prefix each source line with its original line number.
                    body = re.sub(r"(?m)^\d+: ", "", body)
                    if PurePath(self.path).suffix.lower() in {".md", ".markdown", ".mdown"}:
                        console.print(Markdown(body, code_theme=CODE_THEME))
                    else:
                        lexer = Syntax.guess_lexer(self.path, body)
                        console.print(
                            Syntax(
                                body,
                                lexer,
                                word_wrap=True,
                                theme=CODE_THEME,
                                background_color="default",
                            )
                        )
                elif self.tool == "delegate":
                    console.print(Markdown(body, code_theme=CODE_THEME))
                else:
                    # Shell output, filenames, and search matches are literal text.
                    console.print(Text(body))
            else:
                console.print(Markdown(source or "Waiting for output…", code_theme=CODE_THEME))
            self.cache = list(split_lines(to_formatted_text(ANSI(output.getvalue()))))
            # Rich appends a newline; don't accumulate empty rows between entries.
            while self.cache and not any(fragment[1] for fragment in self.cache[-1]):
                self.cache.pop()
            self.cache_key = key
        return self.cache


class TranscriptControl(UIControl):
    def __init__(self, chat, *, popup=False):
        self.chat = chat
        self.popup = popup
        self.offset = 0
        self.follow = True
        self.visible = []
        self.total = self.height = self.width = 0
        self.rows = []
        self.selection_rows = None
        self.anchor = self.selection_end = None
        self.dragging = False
        self.selection_follow = True
        self.block_text = None
        self.block_entry = None
        self.toggle_on_release = False
        self.row_cache_key = None
        self.row_cache = []

    def clear_selection(self):
        if self.selection_rows is not None:
            self.follow = self.selection_follow
        self.selection_rows = None
        self.anchor = self.selection_end = None
        self.dragging = False
        self.block_text = None
        self.block_entry = None

    def selected_text(self):
        if self.block_text is not None:
            return self.block_text
        if self.anchor is None or self.anchor == self.selection_end:
            return ""
        start, end = sorted((self.anchor, self.selection_end))
        lines = []
        for index in range(start[0], end[0] + 1):
            fragments = self.selection_rows[index][0]
            if any("class:bubble-edge" in p[0] for p in fragments):
                continue
            text = "".join(part[1] for part in fragments)
            left = start[1] if index == start[0] else 0
            right = end[1] if index == end[0] else len(text)
            # Mouse positions include the right-alignment gutter, copied text does not.
            selected = "".join(
                char
                for x, (style, char, *_) in enumerate(explode_text_fragments(fragments))
                if left <= x < right and "class:layout-padding" not in style
            )
            # Rich pads rendered rows to the viewport; omit that padding when copying.
            lines.append(selected.rstrip() if index < end[0] else selected)
        return "\n".join(lines)

    def selected_line(self, i):
        fragments = list(self.visible[i][0])
        # Give blank rows and trailing space mouse coordinates in the Window map.
        padding = max(0, self.width - sum(Text(part[1]).cell_len for part in fragments))
        fragments.append(("class:layout-padding", " " * padding))
        if self.anchor is None:
            return fragments
        start, end = sorted((self.anchor, self.selection_end))
        row = self.offset + i
        if not start[0] <= row <= end[0]:
            return fragments
        if self.block_entry is not None:
            return [
                (
                    style
                    if "class:alignment-gutter" in style
                    else style + " class:block-selection",
                    text,
                )
                for style, text, *_ in fragments
            ]
        return [
            (
                style + " class:selection"
                if (row > start[0] or x >= start[1])
                and (row < end[0] or x < end[1])
                and not (self.block_text is not None and "class:layout-padding" in style)
                else style,
                char,
            )
            for x, (style, char, *_) in enumerate(explode_text_fragments(fragments))
        ]

    def is_focusable(self):
        return True

    def select_entry(self, entry):
        self.clear_selection()
        self.create_content(self.width or 80, self.height or 30)
        indices = [i for i, (_, owner) in enumerate(self.rows) if owner is entry]
        if not indices:
            return
        self.selection_rows = self.rows
        self.selection_follow = self.follow
        self.follow = False
        self.anchor = (indices[0], 0)
        last = indices[-1]
        self.selection_end = (last, len("".join(p[1] for p in self.rows[last][0])))
        self.block_text = self.chat.entry_text(entry)
        self.block_entry = entry
        self.chat.app.invalidate()

    def scroll(self, amount):
        self.follow = False
        self.offset = max(0, min(max(0, self.total - self.height), self.offset + amount))
        self.chat.app.invalidate()

    def create_content(self, width, height):
        self.width = width
        if self.chat.copy_mode:
            entries = [self.chat.copy_selected] if self.popup else self.chat.copy_entries
        else:
            entries = [self.chat.selected] if self.popup else self.chat.entries
        key = (
            width,
            int((self.chat.copy_time if self.chat.copy_mode else time.monotonic()) * 8)
            if any(entry is not None and entry.expandable and not entry.done for entry in entries)
            else None,
            tuple(
                (
                    id(entry), entry.kind, entry.title, entry.text, entry.detail,
                    entry.done, entry.status, entry.tool, entry.path, id(entry.renderable),
                )
                for entry in entries if entry is not None
            ),
        )
        if key == self.row_cache_key:
            return self.show_rows(self.row_cache, height)
        rows = []
        if not self.popup and not entries:
            welcome = [
                ("class:muted", ""),
                ("class:heading", "echo."),
                ("class:muted", ""),
                ("class:heading", "Your code. Your machine. Your Echo."),
                ("class:muted", ""),
                ("class:muted", "Ask a question or describe a change."),
                ("class:muted", "/help commands    /sessions pick up a thread"),
            ]
            if height < len(welcome):
                welcome = welcome[3:]
            for style, text in welcome[:height]:
                text = fit_text(text, width)
                padding = max(0, (width - Text(text).cell_len) // 2)
                rows.append(([(style, " " * padding + text)], None))
        for entry in entries:
            if entry is None:
                continue
            first_row = len(rows)
            user = entry.kind == "user" and not self.popup
            entry_width = width
            if user:
                natural_width = max(
                    Text(line).cell_len for line in [entry.title, *entry.text.split("\n")]
                )
                entry_width = max(1, min(natural_width, 80, max(1, width * 7 // 10 - 4)))
            style = "class:heading" if entry.kind == "text" else "class:muted"
            if entry.kind == "user":
                style = "class:accent"
            if entry.title == "Error" or entry.status.startswith("Failed"):
                style = "class:error"
            elif entry.status in {"Cancelled", "Interrupted"}:
                style = "class:warning"
            suffix = ""
            if entry.expandable:
                suffix = "" if entry.done and entry.status == "Done" else f" · {entry.status or 'Streaming'}"
                if width >= 60:
                    suffix += " · Esc close" if self.popup else " · details"
            suffix_width = Text(suffix).cell_len
            icon = []
            if entry.expandable:
                if not entry.done:
                    icon = [("class:spinner", self.chat.spinner() + " ")]
                elif entry.status.startswith("Failed"):
                    icon = [("class:error", "✗ ")]
                elif entry.status in {"Cancelled", "Interrupted"}:
                    icon = [("class:warning", "! ")]
                else:
                    icon = [("class:success", "✓ ")]
            available = max(0, entry_width - (2 if icon else 0))
            display_title = entry.title.removeprefix("Echo · ") if entry.expandable else entry.title
            title = fit_text(display_title, max(0, available - suffix_width)) + suffix
            rows.append((icon + [(style, fit_text(title, available))], entry))
            if self.popup or not entry.expandable or not entry.done:
                lines = entry.markdown_lines(max(1, entry_width if user else width - 1))
                if entry.expandable and not self.popup:
                    lines = lines[-6:]
                rows.extend((line, entry) for line in lines)
            rows.append(([("", "")], None))
            if user:
                framed = width >= 6
                bubble_width = entry_width + (4 if framed else 0)
                gutter = [
                    ("class:layout-padding class:alignment-gutter", " " * (width - bubble_width))
                ]
                border = "class:layout-padding class:user-border"
                for index in range(first_row, len(rows) - 1):
                    fragments, owner = rows[index]
                    padding = max(0, entry_width - sum(Text(p[1]).cell_len for p in fragments))
                    rows[index] = (
                        gutter
                        + ([(border, "│ ")] if framed else [])
                        + list(fragments)
                        + [("class:layout-padding", " " * padding)]
                        + ([(border, " │")] if framed else []),
                        owner,
                    )
                if framed:
                    rows.insert(
                        first_row,
                        (
                            gutter
                            + [
                                (border + " class:bubble-edge", "╭" + "─" * (entry_width + 2) + "╮")
                            ],
                            entry,
                        ),
                    )
                    rows.insert(
                        len(rows) - 1,
                        (
                            gutter
                            + [
                                (border + " class:bubble-edge", "╰" + "─" * (entry_width + 2) + "╯")
                            ],
                            entry,
                        ),
                    )
        self.row_cache_key = key
        self.row_cache = rows
        return self.show_rows(rows, height)

    def show_rows(self, rows, height):
        if self.selection_rows is not None:
            rows = self.selection_rows
        self.rows = rows
        self.total, self.height = len(rows), height
        maximum = max(0, len(rows) - height)
        self.offset = maximum if self.follow else min(self.offset, maximum)
        self.visible = rows[self.offset : self.offset + height]
        return UIContent(
            get_line=self.selected_line,
            line_count=len(self.visible),
            show_cursor=False,
        )

    def mouse_handler(self, event):
        if event.event_type == MouseEventType.SCROLL_UP:
            self.scroll(-3)
        elif event.event_type == MouseEventType.SCROLL_DOWN:
            self.scroll(3)
        elif event.button == MouseButton.LEFT and event.event_type == MouseEventType.MOUSE_DOWN:
            if not self.visible:
                return
            clicked = self.visible[min(max(event.position.y, 0), len(self.visible) - 1)][1]
            toggle = self.block_entry is not None and clicked is self.block_entry
            self.clear_selection()
            self.toggle_on_release = toggle
            self.selection_rows = self.rows
            self.selection_follow = self.follow
            self.follow = False
            row = self.offset + min(max(event.position.y, 0), len(self.visible) - 1)
            self.anchor = self.selection_end = (row, max(0, event.position.x))
            self.dragging = True
        elif event.event_type in {MouseEventType.MOUSE_MOVE, MouseEventType.MOUSE_UP}:
            if self.dragging:
                row = self.offset + min(max(event.position.y, 0), len(self.visible) - 1)
                self.selection_end = (row, max(0, event.position.x))
                self.chat.app.invalidate()
                if event.event_type == MouseEventType.MOUSE_MOVE:
                    return
                self.dragging = False
                if self.anchor != self.selection_end:
                    self.toggle_on_release = False
                    return
                self.clear_selection()
                if self.toggle_on_release:
                    self.toggle_on_release = False
                    self.chat.app.invalidate()
                    return
            if event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            if 0 <= event.position.y < len(self.visible):
                entry = self.visible[event.position.y][1]
                if entry:
                    if entry.session_target is not None and not self.chat.copy_mode:
                        if not self.chat.busy and self.chat.approval is None:
                            self.chat.confirm_session(entry.session_target)
                    elif entry.expandable and not self.popup:
                        self.chat.open_details(entry)
                        self.chat.details.select_entry(entry)
                    else:
                        self.select_entry(entry)
        else:
            return NotImplemented


class DeferredFileHistory(FileHistory):
    """Keep prompt_toolkit's in-memory history immediate; serialize disk writes."""

    def __init__(self, filename):
        super().__init__(filename)
        self.pending_write = None

    def store_string(self, string):
        previous = self.pending_write

        async def write():
            if previous is not None:
                await previous
            await asyncio.to_thread(super(DeferredFileHistory, self).store_string, string)

        self.pending_write = asyncio.create_task(write())

    async def flush(self):
        if self.pending_write is not None:
            await self.pending_write


class TerminalChat:
    def __init__(self, agent, root, renderer, *, input=None, output=None):
        self.agent, self.renderer = agent, renderer
        self.theme = load_theme()
        self.entries = []
        self.current = {}
        self.drafts = {}
        self.selected = None
        self.task = None
        self.approval = None
        self.approval_correction = False
        self.pending_session = None
        self.model_settings = None
        if not hasattr(agent, "permissions"):
            agent.permissions = Permissions()
        agent.permissions.ask = self.ask_permission
        self.copy_mode = False
        self.copy_entries = []
        self.copy_selected = None
        self.copy_time = 0.0
        self.copy_status = ""
        self.copy_header = []
        self.input_rows = 3
        self.resize_drag = None
        self.transcript = TranscriptControl(self)
        self.details = TranscriptControl(self, popup=True)
        self.editor = TextArea(
            prompt="echo › ",
            multiline=True,
            height=self.input_height,
            history=DeferredFileHistory(str(root / "input-history")),
            completer=CommandCompleter(),
            read_only=Condition(lambda: self.copy_mode),
            focus_on_click=True,
            style="class:composer",
        )
        self.permission_input = TextArea(
            prompt="tell Echo › ",
            multiline=True,
            height=self.input_height,
            focus_on_click=True,
            style="class:composer",
        )
        self.permission_choices = Window(
            FormattedTextControl(self.approval_text, focusable=True), height=3,
            style="class:permission",
        )
        self.session_choices = Window(
            FormattedTextControl(self.session_confirmation_text, focusable=True),
            height=3, style="class:permission",
        )
        keys = KeyBindings()

        @keys.add("enter")
        def submit(event):
            if self.pending_session is not None:
                return
            if self.approval is not None:
                if self.approval_correction:
                    message = self.permission_input.text.strip()
                    if message:
                        self.resolve_approval("deny", message)
                return
            if self.editor.buffer.complete_state:
                completion = (
                    self.editor.buffer.complete_state.current_completion
                    or self.editor.buffer.complete_state.completions[0]
                )
                already_complete = completion.text == self.editor.text
                self.editor.buffer.apply_completion(completion)
                if not already_complete:
                    return
            if self.copy_mode:
                self.toggle_copy()
            elif self.selected:
                self.close_details()
            elif not self.busy:
                text = self.editor.text.strip()
                if text:
                    if text not in {"/exit", "/new"} and self.pending_session is None:
                        self.editor.buffer.append_to_history()
                    self.editor.buffer.reset()
                    self.editor.buffer.load_history_if_not_yet_loaded()
                    self.task = self.app.create_background_task(self.submit(text))

        @keys.add("c-j")
        def newline(event):
            if self.approval_correction:
                self.permission_input.buffer.insert_text("\n")
            elif self.approval is None and self.pending_session is None and not self.selected and not self.copy_mode:
                self.editor.buffer.insert_text("\n")

        @keys.add("y", filter=Condition(lambda: self.pending_session is not None))
        @keys.add("Y", filter=Condition(lambda: self.pending_session is not None))
        def resume_session(event):
            self.resolve_session(True)

        @keys.add("n", filter=Condition(lambda: self.pending_session is not None))
        @keys.add("N", filter=Condition(lambda: self.pending_session is not None))
        def decline_session(event):
            self.cancel_session()

        @keys.add("s-tab")
        def toggle_permissions(event):
            self.agent.permissions.yolo = not self.agent.permissions.yolo
            self.app.invalidate()

        @keys.add("y", filter=Condition(lambda: self.approval is not None and not self.approval_correction))
        def approve_once(event):
            self.resolve_approval("once")

        @keys.add("a", filter=Condition(lambda: self.approval is not None and not self.approval_correction))
        def approve_session(event):
            if self.approval["rule"]:
                self.resolve_approval("session")

        @keys.add("n", filter=Condition(lambda: self.approval is not None and not self.approval_correction))
        def deny(event):
            self.resolve_approval("deny")

        @keys.add("t", filter=Condition(lambda: self.approval is not None and not self.approval_correction))
        def tell_echo(event):
            self.approval_correction = True
            self.permission_input.buffer.reset()
            self.app.layout.focus(self.permission_input)
            self.app.invalidate()

        @keys.add("escape")
        def close(event):
            if self.approval_correction:
                self.approval_correction = False
                self.app.layout.focus(self.permission_choices)
                self.app.invalidate()
            elif self.approval is not None:
                self.resolve_approval("deny")
            elif self.pending_session is not None:
                self.cancel_session()
            elif self.editor.buffer.complete_state is not None:
                self.editor.buffer.cancel_completion()
            elif self.copy_mode:
                self.toggle_copy()
            elif self.selected:
                self.close_details()

        @keys.add("f2")
        @keys.add("escape", "d")
        def latest(event):
            if self.selected:
                self.close_details()
            else:
                self.latest_details()

        @keys.add("c-c", eager=True)
        def copy_latest(event):
            if self.app.layout.has_focus(self.editor) and self.editor.buffer.selection_state:
                # Extract from the immutable document without cutting the live buffer.
                self.copy_text(self.editor.buffer.document.cut_selection()[1].text)
            else:
                self.copy_output()

        @keys.add("f24")
        def copy_all(event):
            self.copy_output(all_entries=True)

        @keys.add("f23", filter=Condition(lambda: not self.selected and not self.copy_mode and self.pending_session is None))
        def clear_draft(event):
            self.clear_input()

        @keys.add("f3")
        @keys.add("escape", "y")
        def selection_mode(event):
            self.toggle_copy()

        @keys.add("pageup")
        def page_up(event):
            control = self.details if self.selected else self.transcript
            control.scroll(-max(1, control.height - 1))

        @keys.add("pagedown")
        def page_down(event):
            control = self.details if self.selected else self.transcript
            control.scroll(max(1, control.height - 1))

        @keys.add("c-end")
        def follow(event):
            control = self.details if self.selected else self.transcript
            control.clear_selection()
            control.follow = True

        @keys.add("c-d")
        def exit_app(event):
            if self.busy:
                self.task.cancel()
            else:
                self.app.exit()

        @keys.add("f4")
        def settings(event):
            if not self.busy and self.approval is None and self.pending_session is None:
                self.open_model_settings()

        status = Window(FormattedTextControl(self.status), height=1, style="class:muted")
        permission_panel = Frame(
            HSplit([
                self.permission_choices,
                ConditionalContainer(
                    self.permission_input,
                    filter=Condition(lambda: self.approval_correction),
                ),
            ]),
            title="Permission required",
            style="class:permission",
        )
        composer = HSplit([
            Window(height=1, char="─", style="class:user-border"),
            self.editor,
            Window(height=1, style="class:composer"),
        ], style="class:composer")
        body = HSplit(
            [
                Window(
                    FormattedTextControl(self.header),
                    height=lambda: 3 if self.roomy_header() else 1,
                ),
                VSplit([Window(width=self.side_padding), Window(self.transcript), Window(width=self.side_padding)]),
                VSplit([
                    Window(width=lambda: max(0, self.side_padding() - 2)),
                    Window(FormattedTextControl(self.composer_hint), height=1, style="class:muted"),
                    Window(FormattedTextControl(self.mode_label), width=lambda: 26 if self.app.output.get_size().columns >= 60 else 12, height=1),
                    Window(width=self.side_padding),
                ]),
                VSplit(
                    [
                        Window(width=self.side_padding),
                        ConditionalContainer(
                            composer,
                            filter=Condition(lambda: self.approval is None and self.pending_session is None),
                        ),
                        ConditionalContainer(
                            permission_panel,
                            filter=Condition(lambda: self.approval is not None),
                        ),
                        ConditionalContainer(
                            Frame(self.session_choices, title="Resume session?", style="class:permission"),
                            filter=Condition(lambda: self.pending_session is not None),
                        ),
                        Window(width=self.side_padding),
                    ]
                ),
                status,
            ]
        )
        popup = ConditionalContainer(
            Frame(Window(self.details), title=self.details_title),
            filter=Condition(lambda: self.selected is not None),
        )
        layout = FloatContainer(
            body,
            floats=[
                Float(content=popup, left=2, right=2, top=2, bottom=2),
                Float(content=ConditionalContainer(
                    DynamicContainer(lambda: self.model_settings or Window()),
                    filter=Condition(lambda: self.model_settings is not None),
                ), left=2, right=2),
                Float(xcursor=True, ycursor=True, content=CompletionsMenu(max_height=10)),
            ],
        )
        self.app = Application(
            layout=Layout(layout, focused_element=self.editor),
            key_bindings=ConditionalKeyBindings(
                keys, filter=Condition(lambda: self.model_settings is None),
            ),
            full_screen=True,
            mouse_support=Condition(lambda: not self.copy_mode),
            input=input,
            output=output,
            min_redraw_interval=0.016,
            refresh_interval=None,
            after_render=self.install_resize_handlers,
            style=Style.from_dict(self.theme.styles()),
        )

        # Resolve standalone Esc promptly while leaving time for Alt key sequences.
        self.app.ttimeoutlen = 0.1
        self.app.timeoutlen = 0.5

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def approval_text(self):
        if self.approval is None:
            return ""
        item = self.approval
        target = item["args"].get("command") or item["args"].get("path") or ""
        parts = [
            ("class:warning", f" {item['name']}  "),
            ("class:permission-target", fit_text(target, max(8, self.app.output.get_size().columns - 18))),
            ("", "\n"),
        ]
        if self.approval_correction:
            parts.append(("class:muted", " Enter sends · Ctrl+J new line · Esc back"))
        else:
            parts.extend([
                ("class:success", " Y "), ("", "Allow once   "),
                ("class:error", " N "), ("", "Deny   "),
                ("class:accent", " T "), ("", "Tell Echo"),
            ])
            if item["rule"]:
                parts.extend([
                    ("", "\n"),
                    ("class:success", " A "),
                    ("", f"Allow ({item['rule']}) for this session"),
                ])
        return parts

    async def ask_permission(self, name, args, rule):
        future = asyncio.get_running_loop().create_future()
        self.approval = {"name": name, "args": args, "rule": rule, "future": future}
        self.approval_correction = False
        self.permission_input.buffer.reset()
        self.app.layout.focus(self.permission_choices)
        self.app.invalidate()
        try:
            return await future
        finally:
            self.approval = None
            self.approval_correction = False
            self.permission_input.buffer.reset()
            self.app.layout.focus(self.editor)
            self.app.invalidate()

    def resolve_approval(self, decision, message=""):
        if self.approval and not self.approval["future"].done():
            self.approval["future"].set_result((decision, message))
            self.app.invalidate()

    def input_height(self):
        if not hasattr(self, "app"):
            return self.input_rows
        return max(1, min(self.input_rows, self.app.output.get_size().rows - 8))

    def install_resize_handlers(self, app):
        """Capture dragging across panes, using terminal coordinates throughout."""
        info = self.editor.window.render_info
        if info is None or self.selected or self.copy_mode or self.approval is not None or self.pending_session is not None or self.model_settings is not None:
            self.resize_drag = None
            return
        handlers = app.renderer.mouse_handlers
        size = app.output.get_size()
        if self.resize_drag is None:
            handlers.set_mouse_handler_for_range(
                self.side_padding(),
                max(self.side_padding(), size.columns - self.side_padding()),
                info._y_offset - 1,
                info._y_offset,
                self.resize_input,
            )
        else:
            for y in range(size.rows):
                for x in range(size.columns):
                    original = handlers.mouse_handlers[y][x]

                    def capture(event, original=original):
                        if self.resize_drag is not None:
                            return self.resize_input(event)
                        return original(event)

                    handlers.mouse_handlers[y][x] = capture

    def resize_input(self, event):
        if event.event_type == MouseEventType.MOUSE_DOWN and event.button == MouseButton.LEFT:
            self.resize_drag = (event.position.y, self.input_height())
            self.install_resize_handlers(self.app)
        elif self.resize_drag is not None and event.event_type in {
            MouseEventType.MOUSE_MOVE,
            MouseEventType.MOUSE_UP,
        }:
            start_y, start_height = self.resize_drag
            maximum = max(1, self.app.output.get_size().rows - 8)
            self.input_rows = max(1, min(maximum, start_height + start_y - event.position.y))
            if event.event_type == MouseEventType.MOUSE_UP:
                self.resize_drag = None
            self.app.invalidate()
        else:
            return NotImplemented

    def side_padding(self):
        return 2

    def status(self):
        if self.copy_mode:
            return self.copy_status
        width = self.app.output.get_size().columns
        active = self.renderer.active
        parts = []
        if active.context is not None and active.capacity:
            prefix = "~" if active.estimated else ""
            parts.append(f"Context {prefix}{active.context:,} / {active.capacity:,}")
        if active.requested:
            parts.append(active.generated_text())
        if self.renderer.tools:
            parts.append(f"{self.renderer.tools} tools")
        if not parts:
            parts.append("Session " + safe_text(self.agent.session_id)[:8])
        parts.append("/status details")
        parts.append("F4 /model")
        return " " * self.side_padding() + fit_text(" · ".join(parts), width - self.side_padding() * 2)

    def spinner(self):
        moment = self.copy_time if self.copy_mode else time.monotonic()
        return "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(moment * 8) % 10]

    def toggle_copy(self):
        self.transcript.clear_selection()
        self.details.clear_selection()
        if not self.copy_mode:
            self.copy_status = self.status()
            self.copy_header = list(self.header())
            self.copy_time = time.monotonic()
            self.copy_entries = [replace(entry) for entry in self.entries]
            self.copy_selected = replace(self.selected) if self.selected else None
        else:
            self.copy_entries = []
            self.copy_selected = None
        self.copy_mode = not self.copy_mode
        self.app.invalidate()

    def copy_selection(self):
        control = self.details if self.selected else self.transcript
        text = control.selected_text()
        if not text:
            return False
        self.copy_text(text)
        return True

    @staticmethod
    def entry_text(entry):
        return "\n\n".join(part for part in (entry.detail, entry.text) if part)

    def copy_output(self, *, all_entries=False):
        entries = self.copy_entries if self.copy_mode else self.entries
        if all_entries:
            text = "\n\n".join(
                f"{'user' if entry.kind == 'user' else 'echo'}:\n"
                + json.dumps(entry.text, ensure_ascii=False)
                for entry in entries
                if entry.kind in {"user", "text"}
            )
        else:
            if self.copy_selection():
                return
            entry = (self.copy_selected if self.copy_mode else self.selected) or next(
                (entry for entry in reversed(entries) if entry.kind == "text"), None
            )
            text = self.entry_text(entry) if entry else ""
        if text:
            self.copy_text(text)

    def copy_text(self, text):
        # OSC 52 targets the user's terminal clipboard, including over SSH.
        payload = base64.b64encode(text.encode()).decode("ascii")
        self.app.output.write_raw(f"\x1b]52;c;{payload}\x07")
        self.app.output.flush()

    def latest_details(self):
        entry = next((e for e in reversed(self.entries) if e.expandable), None)
        self.open_details(entry or Entry("notice", "Details", "No tool or reasoning traces yet."))

    def roomy_header(self):
        size = self.app.output.get_size()
        return size.columns >= 44 and size.rows >= 18

    def header(self):
        if self.copy_mode:
            return self.copy_header
        width = self.app.output.get_size().columns
        padding = self.side_padding()
        available = max(1, width - padding * 2)
        status = safe_text(self.renderer.active.status) if self.busy else "Ready"
        roomy = self.roomy_header()
        orb = orb_frame(time.monotonic()) if self.busy and roomy else None
        model = safe_text(self.renderer.model) or "Local coding agent"
        cost = "Turn API: " + self.renderer.cost_text()
        left_rows = ["echo.", fit_text(model, max(1, available - 28)),
                     fit_text(cost, max(1, available - 28))] if roomy else ["echo."]
        fragments = []
        for index, left in enumerate(left_rows):
            if orb:
                right = (fit_text(status, max(0, available // 2 - 8)) + "  " if index == 1 else "") + orb[index]
            else:
                right = (self.spinner() + " " if self.busy else "") + status if index == 0 else ""
            right = fit_text(right, max(0, available - Text(left).cell_len - 1))
            gap = max(0, available - Text(left).cell_len - Text(right).cell_len)
            fragments.extend([
                ("", " " * padding),
                ("class:heading" if index == 0 else "class:muted", left),
                ("", " " * gap), ("class:muted", right),
            ])
            if index < len(left_rows) - 1:
                fragments.append(("", "\n"))
        return fragments

    def mode_label(self):
        auto = self.agent.permissions.yolo
        label = "Auto approve" if auto else "Ask first"
        shortcut = " · Shift+Tab" if self.app.output.get_size().columns >= 60 else ""
        return [("class:error" if auto else "class:muted", label), ("class:muted", shortcut)]

    def composer_hint(self):
        width = self.app.output.get_size().columns
        if self.pending_session is not None:
            items = ["Y Resume", "N Cancel", "Esc Cancel"]
        elif self.approval is not None:
            items = ["Permission required", "Choose in the box below"]
        elif self.copy_mode:
            items = ["Select text", "Cmd+C (Mac) / Ctrl+Shift+C (Linux)", "Esc Return"]
        elif (self.details if self.selected else self.transcript).selected_text():
            items = ["Ctrl+C Copy", "Click again to deselect"]
        elif self.selected:
            items = ["Ctrl+C Copy section", "Esc Close"]
        elif self.editor.text in COMMANDS:
            items = [f"{self.editor.text} · {COMMANDS[self.editor.text]}", "Enter Run"]
        else:
            items = ["Enter Send", "Ctrl+J New line", "Ctrl+C Copy"]
            items.append("Ctrl+D Stop" if self.busy else "/help Commands")
        clear = bool(self.editor.text and self.approval is None and self.pending_session is None and not self.selected and not self.copy_mode)
        label = "Ctrl+Shift+U Clear input" if width >= 60 else "Clear input"
        reserved = len(label) + 3 if clear else 0
        available = max(0, width - reserved - 2)
        # Drop whole hints on narrow terminals instead of cutting through shortcuts.
        while len(items) > 1 and len(" · ".join(items)) > available:
            items.pop()
        fragments = key_highlights("  " + " · ".join(items), max(0, width - reserved))
        if clear:
            fragments.append(("class:muted", " · "))
            fragments.extend(
                (style, text, self.clear_input)
                for style, text in key_highlights(label, min(len(label), width))
            )
        return fragments

    def clear_input(self, event=None):
        if event is None or (
            event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT
        ):
            self.editor.text = ""
            self.app.layout.focus(self.editor)
            self.app.invalidate()

    def details_title(self):
        width = max(1, self.app.output.get_size().columns - 10)
        title = (
            "Esc resume · Select text · Ctrl+Shift+C copy"
            if self.copy_mode
            else "Trace details · Ctrl+c copy · Ctrl+Shift+C copy all · Esc close"
        )
        return key_highlights(title, width)

    def help_entry(self):
        return Entry(
            "notice",
            "Commands · Esc close",
            "```text\n" + help_text() + "\n```\n\n"
            "**Enter** Send · **Ctrl+J** New line · **Esc** Close menu/details · **Ctrl+D** Stop/exit\n\n"
            "- **Select:** Click a block or drag across text. Click a selected block again to deselect.\n"
            "- **Copy:** Ctrl+C copies your selection, or the latest answer if nothing is selected. "
            "Ctrl+Shift+C copies the whole conversation.\n"
            "- **Paste:** Cmd+V on Mac; Ctrl+Shift+V on Linux.\n"
            "- **Clear input:** Ctrl+Shift+U or click **Clear input**.\n\n"
            "**Resize input:** Drag the top border of the input box up or down.\n\n"
            "Copy shortcut not working? Press Alt+y, select text, and use your usual copy shortcut. "
            "Press Esc to return.",
        )

    def add(self, kind, title, text="", **kwargs):
        entry = Entry(kind, safe_text(title), safe_text(text), **kwargs)
        self.entries.append(entry)
        return entry

    def open_details(self, entry):
        self.transcript.clear_selection()
        self.details.clear_selection()
        if self.copy_mode:
            self.toggle_copy()
        self.selected = entry
        self.details.offset = 0
        self.details.follow = False
        self.app.layout.focus(self.details)
        self.app.invalidate()

    def close_details(self):
        self.details.clear_selection()
        if self.copy_mode:
            self.toggle_copy()
        self.selected = None
        self.app.layout.focus(self.editor)
        self.app.invalidate()

    def on_event(self, kind, value):
        actor = "Review" if kind.startswith("child_") else "Echo"
        kind = kind.removeprefix("child_")
        if kind in {"reasoning", "text"}:
            if kind == "text":
                thought = self.current.get((actor, "reasoning"))
                if thought:
                    thought.done, thought.status = True, "Done"
            key = (actor, kind)
            entry = self.current.get(key)
            if entry is None:
                entry = self.add(kind, f"{actor} · Reasoning" if kind == "reasoning" else actor)
                self.current[key] = entry
            entry.text += safe_text(value)
        elif kind == "tool_call_delta":
            key = (actor, value["index"])
            entry = self.drafts.get(key)
            if entry is None:
                entry = self.add("tool", f"{actor} · Tool", status="Preparing")
                self.drafts[key] = entry
            entry.title = f"{actor} · {safe_text(value['name']) or 'Tool'}"
            entry.tool = safe_text(value["name"])
            entry.detail = safe_text(value["arguments"])
        elif kind == "tool_start":
            entry = next(
                (
                    e
                    for (a, _), e in sorted(self.drafts.items())
                    if a == actor and e.status == "Preparing"
                ),
                None,
            )
            if entry is None:
                entry = self.add("tool", f"{actor} · {safe_text(value)}")
            entry.status = "Running"
            entry.tool = safe_text(value)
            self.current[(actor, "tool")] = entry
        elif kind in {"tool_detail", "tool_output", "tool_end"}:
            entry = self.current.get((actor, "tool"))
            if entry:
                if kind == "tool_detail":
                    args = value["args"]
                    entry.tool = safe_text(value["name"])
                    entry.path = safe_text(args.get("path", ""))
                    summary = args.get("command") or args.get("path") or args.get("pattern")
                    entry.title = f"{actor} · {safe_text(value['name'])}"
                    if summary:
                        entry.title += " · " + safe_text(summary).replace("\n", " ")[:80]
                    entry.detail = safe_text(json.dumps(value["args"], indent=2))
                elif kind == "tool_output":
                    entry.text += safe_text(value)
                else:
                    parts = [str(value[k]) for k in ("error", "output", "findings", "undo_note")
                             if value.get(k)]
                    entry.text = safe_text(
                        "\n\n".join(parts) if parts else json.dumps(value, indent=2)
                    )
                    failed = bool(value.get("error") or value.get("exit_code", 0))
                    entry.status = "Failed" if failed else "Done"
                    if value.get("exit_code"):
                        entry.status += f" · exit {value['exit_code']}"
                    entry.done = True
                    self.current.pop((actor, "tool"), None)
        elif kind == "input_rejected" and actor == "Echo":
            for entry in reversed(self.entries):
                if entry.kind == "user":
                    self.entries.remove(entry)
                    break
            if not self.editor.text:
                self.editor.text = value["prompt"]
        elif kind in {"model_end", "run_end"}:
            for key in list(self.current):
                if key[0] == actor and (key[1] != "tool" or kind == "run_end"):
                    entry = self.current.pop(key)
                    entry.done = True
                    entry.status = value.get("status", "Done").capitalize()
            if kind == "run_end":
                for (a, _), entry in self.drafts.items():
                    if a == actor and not entry.done:
                        entry.done = True
                        entry.status = value["status"].capitalize()
        elif kind == "model_start":
            self.drafts = {k: e for k, e in self.drafts.items() if k[0] != actor}
        elif kind == "task":  # child_task after removing the prefix
            self.add("notice", "Read-only subagent", value)
        self.app.invalidate()

    def confirm_session(self, target):
        if self.pending_session is not None or self.approval is not None:
            return
        if target["id"] == self.agent.session_id:
            self.add("notice", "Sessions", "This is already the current session.")
            return
        self.pending_session = target
        self.transcript.clear_selection()
        self.app.layout.focus(self.session_choices)
        self.app.invalidate()

    def session_confirmation_text(self):
        if self.pending_session is None:
            return ""
        target = self.pending_session
        width = max(1, self.app.output.get_size().columns - 8)
        return [
            ("class:permission-target", fit_text(safe_text(target['title'] or 'New session'), width)),
            ("class:muted", f"\n{target['id']}\n"),
            ("class:success", " Y "), ("", "Resume   "),
            ("class:error", " N "), ("", "Cancel   "),
            ("class:muted", "Esc Cancel"),
        ]

    def resolve_session(self, confirmed):
        if self.pending_session is None:
            return
        target = self.pending_session["id"]
        self.cancel_session()
        if confirmed:
            self.app.exit(result=target)

    def cancel_session(self):
        self.pending_session = None
        self.app.layout.focus(self.editor)
        self.app.invalidate()

    def open_model_settings(self):
        if getattr(self.agent, "running", False) or self.approval or self.pending_session:
            return
        if self.copy_mode:
            self.toggle_copy()
        if self.selected:
            self.close_details()
        self.model_settings = ModelSettings(
            self.agent.model.config, self.save_model_settings, self.close_model_settings,
        )
        self.app.layout.update_parents_relations()
        self.app.layout.focus(self.model_settings.profile.control)
        self.app.invalidate()

    def close_model_settings(self):
        self.model_settings = None
        self.app.layout.focus(self.editor)
        self.app.invalidate()

    def save_model_settings(self, config, *, make_default=True):
        self.agent.update_model(config, make_default=make_default)
        self.renderer.configure(self.agent, plain=self.renderer.plain)
        self.close_model_settings()
        self.add("notice", "Model settings saved",
                 f"{config.provider}/{config.model} · reasoning "
                 f"{config.reasoning_effort or ('default' if config.reasoning_enabled else 'off')}"
                 + ("\nSaved as the default for new sessions." if make_default
                    else "\nSaved for this session only."))

    async def submit(self, text):
        self.transcript.clear_selection()
        self.transcript.follow = True
        if self.pending_session is not None:
            answer = text.strip().lower()
            if answer in {"y", "yes"}:
                self.resolve_session(True)
            elif answer in {"n", "no"}:
                self.cancel_session()
            return
        if text == "/exit":
            self.app.exit()
            return
        if text in {"/yolo", "/default"}:
            self.agent.permissions.yolo = text == "/yolo"
            self.add("notice", "Permissions", "YOLO" if self.agent.permissions.yolo else "Default")
            self.app.invalidate()
            return
        if text == "/new":
            self.app.exit(result=NEW_SESSION)
            return
        if text == "/help":
            self.open_details(self.help_entry())
            return
        if text in {"/model", "/settings"}:
            self.open_model_settings()
            return
        if text == "/status":
            self.add(
                "notice",
                "Status",
                status_text(self.agent, self.renderer),
                renderable=status_panel(self.agent, self.renderer, theme=self.theme),
            )
            return
        if text == "/sessions" or text.startswith("/sessions "):
            try:
                session = self.agent.store.session(self.agent.session_id)
                if text == "/sessions":
                    rows = self.agent.store.sessions(session["repo"], include_children=False)
                    for row in reversed(rows):
                        self.add(
                            "notice", "Sessions", f"{row['title'] or 'New session'}\n{row['id']}",
                            session_target=row,
                            renderable=session_rows_panel(
                                [row], current=self.agent.session_id, theme=self.theme,
                                clickable=True,
                            ),
                        )
                    if not rows:
                        self.add("notice", "Sessions", "No sessions found.")
                else:
                    target = self.agent.store.resolve(text.split(maxsplit=1)[1], session["repo"])
                    self.confirm_session(target)
            except ValueError as error:
                self.add("notice", "Error", str(error))
            return
        if text == "/diff":
            try:
                patch = "\n".join(
                    item["patch"] for item in
                    self.agent.store.active_tool_changes(self.agent.session_id)
                    if item["patch"]
                )
                self.open_details(
                    Entry(
                        "notice",
                        "Changes",
                        patch if patch.strip() else "No recorded agent changes.",
                        renderable=diff_renderable(patch)
                        if patch.strip()
                        else None,
                    )
                )
            except (RuntimeError, ValueError, OSError) as error:
                self.add("notice", "Error", str(error))
            return
        if text in {"/undo", "/undo force", "/redo", "/redo force"}:
            try:
                action, *options = text[1:].split()
                paths = await move_turn(self.agent, action, force=bool(options))
                self.load_history(clear=True)
                self.open_details(Entry(
                    "notice", action.capitalize(),
                    f"Conversation branch switched. Files changed: {', '.join(paths) or '(none)'}."
                ))
            except (RuntimeError, ValueError, OSError) as error:
                self.open_details(Entry("notice", "Restore conflict", str(error)))
            return
        if text in {"/apply", "/apply force"}:
            try:
                paths = await apply_sandbox(self.agent, force=text.endswith(" force"))
                self.open_details(Entry(
                    "notice", "Applied sandbox changes",
                    ", ".join(paths) or "No file changes to apply.",
                ))
            except (RuntimeError, ValueError, OSError) as error:
                self.open_details(Entry("notice", "Apply conflict", str(error)))
            return
        if text.startswith("/"):
            self.add("notice", "Unknown command", "Use /help.")
            return
        self.add("user", "You", text)
        self.renderer.start()
        refresh = asyncio.create_task(self.refresh_activity())
        status = "failed"
        try:
            result = await self.agent.run(text)
            status = result.get("status", "completed")
        except asyncio.CancelledError:
            status = "cancelled"
            self.add("notice", "Cancelled", "Inspect /diff before retrying.")
        except (RuntimeError, ValueError, OSError, httpx.HTTPError) as error:
            self.add("notice", "Error", str(error))
        finally:
            refresh.cancel()
            await asyncio.gather(refresh, return_exceptions=True)
            self.renderer.stop(status)
            # Some adapters do not emit run_end; close any unfinished trace too.
            for actor in ("Echo", "Review"):
                self.on_event(
                    "child_run_end" if actor == "Review" else "run_end", {"status": status}
                )
            self.app.invalidate()

    async def refresh_activity(self):
        while True:
            await asyncio.sleep(0.125)
            self.app.invalidate()

    def load_history(self, *, clear=False):
        if clear:
            self.entries.clear()
        if hasattr(self.agent, "store"):
            for message in self.agent.store.messages(self.agent.session_id):
                if message["role"] in {"user", "assistant"} and message.get("content"):
                    user = message["role"] == "user"
                    self.add(
                        "user" if user else "text", "You" if user else "Echo", message["content"]
                    )

    async def run(self):
        self.load_history()
        self.renderer.event_handler = self.on_event
        try:
            return await self.app.run_async()
        finally:
            if self.busy:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            await self.editor.buffer.history.flush()
            self.renderer.event_handler = None
