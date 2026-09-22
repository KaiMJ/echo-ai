"""Shared command descriptions for full-screen and plain chat."""

from prompt_toolkit.completion import Completer, Completion
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from echo_ai.config.theme import Theme

NEW_SESSION = object()


class CommandCompleter(Completer):
    """Offer commands only when the entire prompt starts with a slash."""

    def get_completions(self, document, complete_event):
        prefix = document.text_before_cursor
        if not prefix.startswith("/") or "\n" in prefix:
            return
        for command, description in COMMANDS.items():
            if command.startswith(prefix):
                yield Completion(command, start_position=-len(prefix), display_meta=description)


COMMANDS = {
    "/help": "List commands",
    "/new": "Start a fresh session in this repository",
    "/status": "Show session, execution mode, and token usage",
    "/model": "Choose model, reasoning, and default settings",
    "/yolo": "Allow tools without asking until /default or exit",
    "/default": "Ask before bash, write, and edit calls",
    "/sessions": "List sessions for this repository",
    "/sessions ID": "Switch to a session (short IDs or latest accepted)",
    "/diff": "Show changes from agent edit and write tools",
    "/undo": "Undo the latest completed turn and its file changes",
    "/redo": "Redo the last undone turn",
    "/apply": "Apply sandbox agent edits to the source checkout",
    "/exit": "Save and exit",
}


def help_text():
    return "\n".join(f"{name:20} {description}" for name, description in COMMANDS.items())


def sessions_text(store, repo=None, *, include_children=False):
    rows = store.sessions(repo, include_children=include_children)
    if not rows:
        return "No sessions found."
    return "\n".join(
        f"{s['id']}  {s['title'] or '(new session)'}\n"
        f"  {s['updated']} UTC · {s['turns']} turns · {s['mode']}"
        f"{' · review' if s['parent_id'] else ''} · {s['repo'] or s['workspace']}"
        for s in reversed(rows)
    )


def sessions_panel(store, repo=None, *, current=None, include_children=False, theme=None):
    rows = store.sessions(repo, include_children=include_children)
    return session_rows_panel(list(reversed(rows)), current=current, theme=theme)


def session_rows_panel(rows, *, current=None, theme=None, clickable=False):
    theme = theme or Theme()
    table = Table(show_header=False, show_lines=True, expand=True, border_style=theme.muted)
    table.add_column(ratio=1, overflow="fold")
    for session in rows:
        text = Text(session["title"] or "New session", style="bold")
        if session["id"] == current:
            text.append("  • current", style=f"bold {theme.success}")
        text.append("\n" + session["id"], style=theme.accent)
        text.append(
            f"  ·  {session['mode']}  ·  {session['turns']} turns"
            + ("  ·  review" if session["parent_id"] else ""),
            style=theme.warning,
        )
        text.append(f"\nUpdated {session['updated']} UTC", style="dim")
        text.append("\n" + str(session["repo"] or session["workspace"]), style="dim")
        table.add_row(text)
    return Panel(
        table if rows else Text("No sessions found.", style="dim"),
        title="Sessions",
        subtitle="Click to resume · /sessions ID to switch" if clickable else "/sessions ID to switch",
        border_style=theme.accent,
    )


def status_rows(agent, renderer):
    rows = [
        ("Session", agent.session_id),
        ("Mode", getattr(agent.sandbox, "mode", "sandbox")),
        ("Permissions", "YOLO" if agent.permissions.yolo else "Default"),
        ("Workspace", str(agent.sandbox.workspace)),
        ("Context", renderer.active_context_text()),
        ("Generation", renderer.active.generated_text(detailed=True)),
    ]
    config = getattr(getattr(agent, "model", None), "config", None)
    if config is not None:
        rows.insert(1, ("Model", f"{config.provider}/{config.model}"))
        rows.insert(2, ("Reasoning", config.reasoning_effort or (
            "default" if config.reasoning_enabled else "off"
        )))
    if hasattr(agent, "store") and hasattr(agent.store, "session_cost"):
        total, estimated, unknown = agent.store.session_cost(agent.session_id)
        from echo_ai.runtime.pricing import format_cost

        detail = format_cost(total, estimated=bool(estimated))
        if estimated:
            detail += f"; {estimated} estimated calls"
        if unknown:
            detail += f"; {unknown} calls with unknown cost"
        rows.append(("Session API cost", detail))
    return rows


def status_text(agent, renderer):
    return "\n".join(f"{label}: {value}" for label, value in status_rows(agent, renderer))


def status_panel(agent, renderer, *, theme=None):
    theme = theme or Theme()
    table = Table.grid(padding=(0, 2), expand=True)
    table.add_column(style=f"bold {theme.accent}", no_wrap=True)
    table.add_column(ratio=1, overflow="fold")
    for label, value in status_rows(agent, renderer):
        table.add_row(label, Text(value))
    return Panel(table, title="Session status", border_style=theme.muted, padding=(1, 2))
