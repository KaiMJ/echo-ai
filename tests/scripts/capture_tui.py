"""Render a deterministic, synthetic Echo session through the real TUI.

Usage: uv run python tests/scripts/capture_tui.py --output /tmp/echo.ansi
The output is a VT screen capture for a terminal renderer, not a model run.
"""

import argparse
import asyncio
import os
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import ColorDepth
from prompt_toolkit.output.vt100 import Vt100_Output
from rich.console import Console

from echo_ai.ui.renderer import Renderer
from echo_ai.ui.terminal import TerminalChat


async def capture(args):
    with TemporaryDirectory() as directory, create_pipe_input() as pipe:
        root = Path(directory)
        config = root / "echo.yaml"
        config.write_text(f"theme:\n  preset: {args.theme}\n")
        env = root / ".env"
        env.write_text("")
        # Captures never load real credentials, history, or model configuration.
        os.environ["ECHO_CONFIG_FILE"] = str(config)
        os.environ["ECHO_ENV_FILE"] = str(env)
        stream = StringIO()
        output = Vt100_Output(
            stream, lambda: Size(rows=28, columns=100), term="xterm-256color",
            default_color_depth=ColorDepth.TRUE_COLOR, enable_cpr=False,
        )
        renderer = Renderer(Console(file=StringIO(), width=100))
        renderer.model = "Qwen / local"
        agent = SimpleNamespace(session_id="demo-session", sandbox=SimpleNamespace(workspace=root))
        chat = TerminalChat(agent, root, renderer, input=pipe, output=output)
        if args.scenario == "session":
            chat.add("user", "You", "Where are sessions stored, and how do I resume one?")
            chat.add("tool", "Echo · read · src/echo_ai/runtime/store.py", done=True, status="Done", tool="read")
            chat.add("text", "Echo", "Sessions are saved in a **local SQLite database**.\n\n"
                     "Browse this repository’s history with `/sessions`,\n"
                     "or resume a conversation from your terminal:\n\n"
                     "`uv run echo-ai resume <ID>`\n\n"
                     "Your conversation and its recorded edits stay together.")
            renderer.main.context, renderer.main.capacity = 2841, 262144
            renderer.main.status = "Completed"
        task = asyncio.create_task(chat.app.run_async())
        try:
            async with asyncio.timeout(5):
                while chat.editor.window.render_info is None:
                    await asyncio.sleep(0.01)
            args.output.write_text(stream.getvalue())
        finally:
            chat.app.exit()
            await task
        print(f"Captured {args.theme}/{args.scenario} at 100 × 28 cells: {args.output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--theme", choices=["dark", "light"], default="dark")
    parser.add_argument("--scenario", choices=["welcome", "session"], default="session")
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(capture(parser.parse_args()))
