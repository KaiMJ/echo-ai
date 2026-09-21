"""Terminal presentation; agent events stay independent of display refreshes."""

import time
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.markdown import Markdown
from rich.text import Text


def safe_text(value):
    """Do not interpret model/tool output as terminal control sequences."""
    return "".join(
        c for c in str(value) if c in "\n\t" or (ord(c) >= 32 and not 127 <= ord(c) <= 159)
    )


@dataclass
class Activity:
    label: str = "Echo"
    status: str = "Ready"
    task: str = ""
    text: str = ""
    reasoning: str = ""
    context: int | None = None
    capacity: int = 0
    estimated: bool = True
    generated_chars: int = 0
    tool_chars: dict = field(default_factory=dict)
    generated_tokens: int | None = None
    reasoning_tokens: int | None = None
    output_limit: int = 0
    requested: bool = False
    return_reasoning: bool = False

    def context_text(self, *, label="Input"):
        if self.context is None or not self.capacity:
            return f"{label}: awaiting first request"
        ratio = self.context / self.capacity
        prefix = "~" if self.estimated else ""
        return f"{label} [{prefix}{self.context:,} / {self.capacity:,}] {ratio:.0%}"

    def generated_text(self, *, detailed=False):
        if not self.requested:
            return "Generated: awaiting first request"
        count = self.generated_tokens
        estimated = count is None
        if estimated:
            count = (self.generated_chars + sum(self.tool_chars.values()) + 2) // 3
        value = f"{'~' if estimated else ''}{count:,}"
        if not detailed:
            return f"Gen {value}"
        limit = f" / {self.output_limit:,}" if self.output_limit else ""
        text = f"Generated this request: {value}{limit} tokens (thinking + answer + tool calls)"
        if self.reasoning_tokens is not None:
            text += f"; thinking: {self.reasoning_tokens:,} tokens"
        return text


