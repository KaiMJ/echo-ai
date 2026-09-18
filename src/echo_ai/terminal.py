"""Persistent interactive transcript; Rich formats Markdown, prompt_toolkit owns the screen."""

import asyncio
import base64
import json
import re
import time
from dataclasses import dataclass, field, replace
from io import StringIO
from pathlib import PurePath

import httpx
from prompt_toolkit import Application
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, to_formatted_text
from prompt_toolkit.formatted_text.utils import split_lines
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer,
    Float,
    FloatContainer,
    HSplit,
    Layout,
    VSplit,
    Window,
)
from prompt_toolkit.layout.controls import FormattedTextControl, UIContent, UIControl
from prompt_toolkit.layout.utils import explode_text_fragments
from prompt_toolkit.mouse_events import MouseButton, MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text

from .ui import safe_text


def fit_text(value, width):
    """Clip chrome by terminal cells, including wide Unicode characters."""
    text = Text(safe_text(value).replace("\n", " ").replace("\t", " "))
    text.truncate(max(0, width), overflow="ellipsis")
    return text.plain


def key_highlights(value, width):
    text = fit_text(value, width)
    keys = r"(Ctrl\+Shift\+C|Ctrl-End|Ctrl-C|Alt\+Enter|Alt\+[dy]|PgUp/PgDn|Enter|Esc|F[123])"
    return [
        ("class:key" if re.fullmatch(keys, part) else "class:muted", part)
        for part in re.split(keys, text)
        if part
    ]


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
                color_system="standard",
                highlight=False,
            )
            if self.kind == "tool":
                if self.detail:
                    console.print(Text("Arguments", style="dim"))
                    console.print(
                        Syntax(self.detail, "json", word_wrap=True, background_color="default")
                    )
                    console.print()
                console.print(Text("Output", style="dim"))
                body = self.text or ("No output." if self.done else "Waiting for output…")
                if self.tool == "read" and not self.status.startswith("Failed"):
                    # Read results prefix each source line with its original line number.
                    body = re.sub(r"(?m)^\d+: ", "", body)
                    if PurePath(self.path).suffix.lower() in {".md", ".markdown", ".mdown"}:
                        console.print(Markdown(body))
                    else:
                        lexer = Syntax.guess_lexer(self.path, body)
                        console.print(
                            Syntax(body, lexer, word_wrap=True, background_color="default")
                        )
                elif self.tool == "delegate":
                    console.print(Markdown(body))
                else:
                    # Shell output, filenames, and search matches are literal text.
                    console.print(Text(body))
            else:
                console.print(Markdown(source or "Waiting for output…"))
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
        self.total = self.height = 0
        self.rows = []
        self.selection_rows = None
        self.anchor = self.selection_end = None
        self.dragging = False
        self.selection_follow = True

    def clear_selection(self):
        if self.selection_rows is not None:
            self.follow = self.selection_follow
        self.selection_rows = None
        self.anchor = self.selection_end = None
        self.dragging = False

    def selected_text(self):
        if self.anchor is None or self.anchor == self.selection_end:
            return ""
        start, end = sorted((self.anchor, self.selection_end))
        lines = []
        for index in range(start[0], end[0] + 1):
            text = "".join(part[1] for part in self.selection_rows[index][0])
            left = start[1] if index == start[0] else 0
            right = end[1] if index == end[0] else len(text)
            selected = text[left:right]
            # Rich pads rendered rows to the viewport; omit that padding when copying.
            lines.append(selected.rstrip() if index < end[0] else selected)
        return "\n".join(lines)

    def selected_line(self, i):
        fragments = self.visible[i][0]
        if self.anchor is None:
            return fragments
        start, end = sorted((self.anchor, self.selection_end))
        row = self.offset + i
        if not start[0] <= row <= end[0]:
            return fragments
        return [
            (
                style + " class:selection"
                if (row > start[0] or x >= start[1]) and (row < end[0] or x < end[1])
                else style,
                char,
            )
            for x, (style, char, *_) in enumerate(explode_text_fragments(fragments))
        ]

    def is_focusable(self):
        return True

    def scroll(self, amount):
        self.follow = False
        self.offset = max(0, min(max(0, self.total - self.height), self.offset + amount))
        self.chat.app.invalidate()

    def create_content(self, width, height):
        rows = []
        if self.chat.copy_mode:
            entries = [self.chat.copy_selected] if self.popup else self.chat.copy_entries
        else:
            entries = [self.chat.selected] if self.popup else self.chat.entries
        if not self.popup and not entries:
            for style, text in (
                ("class:heading", "What would you like to work on?"),
                ("class:muted", "Describe a change, investigate a bug, or ask about the code."),
                ("class:muted", "/help for commands · /diff to inspect changes"),
            ):
                rows.append(([(style, fit_text(text, width))], None))
            rows = rows[:height]
        for entry in entries:
            if entry is None:
                continue
            style = "class:heading" if entry.kind == "text" else "class:muted"
            if entry.kind == "user":
                style = "class:accent"
            if entry.title == "Error" or entry.status.startswith("Failed"):
                style = "class:error"
            elif entry.status in {"Cancelled", "Interrupted"}:
                style = "class:warning"
            suffix = ""
            if entry.expandable:
                suffix = f" · {entry.status or 'Streaming'}"
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
            available = max(0, width - (2 if icon else 0))
            title = fit_text(entry.title, max(0, available - suffix_width)) + suffix
            rows.append(
                (icon + [(style, fit_text(title, available))], entry if entry.expandable else None)
            )
            if self.popup or not entry.expandable or not entry.done:
                lines = entry.markdown_lines(max(1, width - 1))
                if entry.expandable and not self.popup:
                    lines = lines[-6:]
                rows.extend((line, None) for line in lines)
            rows.append(([("", "")], None))
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
            self.clear_selection()
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
                    return
                self.clear_selection()
            if event.event_type != MouseEventType.MOUSE_UP:
                return NotImplemented
            if 0 <= event.position.y < len(self.visible):
                entry = self.visible[event.position.y][1]
                if entry:
                    if self.popup:
                        self.chat.close_details()
                    else:
                        self.chat.open_details(entry)
        else:
            return NotImplemented


