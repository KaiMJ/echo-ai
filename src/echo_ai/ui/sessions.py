"""Compact session picker with keyboard navigation and clickable rows."""

from datetime import UTC, datetime

from prompt_toolkit.data_structures import Point
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.mouse_events import MouseButton, MouseEventType
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import Frame


def session_age(updated, now):
    if not updated:
        return ""
    timestamp = datetime.fromisoformat(updated)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    seconds = max(0, int((now - timestamp).total_seconds()))
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{seconds // 60} min ago"
    if seconds < 86400:
        return f"{seconds // 3600} hr ago"
    days = seconds // 86400
    return f"{days} {'day' if days == 1 else 'days'} ago"


class SessionPicker:
    def __init__(self, rows, current, choose, close, fit, size):
        self.rows, self.current = rows, current
        self.choose, self.close = choose, close
        self.fit, self.size = fit, size
        self.index = 0
        keys = KeyBindings()

        @keys.add("up")
        def up(event):
            self.move(-1)

        @keys.add("down")
        def down(event):
            self.move(1)

        @keys.add("pageup")
        def page_up(event):
            self.move(-self.height())

        @keys.add("pagedown")
        def page_down(event):
            self.move(self.height())

        @keys.add("home")
        def first(event):
            self.index = 0

        @keys.add("end")
        def last(event):
            self.index = len(self.rows) - 1

        @keys.add("enter")
        def select(event):
            self.choose(self.rows[self.index])

        @keys.add("escape", eager=True)
        def cancel(event):
            self.close()

        self.control = FormattedTextControl(
            self.text, focusable=True, key_bindings=keys,
            get_cursor_position=lambda: Point(x=0, y=self.index), show_cursor=False,
        )
        self.window = Window(self.control, height=self.height, wrap_lines=False)
        self.container = Frame(self.window, title="Sessions · ↑/↓ select · Enter resume · Esc close")

    def __pt_container__(self):
        return self.container

    def height(self):
        return max(1, min(len(self.rows), 12, self.size().rows - 6))

    def move(self, delta):
        self.index = max(0, min(len(self.rows) - 1, self.index + delta))

    def text(self):
        fragments = []
        width = max(1, self.size().columns - 8)
        now = datetime.now(UTC)
        for index, row in enumerate(self.rows):
            def click(event, index=index):
                if event.event_type == MouseEventType.MOUSE_UP and event.button == MouseButton.LEFT:
                    self.index = index
                    self.choose(self.rows[index])

            if index:
                fragments.append(("", "\n"))
            marker = "› " if index == self.index else "  "
            current = " · current" if row["id"] == self.current else ""
            age = session_age(row.get("updated"), now)
            metadata = f" · {age}" if age else ""
            label = f"{marker}{row['id'][:8]}{current}{metadata}  {row['title'] or 'New session'}"
            usage = row.get("usage", {})
            counts = [
                f"{name} {usage[key]:,}" if usage.get(key) is not None else f"{name} —"
                for name, key in (("In", "prompt_tokens"), ("Out", "completion_tokens"))
            ]
            tokens = " · ".join(counts)
            left_width = width - get_cwidth(tokens) - 2
            if left_width >= 12:
                label = self.fit(label, left_width)
                label += " " * (width - get_cwidth(label) - get_cwidth(tokens)) + tokens
            fragments.append((
                "class:selection" if index == self.index else "",
                self.fit(label, width), click,
            ))
        return fragments
