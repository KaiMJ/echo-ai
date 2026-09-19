import subprocess
from dataclasses import asdict
from pathlib import Path

import pytest
from jsonschema import ValidationError, validate

from echo_ai.config import Config
from echo_ai.runtime.tools import tools_for
from echo_ai.workspace import sandbox_tools
from echo_ai.workspace.sandbox import Sandbox, _workspace_size


def test_workspace_limit_applies_to_copy_and_existing_workspace(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "--quiet", str(repo)], check=True)
    (repo / "large").write_text("12345")
    config = Config(max_workspace_bytes=4)
    with pytest.raises(ValueError, match="4-byte"):
        Sandbox.create(repo, tmp_path / "state", config)
    with pytest.raises(ValueError, match="4-byte"):
        _workspace_size(repo, config.max_workspace_bytes)


def test_tool_schema_uses_configured_limits():
    config = Config(read_max_lines=10, read_default_lines=5, tool_max_timeout=5, tool_timeout=3)
    specs = {t["function"]["name"]: t["function"]["parameters"] for t in tools_for(config)}
    validate({"path": "a", "limit": 10}, specs["read"])
    with pytest.raises(ValidationError):
        validate({"path": "a", "limit": 11}, specs["read"])
    with pytest.raises(ValidationError):
        validate({"command": "pwd", "timeout": 6}, specs["bash"])
    assert tools_for(Config())[1]["function"]["parameters"]["properties"]["limit"]["maximum"] == 500


def test_file_tools_enforce_configured_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(
        sandbox_tools, "Path", lambda value: tmp_path if value == "/workspace" else Path(value)
    )
    (tmp_path / "a").write_text("one\ntwo\nthree\n")
    limits = asdict(Config(read_max_lines=2, read_default_lines=1, max_write_bytes=3))
    assert sandbox_tools._tool("read", {"path": "a"}, limits)["output"] == "1: one\n"
    assert (
        sandbox_tools._tool("read", {"path": "a", "limit": 100}, limits)["output"]
        == "1: one\n2: two\n"
    )
    with pytest.raises(ValueError, match="3 bytes"):
        sandbox_tools._tool("write", {"path": "b", "content": "four"}, limits)


async def test_docker_receives_configured_limits(tmp_path, monkeypatch):
    config = Config(sandbox_pids=12, sandbox_cpus=0.5, max_write_bytes=123,
                    sandbox_image="project-sandbox:local")
    sandbox = Sandbox(tmp_path, config)
    commands = []

    async def docker(*args):
        commands.append(args)
        return 0, ""

    monkeypatch.setattr("echo_ai.workspace.sandbox.os.getuid", lambda: 1000)
    monkeypatch.setattr(sandbox, "_docker", docker)
    await sandbox._start()
    command = commands[0]
    assert "--pids-limit=12" in command
    assert "--cpus=0.5" in command
    assert command[-1] == "project-sandbox:local"
    assert any('"max_write_bytes": 123' in arg for arg in command)


def test_edit_checks_resulting_utf8_size_before_writing(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox_tools, "Path", lambda _: tmp_path)
    file = tmp_path / "a"
    file.write_text("abc")
    limits = asdict(Config(max_edit_bytes=3))
    with pytest.raises(ValueError, match="3 bytes"):
        sandbox_tools._tool("edit", {"path": "a", "old": "a", "new": "éé"}, limits)
    assert file.read_text() == "abc"
    sandbox_tools._tool("edit", {"path": "a", "old": "abc", "new": "é"}, limits)
    assert file.read_text() == "é"
