import os
from pathlib import Path

import pytest

from echo_ai import cli
from echo_ai.config import Config
from echo_ai.config.file import config_dir, config_path, load_environment, read_document
from echo_ai.config.setup import setup


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("ECHO_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_discovery_and_relative_profiles(isolated, monkeypatch):
    path, _ = setup()
    assert config_path() == path
    assert "builtin:qwen" in path.read_text()
    assert not (path.parent / "models").exists()
    assert Config.from_env().request_format == "qwen"
    project = isolated / "echo.yaml"
    project.write_text("agent:\n  max_steps: 7\n")
    assert Config.from_env().max_steps == 7
    assert Config.from_env().model == Config().model  # Selection, never merging.
    monkeypatch.setenv("ECHO_CONFIG_FILE", str(path))
    assert Config.from_env().request_format == "qwen"
    monkeypatch.setenv("ECHO_CONFIG_FILE", str(isolated / "missing.yaml"))
    with pytest.raises(ValueError, match="Cannot load"):
        Config.from_env()


def test_environment_is_global_or_explicit(isolated, monkeypatch):
    setup()
    (isolated / ".env").write_text("ECHO_TEMPERATURE=0.2\n")
    assert Config.from_env().temperature == 1.0
    (config_dir() / ".env").write_text("ECHO_TEMPERATURE=0.3\n")
    assert Config.from_env().temperature == 0.3
    monkeypatch.setenv("ECHO_TEMPERATURE", "0.4")
    assert Config.from_env().temperature == 0.4
    monkeypatch.delenv("ECHO_TEMPERATURE")
    monkeypatch.setenv("ECHO_ENV_FILE", str(isolated / ".env"))
    assert Config.from_env().temperature == 0.2
    monkeypatch.setenv("ECHO_ENV_FILE", str(isolated / "missing"))
    with pytest.raises(ValueError, match="does not exist"):
        load_environment()


def test_setup_preserves_development_and_existing_files(isolated, monkeypatch):
    project = isolated / "echo.yaml"
    project.write_text("agent:\n  max_steps: 6\n")
    (isolated / ".env").write_text("PRIVATE_DEVELOPMENT_SECRET=do-not-copy\n")
    monkeypatch.setenv("ECHO_CONFIG_FILE", str(project))
    path, saved = setup()
    assert path != project and saved is None
    assert not (path.parent / ".env").exists()
    path.write_text("agent:\n  max_steps: 9\n")
    setup()
    assert "9" in path.read_text() and "6" in project.read_text()
    assert path.parent.stat().st_mode & 0o777 == 0o700
    assert path.stat().st_mode & 0o777 == 0o600


async def test_reset_works_with_broken_config_and_environment(isolated, monkeypatch):
    path, _ = setup()
    path.write_text("broken: [")
    monkeypatch.setenv("ECHO_ENV_FILE", str(isolated / "missing.env"))
    args = cli.build_parser().parse_args(["setup", "--reset"])
    assert await cli.execute(args) == 0
    backups = list(path.parent.glob("echo.yaml.backup-*"))
    assert backups[0].read_text() == "broken: ["
    assert backups[0].stat().st_mode & 0o777 == 0o600
    assert read_document(path, use_environment=False)["local-model"]


def test_editor_validates_before_replacement(isolated, monkeypatch):
    import echo_ai.config.setup as module

    path, _ = setup()
    original = path.read_text()

    def edit(command, **kwargs):
        from types import SimpleNamespace

        Path(command[-1]).write_text("local-model:\n  max_tokens: -1\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/vi")
    monkeypatch.setattr(module.subprocess, "run", edit)
    with pytest.raises(ValueError, match="Original preserved; edited draft"):
        setup(edit=True)
    assert path.read_text() == original
    drafts = list(path.parent.glob(".echo-edit-*.backup-*"))
    assert "-1" in drafts[0].read_text()


def test_xdg_fallback(isolated, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert config_dir() == isolated / ".config/echo-ai"
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative")
    assert config_dir() == isolated / ".config/echo-ai"


def test_edit_repairs_invalid_yaml(isolated, monkeypatch):
    from types import SimpleNamespace

    import echo_ai.config.setup as module

    path, _ = setup()
    path.write_text("broken: [")

    def edit(command, **kwargs):
        Path(command[-1]).write_text("agent:\n  max_steps: 12\n")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(module.shutil, "which", lambda _: "/usr/bin/vi")
    monkeypatch.setattr(module.subprocess, "run", edit)
    _, saved = setup(edit=True)
    assert saved.read_text() == "broken: ["
    assert Config.from_env().max_steps == 12


async def test_config_hides_url_credentials(isolated, monkeypatch, capsys):
    setup()
    monkeypatch.setenv("ECHO_BASE_URL", "https://user:private@example.com/v1?key=token")
    monkeypatch.setenv("ECHO_API_KEY", "secret-value")
    assert await cli.execute(cli.build_parser().parse_args(["config"])) == 0
    output = capsys.readouterr().out
    assert "private" not in output and "token" not in output.replace("tokens", "")
    assert "secret-value" not in output
    assert str(config_dir()) in output


def test_custom_relative_profile_still_works(isolated):
    path, _ = setup()
    (path.parent / "custom.yaml").write_text("model: custom-model\n")
    path.write_text("model-profile: custom.yaml\nlocal-model:\n  temperature: 0.4\n")
    assert Config.from_env().model == "custom-model"
    assert Config.from_env().temperature == 0.4
    setup()
    assert "custom.yaml" in path.read_text()


def test_unknown_builtin_profile_fails_clearly(isolated):
    from echo_ai.config.file import read_model_profile

    with pytest.raises(ValueError, match="Unknown built-in"):
        read_model_profile("builtin:../qwen")
