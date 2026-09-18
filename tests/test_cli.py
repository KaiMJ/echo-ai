from dataclasses import asdict

from echo_ai import cli
from echo_ai.config import Config
from echo_ai.store import Store


def test_help_and_resume_arguments():
    parser = cli.build_parser()
    help_ = parser.format_help()
    assert "--resume" in help_ and "--sandbox" in help_ and "bench" not in help_
    assert "Execute one task and exit" in help_
    assert parser.parse_args(["chat", "--resume"]).resume == "latest"
    assert parser.parse_args(["chat", "--resume", "abc"]).resume == "abc"
    assert not parser.parse_args(["chat"]).sandbox
    assert parser.parse_args(["status", "--sandbox"]).sandbox


async def test_switch_restores_saved_mode_config_and_releases_lock(tmp_path, monkeypatch):
    from echo_ai.store import workspace_lock

    root = tmp_path / "state"
    root.mkdir()
    store = Store(root / "sessions.sqlite3")
    workspaces = [tmp_path / "one/workspace", tmp_path / "two/workspace"]
    for path in workspaces:
        path.mkdir(parents=True)
        (path.parent / "baseline.git").mkdir()
    configs = [Config(max_steps=3), Config(max_steps=5)]
    ids = [
        store.create(path, asdict(config), repo=tmp_path)
        for path, config in zip(workspaces, configs)
    ]
    store.close()
    monkeypatch.setattr(cli, "state_dir", lambda: root)
    monkeypatch.setattr(Config, "from_env", lambda: Config())
    seen = []

    async def chat(agent, root):
        seen.append((agent.session_id, agent.sandbox.mode, agent.model.config.max_steps))
        if agent.session_id == ids[0]:
            return ids[1]
        with workspace_lock(workspaces[0]):
            pass
        return None

    monkeypatch.setattr(cli, "chat", chat)
    assert await cli.execute(cli.build_parser().parse_args(["chat", "--resume", ids[0]])) == 0
    assert seen == [(ids[0], "sandbox", 3), (ids[1], "sandbox", 5)]
    with workspace_lock(workspaces[1]):
        pass


async def test_plain_session_switch(tmp_path, monkeypatch):
    from types import SimpleNamespace

    store = Store(tmp_path / "state.db")
    current = store.create(tmp_path, {}, repo=tmp_path)
    target = store.create(tmp_path, {}, repo=tmp_path)
    prompts = iter(["/help", "/sessions", "/sessions missing", "/sessions " + target[:8]])

    class Prompt:
        async def prompt_async(self, _):
            return next(prompts)

    monkeypatch.setattr(cli, "make_prompt", lambda *args, **kwargs: Prompt())
    monkeypatch.setattr(cli.renderer, "plain", True)
    agent = SimpleNamespace(store=store, session_id=current)
    assert await cli.chat(agent, tmp_path) == target
    store.close()


async def test_run_defaults_to_local_tools_and_persists_mode(tmp_path, monkeypatch):
    import asyncio
    import json
    import subprocess

    import httpx

    from echo_ai.model import Model

    repo, root = tmp_path / "repo", tmp_path / "state"
    repo.mkdir()
    root.mkdir()
    await asyncio.to_thread(subprocess.run, ["git", "init", "--quiet", str(repo)], check=True)
    (repo / "hello.txt").write_text("before")
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert "user's local checkout" in body["messages"][0]["content"]
        delta = (
            {
                "tool_calls": [
                    {
                        "index": 0,
                        "id": "edit1",
                        "type": "function",
                        "function": {
                            "name": "edit",
                            "arguments": json.dumps(
                                {"path": "hello.txt", "old": "before", "new": "after"}
                            ),
                        },
                    }
                ]
            }
            if len(calls) == 1
            else {"content": "Done"}
        )
        event = {
            "choices": [
                {"delta": delta, "finish_reason": "tool_calls" if len(calls) == 1 else "stop"}
            ]
        }
        return httpx.Response(200, text="data: " + json.dumps(event) + "\n\ndata: [DONE]\n\n")

    monkeypatch.setattr(cli, "state_dir", lambda: root)
    monkeypatch.setattr(Config, "from_env", lambda: Config())
    monkeypatch.setattr(cli, "Model", lambda config: Model(config, httpx.MockTransport(respond)))
    args = cli.build_parser().parse_args(["run", "--repo", str(repo), "Change hello"])
    assert await cli.execute(args) == 0
    assert (repo / "hello.txt").read_text() == "after"
    assert len(calls) == 2
    store = Store(root / "sessions.sqlite3")
    session = store.resolve("latest", repo)
    assert session["mode"] == "local" and session["title"] == "Change hello"
    assert session["state_path"]
    store.close()


def test_default_command_starts_chat():
    parser = cli.build_parser()
    args = parser.parse_args([])
    assert args.command == "chat" and args.repo == "."
    assert args.resume is None and not args.sandbox
    args = parser.parse_args(["--repo", "/tmp/project", "--resume"])
    assert args.command == "chat" and args.repo == "/tmp/project"
    assert args.resume == "latest"


def test_plain_option_removed():
    import pytest

    parser = cli.build_parser()
    assert "--plain" not in parser.format_help()
    for args in (
        ["--plain"],
        ["chat", "--plain"],
        ["run", "--plain", "task"],
        ["resume", "id", "--plain"],
    ):
        with pytest.raises(SystemExit):
            parser.parse_args(args)
