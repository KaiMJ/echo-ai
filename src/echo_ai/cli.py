"""Terminal interface and batch commands."""

import argparse
import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
from contextlib import ExitStack
from dataclasses import asdict, replace
from pathlib import Path

import httpx
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.prompt import Confirm

from echo_ai.config import Config, load_theme, state_dir
from echo_ai.config.file import config_path, environment_path
from echo_ai.runtime.agent import Agent
from echo_ai.runtime.locking import WorkspaceBusy
from echo_ai.runtime.model import Model
from echo_ai.runtime.permissions import Permissions
from echo_ai.runtime.revisions import apply_sandbox, move_turn
from echo_ai.runtime.store import Store, workspace_lock
from echo_ai.ui.commands import (
    NEW_SESSION,
    CommandCompleter,
    help_text,
    sessions_panel,
    status_panel,
)
from echo_ai.ui.renderer import Renderer, safe_text
from echo_ai.workspace.revisions import recover_restore

console = Console(highlight=False)


renderer = Renderer(console)
render = renderer.emit


def make_prompt(root, **kwargs):
    keys = KeyBindings()

    @keys.add("c-j")
    def newline(event):
        event.current_buffer.insert_text("\n")

    @keys.add("s-tab")
    def toggle_mode(event):
        permissions = getattr(event.app, "echo_permissions", None)
        if permissions is not None:
            permissions.yolo = not permissions.yolo
            console.print(f"Mode: {'YOLO' if permissions.yolo else 'Default'}", style="bold red" if permissions.yolo else "bold green")

    return PromptSession(
        history=FileHistory(str(root / "input-history")),
        key_bindings=keys,
        completer=CommandCompleter(),
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
    if not hasattr(agent, "permissions"):
        agent.permissions = Permissions()
    if console.is_terminal and not renderer.plain and not console.is_dumb_terminal:
        from echo_ai.ui.terminal import TerminalChat

        return await TerminalChat(agent, root, renderer).run()
    prompt_options = {}
    if console.is_terminal and not renderer.plain and not console.is_dumb_terminal:
        prompt_options["bottom_toolbar"] = renderer.toolbar
    prompt = make_prompt(root, **prompt_options)
    if hasattr(prompt, "app"):
        prompt.app.echo_permissions = agent.permissions

    async def ask_permission(name, args, rule):
        target = args.get("command") or args.get("path") or ""
        console.print(f"Permission · {name}: {target}", style="bold yellow", markup=False)
        choices = "[y] Allow once  [n] Deny  [t] Tell Echo" + (f"  [a] Allow ({rule}) for this session" if rule else "")
        console.print(choices, style="yellow", markup=False)
        while True:
            answer = (await prompt.prompt_async("Choice › ")).strip().lower()
            if answer in {"y", "a", "n", "t"}:
                if answer == "a" and not rule:
                    continue
                if answer == "t":
                    return "deny", (await prompt.prompt_async("Tell Echo › ")).strip()
                return {"y": "once", "a": "session", "n": "deny"}[answer], ""

    agent.permissions.ask = ask_permission
    console.print("Enter sends · Ctrl+J adds a line · Ctrl-C cancels · Ctrl-D exits")
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
        if text in {"/yolo", "/default"}:
            agent.permissions.yolo = text == "/yolo"
            console.print(f"Mode: {'YOLO' if agent.permissions.yolo else 'Default'}", style="bold red" if agent.permissions.yolo else "bold green")
            continue
        if text == "/new":
            return NEW_SESSION
        if text == "/help":
            console.print(help_text(), markup=False)
        elif text == "/sessions":
            session = agent.store.session(agent.session_id)
            console.print(
                sessions_panel(
                    agent.store, session["repo"], current=agent.session_id, theme=load_theme()
                )
            )
        elif text.startswith("/sessions "):
            try:
                session = agent.store.session(agent.session_id)
                target = agent.store.resolve(text.split(maxsplit=1)[1], session["repo"])
                console.print(f"Resume {target['title'] or 'New session'} · {target['id']}?", markup=False)
                while True:
                    try:
                        answer = (await prompt.prompt_async("Resume? [Y/N] › ")).strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        break
                    if answer in {"y", "yes"}:
                        return target["id"]
                    if answer in {"n", "no"}:
                        break
                    console.print("Enter Y to resume or N to cancel.")
            except ValueError as error:
                console.print(str(error), markup=False)
        elif text == "/diff":
            try:
                patch = "\n".join(
                    item["patch"] for item in agent.store.active_tool_changes(agent.session_id)
                    if item["patch"]
                )
                console.print(safe_text(patch or "No changes yet."), markup=False)
            except (RuntimeError, ValueError, OSError) as error:
                console.print(str(error), markup=False)
        elif text in {"/undo", "/undo force", "/redo", "/redo force"}:
            try:
                action, *options = text[1:].split()
                paths = await move_turn(agent, action, force=bool(options))
                console.print(
                    f"Conversation branch switched. Files changed: {', '.join(paths) or '(none)'}."
                )
            except (RuntimeError, ValueError, OSError) as error:
                console.print(str(error), markup=False)
        elif text in {"/apply", "/apply force"}:
            try:
                paths = await apply_sandbox(agent, force=text.endswith(" force"))
                console.print(f"Applied sandbox changes: {', '.join(paths) or '(none)'}")
            except (RuntimeError, ValueError, OSError) as error:
                console.print(str(error), markup=False)
        elif text == "/status":
            console.print(status_panel(agent, renderer, theme=load_theme()))
        elif text.startswith("/"):
            console.print("Unknown command. Use /help.", style="yellow")
        else:
            await run_turn(agent, text)


async def status(config, *, sandbox=False):
    checks = []
    if sandbox:
        for label, command in (
            ("Docker daemon", ["docker", "info"]),
            ("Sandbox image", ["docker", "image", "inspect", config.sandbox_image]),
        ):
            try:
                result = await asyncio.to_thread(
                    subprocess.run, command, capture_output=True, text=True
                )
                checks.append((label, result.returncode == 0))
            except OSError:
                checks.append((label, False))
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                config.base_url.rstrip("/") + "/models",
                headers={"Authorization": f"Bearer {os.getenv(config.api_key_env, 'local')}"},
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
        checks.append(("Model endpoint (check base_url and credentials with echo-ai setup --edit)", False))
    for label, good in checks:
        console.print(f"{'OK' if good else 'FAIL'}  {label}", markup=False)
    return 0 if all(good for _, good in checks) else 1


def session_lock(sandbox, root):
    if sandbox.mode == "sandbox":
        return workspace_lock(sandbox.workspace)
    locks = root / "locks"
    locks.mkdir(exist_ok=True)
    name = hashlib.sha256(os.fsencode(sandbox.workspace)).hexdigest()
    return workspace_lock(sandbox.workspace, locks / (name + ".lock"))


async def acquire_session_lock(locks, sandbox, root, *, interactive, handed_off, timeout=10):
    try:
        lease = locks.enter_context(session_lock(sandbox, root))
    except WorkspaceBusy as busy:
        if not interactive or not sys.stdin.isatty():
            raise
        if not busy.owner:
            raise RuntimeError(
                "This workspace is held by an older or unidentified process. "
                "Close that Echo process manually, then resume."
            ) from busy
        if not Confirm.ask(
            f"Echo process {busy.owner['pid']} has this workspace open. "
            "Close the other process and continue here?",
            default=False,
            console=console,
        ):
            raise RuntimeError("Session left open in the other Echo process.") from busy
        try:
            lease = locks.enter_context(session_lock(sandbox, root))
        except WorkspaceBusy as current:
            if current.owner != busy.owner:
                raise RuntimeError("Workspace owner changed. Try resuming again.") from current
            request = busy.request_close()
            console.print("Waiting for the other Echo process to close…", style="dim")
            try:
                deadline = asyncio.get_running_loop().time() + timeout
                while True:
                    try:
                        lease = locks.enter_context(session_lock(sandbox, root))
                        break
                    except WorkspaceBusy as current:
                        if current.owner != busy.owner:
                            raise RuntimeError(
                                "Workspace owner changed. Try resuming again."
                            ) from current
                        if asyncio.get_running_loop().time() >= deadline:
                            raise RuntimeError(
                                "The other Echo process did not close in time. "
                                "Close it manually, then resume."
                            ) from current
                        await asyncio.sleep(0.1)
            finally:
                request.remove_request()

    owner_task = asyncio.current_task()

    async def watch_handoff():
        while True:
            await asyncio.sleep(0.1)
            if lease.close_requested():
                handed_off.set()
                owner_task.cancel()
                return

    watcher = asyncio.create_task(watch_handoff())
    locks.callback(watcher.cancel)


async def execute(args):
    from echo_ai.workspace.local import LocalWorkspace
    from echo_ai.workspace.sandbox import Sandbox

    if args.command == "setup":
        from echo_ai.config.setup import setup

        path, saved = setup(edit=args.edit, reset=args.reset, path=args.path)
        console.print(f"Configuration: {path}", markup=False)
        if saved:
            console.print(f"Backup: {saved}", markup=False)
        console.print("Edit with echo-ai setup --edit; check the connection with echo-ai status.")
        console.print("Setup preserves existing settings. No credentials were copied.")
        if config_path().absolute() != path.absolute():
            console.print(f"Runtime configuration override: {config_path().absolute()}", markup=False)
        return 0
    config = Config.from_env()
    if getattr(args, "sandbox_image", None):
        if not getattr(args, "sandbox", False):
            raise ValueError("--sandbox-image requires --sandbox")
        config = replace(config, sandbox_image=args.sandbox_image)
    if args.command == "config":
        path = config_path().resolve()
        console.print(f"Config file: {path}", markup=False)
        console.print(f"Credential file: {environment_path().resolve()} (contents hidden)", markup=False)
        console.print("YAML: explicit path > project echo.yaml > global echo.yaml > defaults; no merging.")
        console.print("Shell variables override the selected credential file; both override YAML.")
        overrides = sorted(name for name in os.environ if name.startswith("ECHO_"))
        console.print(f"Environment override names: {', '.join(overrides) or '(none)'}", markup=False)
        console.print("Resumed sessions retain runtime settings; theme uses the current YAML.")
        values = asdict(config)
        # URLs may contain embedded passwords or query tokens. Do not print them.
        values["base_url"] = "(configured; hidden)" if config.base_url else "(provider default)"
        secret = os.getenv(config.api_key_env)
        if secret:
            values = {
                key: value.replace(secret, "[redacted]") if isinstance(value, str) else value
                for key, value in values.items()
            }
        console.print_json(
            data={
                **values,
                "context_char_limit": config.context_char_limit,
                "theme": asdict(load_theme()),
            }
        )
        return 0
    if args.command == "status":
        return await status(config, sandbox=args.sandbox)
    root = state_dir()
    store = Store(root / "sessions.sqlite3")
    sandbox = None
    locks = ExitStack()
    handed_off = asyncio.Event()
    interactive = args.command in {"chat", "resume"}
    try:
        if args.command == "sessions":
            console.print(
                sessions_panel(
                    store,
                    None if args.all else Path(args.repo).resolve(),
                    include_children=args.all,
                    theme=load_theme(),
                ),
            )
            return 0
        pointer = getattr(args, "session", None) or getattr(args, "resume", None)
        if pointer and (getattr(args, "sandbox", False) or getattr(args, "sandbox_image", None)):
            raise ValueError("Resumed sessions keep their saved mode and image; omit --sandbox and --sandbox-image.")
        repo = Path(getattr(args, "repo", ".")).resolve()
        checkout = await asyncio.to_thread(LocalWorkspace(repo, root, config).checkout_id)
        use_sandbox = getattr(args, "sandbox", False)
        fallback = None
        while True:
            if pointer:
                try:
                    session = store.resolve(pointer, repo)
                    config = Config.from_session(json.loads(session["config"]))
                    if session["mode"] == "local":
                        sandbox = LocalWorkspace.resume(
                            Path(session["workspace"]), session["state_path"], config
                        )
                    else:
                        sandbox = Sandbox.resume(Path(session["workspace"]), config)
                    key = session["id"]
                    child = session["parent_id"] is not None
                    await acquire_session_lock(
                        locks, sandbox, root, interactive=interactive, handed_off=handed_off
                    )
                    await asyncio.to_thread(recover_restore, sandbox, store.active_head(key))
                except (RuntimeError, ValueError, OSError) as error:
                    if fallback is None:
                        raise
                    console.print(f"Cannot switch sessions: {error}", markup=False)
                    if sandbox is not None:
                        await sandbox.close()
                        sandbox = None
                    locks.close()
                    pointer, fallback = fallback, None
                    continue
            else:
                backend = Sandbox if use_sandbox else LocalWorkspace
                reused = False
                if interactive:
                    for candidate in store.empty_sessions(repo, backend.mode):
                        if candidate["checkout"] and candidate["checkout"] != checkout:
                            continue
                        try:
                            if backend is LocalWorkspace:
                                sandbox = backend.resume(
                                    Path(candidate["workspace"]), candidate["state_path"], config
                                )
                            else:
                                sandbox = backend.resume(Path(candidate["workspace"]), config)
                            # Do not interrupt another process merely to reuse its empty session.
                            await acquire_session_lock(
                                locks, sandbox, root, interactive=False, handed_off=handed_off
                            )
                            if store.prepare_empty(candidate["id"], asdict(config)):
                                key, reused = candidate["id"], True
                                break
                        except (WorkspaceBusy, ValueError, OSError):
                            pass
                        if sandbox is not None:
                            await sandbox.close()
                            sandbox = None
                        locks.close()
                # Lock the checkout before taking the initial local snapshot.
                if not reused and backend is LocalWorkspace:
                    await acquire_session_lock(
                        locks,
                        LocalWorkspace(repo, root, config),
                        root,
                        interactive=interactive,
                        handed_off=handed_off,
                    )
                if not reused:
                    sandbox = await asyncio.to_thread(backend.create, repo, root, config)
                if not reused and backend is Sandbox:
                    await acquire_session_lock(
                        locks, sandbox, root, interactive=interactive, handed_off=handed_off
                    )
                if not reused:
                    key = store.create(
                        sandbox.workspace,
                        asdict(config),
                        repo=repo,
                        mode=sandbox.mode,
                        state_path=getattr(sandbox, "state_path", None),
                        checkout=checkout,
                    )
                child = False
            if args.command == "diff":
                patch = "\n".join(
                    item["patch"] for item in store.active_tool_changes(key) if item["patch"]
                )
                if args.output:
                    args.output.write_text(patch)
                    console.print(f"Change history saved: {args.output}", markup=False)
                else:
                    print(safe_text(patch))
                return 0
            agent = Agent(Model(config), store, sandbox, key, render, child=child)
            agent.permissions.yolo = getattr(args, "yolo", False)
            renderer.configure(agent, plain=console.is_dumb_terminal or not console.is_terminal)
            console.print(f"Session: {key} · {sandbox.mode}", style="bold", markup=False)
            console.print(f"Workspace: {sandbox.workspace}", style="dim", markup=False)
            if args.command == "run":
                result = await run_turn(agent, args.task)
                console.print(f"Inspect changes: echo-ai diff {key}", style="dim")
                return 0 if result["status"] == "completed" and not agent.permissions.blocked else 1
            fallback = key
            pointer = await chat(agent, root)
            if pointer is NEW_SESSION:
                current = store.session(key)
                repo = Path(current["repo"] or current["workspace"]).resolve()
                use_sandbox = current["mode"] == "sandbox"
            await sandbox.close()
            sandbox = None
            locks.close()
            if pointer is NEW_SESSION:
                pointer, fallback = None, None
                config = Config.from_env()
                continue
            if not pointer:
                return 0
    except asyncio.CancelledError:
        if not handed_off.is_set():
            raise
        console.print("Session closed for handoff to another Echo process.", style="dim")
        return 0
    finally:
        try:
            if sandbox is not None:
                await sandbox.close()
        finally:
            locks.close()
            store.close()


class CommandParser(argparse.ArgumentParser):
    def parse_args(self, args=None, namespace=None):
        args = list(sys.argv[1:] if args is None else args)
        if not args or (args[0].startswith("-") and args[0] not in {"-h", "--help"}):
            args.insert(0, "chat")
        return super().parse_args(args, namespace)

    def format_help(self):
        text = super().format_help()
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                text += "\nCommand options:\n"
                seen = set()
                for name, parser in action.choices.items():
                    if id(parser) in seen:
                        continue
                    seen.add(id(parser))
                    text += f"  {name}\n"
                    for option in parser._actions:
                        if option.dest == "help":
                            continue
                        label = parser._get_formatter()._format_action_invocation(option)
                        text += f"    {label:24} {option.help or ''}\n"
        return text


def build_parser():
    parser = CommandParser(description="Local coding agent. Edits your checkout by default.")
    sub = parser.add_subparsers(dest="command", required=True)
    for command, help_ in (
        ("chat", "Start an interactive conversation"),
        ("run", "Execute one task and exit (for scripts)"),
    ):
        p = sub.add_parser(command, help=help_)
        p.add_argument("--repo", default=".", help="Repository path (default: current directory)")
        p.add_argument("--sandbox", action="store_true", help="Use an isolated Docker workspace")
        p.add_argument("--yolo", action="store_true", help="Run tools without approval prompts")
        p.add_argument("--sandbox-image", help="Docker image for a new sandbox session")
        if command == "run":
            p.add_argument("task", help="Task to execute")
        else:
            p.add_argument(
                "--resume",
                nargs="?",
                const="latest",
                metavar="ID",
                help="Resume ID, or latest session for this repository",
            )
    p = sub.add_parser("resume", help="Resume a saved session (also: chat --resume)")
    p.add_argument(
        "session", nargs="?", default="latest",
        help="Session ID or unique prefix (default: latest non-empty chat)",
    )
    p.add_argument("--repo", default=".", help="Repository used to resolve latest")
    p.add_argument("--yolo", action="store_true", help="Run tools without approval prompts")
    p = sub.add_parser("diff", help="Show changes from agent edit and write tools")
    p.add_argument("session", help="Session ID or unique prefix")
    p.add_argument("--output", type=Path, help="Save recorded change history (not one applyable patch)")
    p = sub.add_parser("sessions", help="List recent sessions for this repository")
    p.add_argument("--repo", default=".", help="Repository to list")
    p.add_argument(
        "--all", action="store_true", help="Include all repositories and review sessions"
    )
    p = sub.add_parser("status", help="Check the model connection and limits")
    p.add_argument("--sandbox", action="store_true", help="Also check Docker and the sandbox image")
    sub.add_parser("config", help="Show YAML path, precedence, and effective settings")
    p = sub.add_parser("setup", help="Create or repair user configuration independently of the checkout")
    group = p.add_mutually_exclusive_group()
    group.add_argument("--edit", action="store_true", help="Edit with VISUAL/EDITOR; validate before saving")
    group.add_argument("--reset", action="store_true", help="Restore starter settings, backing up the original")
    p.add_argument("--path", type=Path, help="Explicit configuration to create/edit instead of global settings")
    return parser


def main():
    parser = build_parser()
    try:
        code = asyncio.run(execute(parser.parse_args()))
    except (RuntimeError, ValueError, OSError, httpx.HTTPError) as error:
        console.print(f"Error: {safe_text(error)}", style="red", markup=False)
        code = 1
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)