class Renderer:
    def __init__(self, console: Console):
        self.console = console
        self.main = Activity()
        self.child: Activity | None = None
        self.live: Live | None = None
        self.started = 0.0
        self.elapsed = 0.0
        self.model = ""
        self.session = ""
        self.calls = self.tools = self.output_tokens = 0
        self.cost_usd = 0.0
        self.estimated_cost_calls = self.unknown_cost_calls = 0
        self.ttft: float | None = None
        self.remaining: int | None = None
        self.max_steps = 0
        self.plain = False
        self.event_handler = None

    def configure(self, agent, *, plain=False):
        self.cost_usd = 0.0
        self.estimated_cost_calls = self.unknown_cost_calls = 0
        self.main = Activity()
        self.child = None
        self.session = agent.session_id
        config = getattr(getattr(agent, "model", None), "config", None)
        if config:
            self.model = config.model.rsplit("/", 1)[-1]
            self.main.capacity = config.context_tokens
            self.main.return_reasoning = getattr(config, "return_reasoning", False)
        self.plain = plain

    def start(self):
        self.cost_usd = 0.0
        self.estimated_cost_calls = self.unknown_cost_calls = 0
        self.started = time.monotonic()
        self.elapsed = 0
        self.calls = self.tools = self.output_tokens = 0
        self.ttft = None
        self.remaining = None
        self.child = None
        self.main.status = "Waiting for model"
        self.main.text = ""
        self.main.reasoning = ""
        self.main.requested = False
        if (
            self.console.is_terminal
            and not self.console.is_dumb_terminal
            and not self.plain
            and self.event_handler is None
        ):
            self.live = Live(
                get_renderable=self.dashboard,
                console=self.console,
                refresh_per_second=1 / 0.15,
                transient=True,
            )
            self.live.start()

    def stop(self, status):
        self.main.status = status.capitalize()
        self.elapsed = time.monotonic() - self.started
        self.started = 0.0
        self.flush(self.main)
        if self.child:
            self.flush(self.child)
        if self.live:
            self.live.stop()
            self.live = None
        summary = f"{status.capitalize()} · {self.elapsed:.1f}s · {self.calls} model calls"
        summary += f" · {self.tools} tools · {self.output_tokens:,} output tokens"
        summary += " · " + self.cost_text()
        self.print(Text(summary, style="dim"))

    def cost_text(self):
        from echo_ai.runtime.pricing import format_cost

        summary = format_cost(self.cost_usd, estimated=bool(self.estimated_cost_calls))
        if self.unknown_cost_calls:
            summary += f" · {self.unknown_cost_calls} calls unpriced"
        return summary

    def flush(self, activity):
        if not activity.text and not activity.reasoning:
            return
        if self.live:
            self.print(Text(activity.label, style="bold cyan"))
            if activity.reasoning:
                self.print(Text(activity.reasoning, style="dim italic"))
            if activity.text:
                self.print(Markdown(activity.text))
        else:
            self.print()
        activity.reasoning = ""
        activity.text = ""

    def print(self, *args, **kwargs):
        if self.event_handler is None:
            self.console.print(*args, **kwargs)

    def emit(self, kind, value):
        self._emit(kind, value)
        if self.event_handler is not None:
            self.event_handler(kind, value)

    def _emit(self, kind, value):
        if kind == "child":
            self.flush(self.main)
            self.child = Activity(label=f"Review {safe_text(value)}", status="Starting")
            self.main.status = "Waiting for review"
            self.print(Text(f"\n{self.child.label} · read-only", style="cyan"))
            return
        if kind == "child_task":
            if self.child:
                self.child.task = safe_text(value)
                self.print(Text(f"  Task: {self.child.task}", style="dim"))
            return
        is_child = kind.startswith("child_")
        activity = self.child if is_child else self.main
        if activity is None:
            return
        if is_child:
            kind = kind.removeprefix("child_")
        prefix = f"{activity.label} · " if is_child else ""
        if kind == "reasoning":
            text = safe_text(value)
            activity.generated_chars += len(str(value))
            activity.requested = True
            activity.reasoning += text
            activity.status = "Thinking"
            if not self.live:
                self.print(text, end="", style="dim italic", markup=False)
        elif kind == "text":
            text = safe_text(value)
            activity.generated_chars += len(str(value))
            activity.requested = True
            if text and activity.reasoning and not activity.text and not self.live:
                self.print("\n")
            activity.text += text
            activity.status = "Responding"
            if not self.live:
                self.print(text, end="", markup=False)
        elif kind == "model_start":
            activity.status = "Waiting for model"
            activity.context = (value["context_chars"] + 2) // 3
            activity.return_reasoning = value.get("return_reasoning", False)
            activity.capacity = value["context_tokens"]
            activity.estimated = True
            activity.generated_chars = 0
            activity.tool_chars.clear()
            activity.generated_tokens = activity.reasoning_tokens = None
            activity.output_limit = value.get("max_tokens", 0)
            activity.requested = True
            self.remaining = value["remaining"]
            self.max_steps = value["max_steps"]
        elif kind == "input_rejected":
            activity.context = value["context_chars"] // 3
            activity.estimated = bool(activity.context)
            activity.requested = False
            activity.generated_tokens = activity.reasoning_tokens = None
        elif kind == "model_cost":
            cost = value.get("cost_usd")
            self.cost_usd += cost if cost is not None else 0
            self.estimated_cost_calls += value.get("cost_source") == "estimated"
            self.unknown_cost_calls += cost is None
        elif kind == "model_end":
            usage = value["usage"]
            activity.requested = True
            activity.generated_tokens = usage.get("completion_tokens")
            activity.reasoning_tokens = (usage.get("completion_tokens_details") or {}).get(
                "reasoning_tokens"
            )
            if "prompt_tokens" in usage:
                activity.context = usage["prompt_tokens"]
                activity.estimated = False
            self.calls += 1
            self.output_tokens += usage.get("completion_tokens", 0)
            self.ttft = usage.get("ttft")
            self.flush(activity)
        elif kind == "tool_call_delta":
            activity.requested = True
            activity.tool_chars[value["index"]] = len(value["name"]) + len(value["arguments"])
        elif kind == "tool_start":
            self.flush(activity)
            self.tools += 1
            activity.status = f"Running {safe_text(value)}"
            self.print(Text(f"\n{prefix}→ {safe_text(value)}", style="cyan"))
        elif kind == "tool_detail":
            args = value["args"]
            detail = args.get("command") or args.get("path") or args.get("pattern") or ""
            if detail:
                detail = safe_text(detail)[:240]
                activity.status = f"{safe_text(value['name'])} · {detail}"
                self.print(Text(f"  {detail}", style="dim"))
        elif kind == "tool_end":
            failed = bool(value.get("error") or value.get("exit_code", 0))
            activity.status = "Tool failed" if failed else "Tool completed"
            display = value.get("error") or value.get("output") or value.get("findings")
            display = safe_text(display if display is not None else value)
            if value.get("exit_code"):
                display = f"Exit {value['exit_code']}\n{display}"
            lines = display.splitlines()
            preview = "\n".join(lines[:6])[:1200]
            if len(preview) < len(display):
                preview += "\n… Full result saved in session"
            display = preview or "Done"
            self.print(Text(display, style="red" if failed else "dim"))
        elif kind == "run_end":
            activity.status = value["status"].capitalize()
            self.flush(activity)
            if is_child:
                style = "green" if value["status"] == "completed" else "yellow"
                self.print(Text(f"{prefix}{activity.status}", style=style))

    @property
    def active(self):
        if self.child and self.main.status == "Waiting for review":
            return self.child
        return self.main

    def active_context_text(self):
        label = "Review Input" if self.active is self.child else "Echo Input"
        return self.active.context_text(label=label)

    def dashboard(self):
        active = self.active
        elapsed = time.monotonic() - self.started if self.started else self.elapsed
        width = max(1, self.console.width)
        height = max(1, self.console.height)
        header = Text(no_wrap=True, overflow="ellipsis")
        header.append("Review" if active is self.child else "Echo", style="bold cyan")
        header.append(f" · {active.status.replace(chr(10), ' ')}", style="dim")
        rows = [header]
        if active is self.child and height >= 10:
            rows.append(
                Text(
                    f"Read-only subagent · {active.task.replace(chr(10), ' ')}",
                    style="dim",
                    no_wrap=True,
                    overflow="ellipsis",
                )
            )

        # Wrap before selecting the tail so the newest output always stays visible.
        # Stream literal text; render complete Markdown once it enters scrollback.
        source = active.text or active.reasoning
        body = Text(source[-8000:], style="" if active.text else "dim italic")
        wrapped = body.wrap(self.console, width) if source else []
        footer = []
        if height >= 10:
            footer.append(
                Text(
                    f"{elapsed:.1f}s · {self.calls} calls · {self.tools} tools"
                    f" · {self.output_tokens:,} output tokens",
                    style="dim",
                    no_wrap=True,
                    overflow="ellipsis",
                )
            )
        footer.append(Text(self.toolbar(streaming=True), style="reverse", no_wrap=True))
        # Reserve the final terminal row and keep status anchored above it while
        # Rich owns output. prompt_toolkit restores its toolbar when input resumes.
        target_height = max(1, height - 1)
        available = max(0, min(20, target_height - len(rows) - len(footer) - 2))
        if wrapped and available:
            rows.append(Text(""))
            rows.extend(wrapped[-available:])
            rows.append(Text(""))
        rows = rows[: max(0, target_height - len(footer))]
        rows.extend(Text("") for _ in range(target_height - len(rows) - len(footer)))
        rows.extend(footer)
        return Group(*rows[-target_height:])

    def toolbar(self, *, streaming=False):
        active = self.active
        context = self.active_context_text()
        hint = "Ctrl-C cancel" if streaming else "/help"
        status = active.status.replace("\n", " ")
        details = f"{context} · {status} · {hint}"
        tokens = context
        if active.requested:
            tokens += f" · {active.generated_text()}"
            details = f"{tokens} · {status} · {hint}"
        candidates = [
            f"{self.model} · {details}" if self.model else details,
            details,
            tokens,
            context,
        ]
        # Keep token counts ahead of model metadata when space is limited.
        if active.context is not None and active.capacity:
            prefix = "~" if active.estimated else ""
            candidates.append(f"In [{prefix}{active.context:,} / {active.capacity:,}]")
            candidates.append(f"[{prefix}{active.context:,} / {active.capacity:,}]")
        width = max(1, self.console.width - 2)
        for candidate in candidates:
            text = Text(candidate)
            if text.cell_len <= width:
                return f" {candidate} "
        text.truncate(width, overflow="ellipsis")
        return f" {text.plain} "
