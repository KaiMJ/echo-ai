"""Terminal interface and batch commands."""

import argparse
import asyncio
import json
import os
import signal
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console

from .agent import Agent
from .config import Config, state_dir
from .model import Model
from .store import Store, workspace_lock
from .ui import Renderer, plain_requested, safe_text

console = Console(highlight=False)


renderer = Renderer(console)
render = renderer.emit


def make_prompt(root, **kwargs):
    keys = KeyBindings()

    @keys.add("escape", "enter")
    def newline(event):
        event.current_buffer.insert_text("\n")

    return PromptSession(
        history=FileHistory(str(root / "input-history")),
        key_bindings=keys,
        completer=WordCompleter(["/help", "/diff", "/status", "/exit"]),
        **kwargs,
    )


async def run_turn(agent, prompt):
    task = asyncio.create_task(agent.run(prompt))
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, task.cancel)
    status = "failed"
    renderer.start()
    try:
        result = await task
        status = result.get("status", "completed")
        console.print()
        return result
    except asyncio.CancelledError:
        status = "cancelled"
        console.print("\nCancelled. Inspect /diff before retrying.", style="yellow")
        return {"status": "cancelled"}
    except (RuntimeError, ValueError, OSError, httpx.HTTPError) as error:
        console.print(f"\nError: {safe_text(error)}", style="red", markup=False)
        return {"status": "failed", "error": str(error)}
    finally:
        renderer.stop(status)
        loop.remove_signal_handler(signal.SIGINT)


async def chat(agent, root):
    if console.is_terminal and not renderer.plain and not console.is_dumb_terminal:
        from .terminal import TerminalChat

        await TerminalChat(agent, root, renderer).run()
        return
    prompt_options = {}
    if console.is_terminal and not renderer.plain and not console.is_dumb_terminal:
        prompt_options["bottom_toolbar"] = renderer.toolbar
    prompt = make_prompt(root, **prompt_options)
    console.print("Enter sends · Alt+Enter adds a line · Ctrl-C cancels · Ctrl-D exits")
    console.print("/help  /diff  /status  /exit", style="dim")
    while True:
        try:
            text = (await prompt.prompt_async("echo › ")).strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            continue
        if not text:
            continue
        if text == "/exit":
            break
        if text == "/help":
            console.print(
                "Describe a coding task. Changes stay in the disposable workspace.\n"
                "/diff shows changes; /status shows session; /exit saves and exits.\n"
                "Resume later with: echo-ai resume SESSION"
            )
        elif text == "/diff":
            console.print(safe_text(await asyncio.to_thread(agent.sandbox.diff)), markup=False)
        elif text == "/status":
            console.print(
                f"Session: {agent.session_id}\nWorkspace: {agent.sandbox.workspace}\n"
                f"{renderer.main.context_text()}",
                markup=False,
            )
        elif text.startswith("/"):
            console.print("Unknown command. Use /help.", style="yellow")
        else:
            await run_turn(agent, text)


async def doctor(config):
    checks = []
    result = await asyncio.to_thread(
        subprocess.run, ["docker", "info"], capture_output=True, text=True
    )
    checks.append(("Docker daemon", result.returncode == 0))
    result = await asyncio.to_thread(
        subprocess.run,
        ["docker", "image", "inspect", "echo-ai-sandbox:local"],
        capture_output=True,
        text=True,
    )
    checks.append(("Sandbox image", result.returncode == 0))
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                config.base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {os.getenv('ECHO_API_KEY', 'local')}"},
            )
            response.raise_for_status()
            entries = response.json()["data"]
            models = [item["id"] for item in entries]
            checks.append((f"Model {config.model}", config.model in models))
            served = next((item for item in entries if item["id"] == config.model), {})
            limit = served.get("max_model_len")
            if isinstance(limit, int):
                checks.append(
                    (
                        f"Context: client {config.context_tokens}, server {limit} tokens",
                        config.context_tokens <= limit,
                    )
                )
    except (httpx.HTTPError, ValueError, KeyError):
        checks.append((f"vLLM at {config.base_url}", False))
    for label, good in checks:
        console.print(f"{'OK' if good else 'FAIL'}  {label}", markup=False)
    return 0 if all(good for _, good in checks) else 1


async def execute(args):
    from .sandbox import Sandbox

    config = Config.from_env()
    if args.command == "config":
        console.print_json(data={**asdict(config), "context_char_limit": config.context_char_limit})
        return 0
    root = state_dir()
    if args.command == "doctor":
        return await doctor(config)
    if args.command == "bench":
        from .benchmark import benchmark

        return await benchmark(config, root, args)
    store = Store(root / "sessions.sqlite3")
    sandbox = None
    locks = ExitStack()
    child = False
    try:
        if args.command == "sessions":
            for session in store.sessions():
                console.print(
                    f"{session['id']}  {session['created']}  "
                    f"{'child' if session['parent_id'] else 'main'}  {session['workspace']}",
                    markup=False,
                )
            return 0
        if args.command in ("resume", "diff"):
            session = store.session(args.session)
            sandbox = await asyncio.to_thread(Sandbox.resume, Path(session["workspace"]))
            config = Config.from_session(json.loads(session["config"]))
            key = args.session
            child = session["parent_id"] is not None
        else:
            sandbox = await asyncio.to_thread(Sandbox.create, Path(args.repo).resolve(), root)
            key = store.create(sandbox.workspace, asdict(config))
        locks.enter_context(workspace_lock(sandbox.workspace))
        if args.command == "diff":
            patch = await asyncio.to_thread(sandbox.diff)
            if getattr(args, "output", None):
                args.output.write_text(patch)
                console.print(f"Patch saved: {args.output}", markup=False)
            else:
                print(safe_text(patch))
            return 0
        agent = Agent(Model(config), store, sandbox, key, render, child=child)
        renderer.configure(agent, plain=plain_requested(args))
        console.print(f"Session: {key}", style="bold", markup=False)
        console.print(f"Workspace: {sandbox.workspace}", style="dim", markup=False)
        if args.command == "run":
            result = await run_turn(agent, args.task)
            console.print(f"Inspect changes: echo-ai diff {key}", style="dim")
            return 0 if result["status"] == "completed" else 1
        await chat(agent, root)
        return 0
    finally:
        try:
            if sandbox is not None:
                await sandbox.close()
        finally:
            locks.close()
            store.close()


def main():
    parser = argparse.ArgumentParser(description="Local coding agent with isolated Docker tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("chat", "run"):
        p = sub.add_parser(command)
        p.add_argument("--repo", default=".")
        p.add_argument("--plain", action="store_true", help="Disable live terminal rendering")
        if command == "run":
            p.add_argument("task")
    for command in ("resume", "diff"):
        p = sub.add_parser(command)
        p.add_argument("session")
        if command == "resume":
            p.add_argument("--plain", action="store_true", help="Disable live terminal rendering")
        if command == "diff":
            p.add_argument(
                "--output", type=Path, help="Save an unmodified patch for review/application"
            )
    sub.add_parser("sessions")
    sub.add_parser("doctor")
    sub.add_parser("config", help="Show effective settings for new sessions")
    p = sub.add_parser("bench")
    p.add_argument("--attempts", type=int, default=1)
    p.add_argument("--output", type=Path, default=Path("benchmark-results.json"))
    try:
        code = asyncio.run(execute(parser.parse_args()))
    except (RuntimeError, ValueError, OSError, httpx.HTTPError) as error:
        console.print(f"Error: {safe_text(error)}", style="red", markup=False)
        code = 1
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