class TerminalChat:
    def __init__(self, agent, root, renderer, *, input=None, output=None):
        self.agent, self.renderer = agent, renderer
        self.entries = []
        self.current = {}
        self.drafts = {}
        self.selected = None
        self.task = None
        self.copy_mode = False
        self.copy_entries = []
        self.copy_selected = None
        self.copy_time = 0.0
        self.copy_status = ""
        self.transcript = TranscriptControl(self)
        self.details = TranscriptControl(self, popup=True)
        self.editor = TextArea(
            prompt="echo › ",
            multiline=True,
            height=3,
            history=FileHistory(str(root / "input-history")),
            completer=WordCompleter(["/help", "/diff", "/status", "/details", "/copy", "/exit"]),
            read_only=Condition(lambda: self.busy or self.copy_mode),
            style="class:composer",
        )
        keys = KeyBindings()

        @keys.add("enter")
        def submit(event):
            if self.copy_mode:
                self.toggle_copy()
            elif self.selected:
                self.close_details()
            elif not self.busy:
                text = self.editor.text.strip()
                if text:
                    self.editor.buffer.append_to_history()
                    self.editor.text = ""
                    self.task = self.app.create_background_task(self.submit(text))

        @keys.add("escape", "enter")
        def newline(event):
            if not self.busy and not self.selected and not self.copy_mode:
                self.editor.buffer.insert_text("\n")

        @keys.add("escape")
        def close(event):
            control = self.details if self.selected else self.transcript
            if control.selection_rows is not None:
                control.clear_selection()
            elif self.copy_mode:
                self.toggle_copy()
            else:
                self.close_details()

        @keys.add("f2")
        @keys.add("escape", "d")
        def latest(event):
            if self.selected:
                self.close_details()
            else:
                self.latest_details()

        @keys.add("f1")
        def help_view(event):
            self.open_details(self.help_entry())

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

        @keys.add("c-c")
        def cancel(event):
            if self.copy_selection():
                return
            if self.selected:
                self.close_details()
            elif self.busy:
                self.task.cancel()
            else:
                self.editor.text = ""

        @keys.add("c-d")
        def exit_app(event):
            if self.busy:
                self.task.cancel()
            else:
                self.app.exit()

        status = Window(FormattedTextControl(self.status), height=1, style="class:muted")
        body = HSplit(
            [
                Window(
                    FormattedTextControl(self.header),
                    height=1,
                ),
                VSplit([Window(width=2), Window(self.transcript), Window(width=2)]),
                Window(
                    FormattedTextControl(self.composer_hint),
                    height=1,
                    style="class:muted",
                ),
                VSplit([Window(width=2), self.editor, Window(width=2)]),
                status,
            ]
        )
        popup = ConditionalContainer(
            Frame(Window(self.details), title=self.details_title),
            filter=Condition(lambda: self.selected is not None),
        )
        layout = FloatContainer(
            body, floats=[Float(content=popup, left=2, right=2, top=2, bottom=2)]
        )
        self.app = Application(
            layout=Layout(layout, focused_element=self.editor),
            key_bindings=keys,
            full_screen=True,
            mouse_support=Condition(lambda: not self.copy_mode),
            input=input,
            output=output,
            min_redraw_interval=0.016,
            refresh_interval=0.125,
            style=Style.from_dict(
                {
                    "heading": "bold",
                    "accent": "ansicyan bold",
                    "muted": "ansibrightblack",
                    "error": "ansired bold",
                    "warning": "ansiyellow",
                    "spinner": "ansimagenta bold",
                    "success": "ansigreen",
                    "key": "ansicyan bold",
                    "selection": "reverse",
                    "composer": "",
                    "frame.border": "ansibrightblack",
                    "frame.label": "bold",
                }
            ),
        )
        # Resolve standalone Esc promptly while leaving time for Alt+Enter sequences.
        self.app.ttimeoutlen = 0.1
        self.app.timeoutlen = 0.5

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def status(self):
        if self.copy_mode:
            return self.copy_status
        self.renderer.console.width = self.app.output.get_size().columns
        return self.renderer.toolbar(streaming=self.busy)

    def spinner(self):
        moment = self.copy_time if self.copy_mode else time.monotonic()
        return "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int(moment * 8) % 10]

    def toggle_copy(self):
        self.transcript.clear_selection()
        self.details.clear_selection()
        if not self.copy_mode:
            self.copy_status = self.status()
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
        # OSC 52 targets the user's terminal clipboard, including over SSH.
        payload = base64.b64encode(text.encode()).decode("ascii")
        self.app.output.write_raw(f"\x1b]52;c;{payload}\x07")
        self.app.output.flush()
        return True

    def latest_details(self):
        entry = next((e for e in reversed(self.entries) if e.expandable), None)
        self.open_details(entry or Entry("notice", "Details", "No tool or reasoning traces yet."))

    def header(self):
        width = self.app.output.get_size().columns
        session = safe_text(self.agent.session_id)[:8]
        metadata = f"  /  {self.renderer.model}" if self.renderer.model else ""
        metadata += f"  /  {session}"
        icon = self.spinner() if self.busy and not self.copy_mode else "✦"
        return [
            ("class:spinner", f" {icon}"),
            ("class:accent", " Echo"),
            ("class:muted", fit_text(metadata, width - 7)),
        ]

    def composer_hint(self):
        width = self.app.output.get_size().columns
        if self.copy_mode:
            hint = "Esc resume · Select text · Ctrl+Shift+C copy"
        elif (self.details if self.selected else self.transcript).selected_text():
            hint = "Ctrl-C copy selection · Esc clear · Alt+y native copy"
        elif self.selected:
            hint = "Esc close · Alt+y native copy · PgUp/PgDn scroll"
        elif not self.transcript.follow:
            hint = "History · Ctrl-End follows latest output"
        elif self.busy:
            hint = "Working · Ctrl-C cancel · Alt+d details · Alt+y copy"
        elif width < 40:
            hint = "Enter send · /copy"
        elif width < 65:
            hint = "Enter send · /copy · /help"
        else:
            hint = "Enter send · Alt+Enter newline · Alt+d details · Alt+y copy · F1 help"
        return key_highlights(f" ── {hint} ", width)

    def details_title(self):
        width = max(1, self.app.output.get_size().columns - 10)
        title = (
            "Esc resume · Select text · Ctrl+Shift+C copy"
            if self.copy_mode
            else "Trace details · Ctrl-C copy selection · Alt+y native copy · Esc close"
        )
        return key_highlights(title, width)

    def help_entry(self):
        return Entry(
            "notice",
            "Help · Esc close",
            "**Write**  Enter sends; Alt+Enter adds a line.\n\n"
            "**Inspect**  Click a reasoning or tool row, or use Alt+d, F2, or /details. "
            "Esc closes details.\n\n"
            "**Navigate**  Mouse wheel or PgUp/PgDn scrolls; Ctrl-End follows new output.\n\n"
            "**Select**  Drag across the transcript or details to highlight text. Ctrl-C "
            "requests copying through your terminal's OSC 52 clipboard support. "
            "Esc clears the selection.\n\n"
            "**Native copy**  If clipboard copying is unsupported, use /copy, Alt+y, or F3. "
            "This freezes the view and releases the mouse to your terminal. "
            "Drag to select, then use your terminal's copy shortcut (usually Ctrl+Shift+C "
            "on Linux or Cmd+C on macOS). F3 or Esc resumes live updates. "
            "In many terminals, Shift+drag also selects without entering copy mode.\n\n"
            "**Stop**  Ctrl-C cancels a running turn or clears the prompt. "
            "Ctrl-D exits when idle.\n\n"
            "**Commands**  /help · /diff · /status · /details · /copy · /exit",
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
                    parts = [str(value[k]) for k in ("error", "output", "findings") if value.get(k)]
                    entry.text = safe_text(
                        "\n\n".join(parts) if parts else json.dumps(value, indent=2)
                    )
                    failed = bool(value.get("error") or value.get("exit_code", 0))
                    entry.status = "Failed" if failed else "Done"
                    if value.get("exit_code"):
                        entry.status += f" · exit {value['exit_code']}"
                    entry.done = True
                    self.current.pop((actor, "tool"), None)
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

    async def submit(self, text):
        self.transcript.clear_selection()
        self.transcript.follow = True
        if text == "/exit":
            self.app.exit()
            return
        if text == "/help":
            self.open_details(self.help_entry())
            return
        if text == "/details":
            self.latest_details()
            return
        if text == "/copy":
            self.toggle_copy()
            return
        if text == "/status":
            reasoning_policy = (
                "Input includes saved reasoning traces sent back to the model. "
                if self.renderer.active.return_reasoning
                else "Input excludes saved reasoning traces; they are not sent back to the model. "
            )
            self.add(
                "notice",
                "Status",
                f"Session: {self.agent.session_id}\n\n"
                f"Workspace: {self.agent.sandbox.workspace}\n\n"
                f"{self.renderer.active_context_text()}\n\n"
                f"{self.renderer.active.generated_text(detailed=True)}\n\n"
                f"Input counts the latest request. {reasoning_policy}"
                "Gen counts generated thinking, answer, and tool-call tokens for that request. "
                "~ marks a character-based estimate until server usage arrives. "
                "Completed reasoning traces are saved locally in either mode.",
            )
            return
        if text == "/diff":
            try:
                patch = await asyncio.to_thread(self.agent.sandbox.diff)
                self.add(
                    "notice",
                    "Changes",
                    "```diff\n" + patch + "\n```" if patch.strip() else "No sandbox changes yet.",
                )
            except (RuntimeError, ValueError, OSError) as error:
                self.add("notice", "Error", str(error))
            return
        if text.startswith("/"):
            self.add("notice", "Unknown command", "Use /help.")
            return
        self.add("user", "You", text)
        self.renderer.start()
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
            self.renderer.stop(status)
            # Some adapters do not emit run_end; close any unfinished trace too.
            for actor in ("Echo", "Review"):
                self.on_event(
                    "child_run_end" if actor == "Review" else "run_end", {"status": status}
                )
            self.app.invalidate()

    async def run(self):
        self.renderer.event_handler = self.on_event
        try:
            await self.app.run_async()
        finally:
            if self.busy:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            self.renderer.event_handler = None
