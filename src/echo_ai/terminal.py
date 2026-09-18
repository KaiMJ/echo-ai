"""Persistent interactive transcript; Rich formats Markdown, prompt_toolkit owns the screen."""

import asyncio
import json
from dataclasses import dataclass, field
from io import StringIO

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
    Window,
)
from prompt_toolkit.layout.controls import UIContent, UIControl
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.markdown import Markdown

from .ui import safe_text


@dataclass
class Entry:
    kind: str
    title: str
    text: str = ""
    detail: str = ""
    done: bool = False
    status: str = ""
    cache_key: tuple | None = None
    cache: list = field(default_factory=list)

    @property
    def expandable(self):
        return self.kind in {"reasoning", "tool"}

    def markdown_lines(self, width):
        source = self.detail + self.text
        key = (width, source)
        if key != self.cache_key:
            output = StringIO()
            console = Console(
                file=output,
                width=max(1, width),
                force_terminal=True,
                color_system="standard",
                highlight=False,
            )
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

    def is_focusable(self):
        return True

    def scroll(self, amount):
        self.follow = False
        self.offset = max(0, min(max(0, self.total - self.height), self.offset + amount))
        self.chat.app.invalidate()

    def create_content(self, width, height):
        rows = []
        entries = [self.chat.selected] if self.popup else self.chat.entries
        for entry in entries:
            if entry is None:
                continue
            if self.popup:
                title = f"{entry.title} · {entry.status}   [Close · Esc]"
            else:
                title = entry.title
                if entry.expandable:
                    title += f" · {entry.status or 'Streaming'} · [Open details]"
            rows.append(([("bold ansicyan", title)], entry if entry.expandable else None))
            if self.popup or not entry.expandable or not entry.done:
                lines = entry.markdown_lines(max(1, width - 1))
                if entry.expandable and not self.popup:
                    lines = lines[-6:]
                rows.extend((line, None) for line in lines)
            rows.append(([("", "")], None))
        self.total, self.height = len(rows), height
        maximum = max(0, len(rows) - height)
        self.offset = maximum if self.follow else min(self.offset, maximum)
        self.visible = rows[self.offset : self.offset + height]
        return UIContent(
            get_line=lambda i: self.visible[i][0],
            line_count=len(self.visible),
            show_cursor=False,
        )

    def mouse_handler(self, event):
        if event.event_type == MouseEventType.SCROLL_UP:
            self.scroll(-3)
        elif event.event_type == MouseEventType.SCROLL_DOWN:
            self.scroll(3)
        elif event.event_type == MouseEventType.MOUSE_UP:
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
        self.transcript = TranscriptControl(self)
        self.details = TranscriptControl(self, popup=True)
        self.editor = TextArea(
            prompt="echo › ",
            multiline=True,
            height=3,
            history=FileHistory(str(root / "input-history")),
            completer=WordCompleter(["/help", "/diff", "/status", "/exit"]),
            read_only=Condition(lambda: self.busy),
        )
        keys = KeyBindings()

        @keys.add("enter")
        def submit(event):
            if self.selected:
                self.close_details()
            elif not self.busy:
                text = self.editor.text.strip()
                if text:
                    self.editor.buffer.append_to_history()
                    self.editor.text = ""
                    self.task = self.app.create_background_task(self.submit(text))

        @keys.add("escape", "enter")
        def newline(event):
            if not self.busy and not self.selected:
                self.editor.buffer.insert_text("\n")

        @keys.add("escape")
        def close(event):
            self.close_details()

        @keys.add("f2")
        def latest(event):
            if self.selected:
                self.close_details()
            else:
                entry = next((e for e in reversed(self.entries) if e.expandable), None)
                if entry:
                    self.open_details(entry)

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
            control.follow = True

        @keys.add("c-c")
        def cancel(event):
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

        from prompt_toolkit.layout.controls import FormattedTextControl

        status = Window(FormattedTextControl(self.status), height=1, style="reverse")
        body = HSplit(
            [
                Window(
                    FormattedTextControl(
                        "Echo · Click traces for details · F2 latest · PgUp/PgDn scroll · Ctrl-End follow"
                    ),
                    height=1,
                    style="dim",
                ),
                Window(self.transcript),
                self.editor,
                status,
            ]
        )
        popup = ConditionalContainer(
            Frame(Window(self.details), title="Trace details"),
            filter=Condition(lambda: self.selected is not None),
        )
        layout = FloatContainer(
            body, floats=[Float(content=popup, left=2, right=2, top=2, bottom=2)]
        )
        self.app = Application(
            layout=Layout(layout, focused_element=self.editor),
            key_bindings=keys,
            full_screen=True,
            mouse_support=True,
            input=input,
            output=output,
            min_redraw_interval=0.1,
            refresh_interval=0.25,
            style=Style.from_dict({"dim": "ansibrightblack"}),
        )

    @property
    def busy(self):
        return self.task is not None and not self.task.done()

    def status(self):
        self.renderer.console.width = self.app.output.get_size().columns
        return self.renderer.toolbar(streaming=self.busy)

    def add(self, kind, title, text="", **kwargs):
        entry = Entry(kind, safe_text(title), safe_text(text), **kwargs)
        self.entries.append(entry)
        return entry

    def open_details(self, entry):
        self.selected = entry
        self.details.offset = 0
        self.details.follow = False
        self.app.layout.focus(self.details)
        self.app.invalidate()

    def close_details(self):
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
            entry.detail = "```json\n" + safe_text(value["arguments"]) + "\n```\n\n"
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
            self.current[(actor, "tool")] = entry
        elif kind in {"tool_detail", "tool_output", "tool_end"}:
            entry = self.current.get((actor, "tool"))
            if entry:
                if kind == "tool_detail":
                    args = value["args"]
                    summary = args.get("command") or args.get("path") or args.get("pattern")
                    entry.title = f"{actor} · {safe_text(value['name'])}"
                    if summary:
                        entry.title += " · " + safe_text(summary).replace("\n", " ")[:80]
                    entry.detail = (
                        "```json\n" + safe_text(json.dumps(value["args"], indent=2)) + "\n```\n\n"
                    )
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
        self.transcript.follow = True
        if text == "/exit":
            self.app.exit()
            return
        if text == "/help":
            self.add(
                "notice",
                "Help",
                "Enter sends; Alt+Enter adds a line. Ctrl-C cancels. "
                "Click a reasoning or tool row to open its Markdown trace; Esc closes it. "
                "F2 opens the latest trace. Scroll with the mouse or PgUp/PgDn; "
                "Ctrl-End follows new output. /diff · /status · /exit",
            )
            return
        if text == "/status":
            self.add(
                "notice",
                "Status",
                f"Session: {self.agent.session_id}\n\n"
                f"Workspace: {self.agent.sandbox.workspace}\n\n"
                f"{self.renderer.active_context_text()}",
            )
            return
        if text == "/diff":
            try:
                patch = await asyncio.to_thread(self.agent.sandbox.diff)
                self.add("notice", "Changes", "```diff\n" + patch + "\n```")
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
