"""Configuration boundaries: persistence, credentials, endpoints, and provenance."""

from dataclasses import replace

import pytest
import yaml

from echo_ai.config import Config
from echo_ai.config.file import config_dir, load_environment
from echo_ai.config.models import select_profile
from echo_ai.config.preferences import preferences_path, read_preferences, save_preferences
from echo_ai.config.settings import MODEL_FIELDS
from echo_ai.config.setup import setup
from echo_ai.runtime.model import completion_kwargs


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHO_ENV_FILE")
    return tmp_path


def test_credentials_reload_edits_deletions_and_shell_override(project, monkeypatch):
    local = project / ".env"
    global_file = config_dir() / ".env"
    global_file.parent.mkdir(parents=True)
    global_file.write_text("XAI_API_KEY=global-key\n")
    config = select_profile(Config(), "xai")
    local.write_text("XAI_API_KEY=first-key\n")
    assert completion_kwargs(config, [], [])["api_key"] == "first-key"
    local.write_text("XAI_API_KEY=corrected-key\n")
    assert completion_kwargs(config, [], [])["api_key"] == "corrected-key"
    local.unlink()
    assert completion_kwargs(config, [], [])["api_key"] == "global-key"
    monkeypatch.setenv("XAI_API_KEY", "shell-key")
    assert completion_kwargs(config, [], [])["api_key"] == "shell-key"
    monkeypatch.delenv("XAI_API_KEY")
    global_file.unlink()
    assert "XAI_API_KEY" not in load_environment()


def test_saved_inferred_endpoint_tracks_port_but_explicit_endpoint_wins(project, monkeypatch):
    config = Config.from_env()
    save_preferences(config)
    assert "base_url" not in read_preferences()
    monkeypatch.setenv("ECHO_INFERENCE_PORT", "9001")
    assert Config.from_env().base_url == "http://127.0.0.1:9001/v1"
    monkeypatch.setenv("ECHO_BASE_URL", "http://remote-server:9999/v1")
    config = select_profile(Config.from_env(), "qwen")
    assert config.base_url == "http://remote-server:9999/v1"
    save_preferences(config)
    monkeypatch.delenv("ECHO_BASE_URL")
    assert Config.from_env().base_url == "http://remote-server:9999/v1"


def test_preferences_share_state_directory_and_yaml_reset_preserves_them(project, monkeypatch):
    save_preferences(select_profile(Config(), "xai"))
    original = preferences_path()
    setup(reset=True)
    assert Config.from_env().provider == "xai"
    assert original.stat().st_mode & 0o777 == 0o600
    assert set(read_preferences()) <= MODEL_FIELDS
    monkeypatch.setenv("ECHO_STATE_DIR", str(project / "new-state"))
    assert preferences_path() == project / "new-state" / "model.yaml"
    assert Config.from_env().provider == "hosted_vllm"
    save_preferences(select_profile(Config(), "qwen"))
    assert Config.from_env().request_format == "qwen"
    assert original.is_file()
    monkeypatch.setenv("ECHO_STATE_DIR", str(original.parent))
    assert Config.from_env().provider == "xai"


def test_presets_match_startup_and_sources_explain_precedence(project, monkeypatch):
    initial = Config.from_env()
    assert initial == select_profile(initial, "gemma")
    save_preferences(select_profile(initial, "qwen"))
    (project / "echo.yaml").write_text("agent:\n  max_steps: 7\n")
    (project / ".env").write_text("ECHO_TEMPERATURE=0.3\n")
    monkeypatch.setenv("ECHO_MAX_TOKENS", "8192")
    config = Config.from_env()
    assert config.max_steps == 7 and config.temperature == 0.3 and config.max_tokens == 8192
    assert config.sources["model"] == str(preferences_path())
    assert config.sources["max_steps"] == "echo.yaml"
    assert config.sources["temperature"].endswith(".env: ECHO_TEMPERATURE")
    assert config.sources["max_tokens"] == "shell: ECHO_MAX_TOKENS"


def test_invalid_preferences_are_actionable_and_not_overwritten(project):
    path = preferences_path()
    path.parent.mkdir(parents=True)
    path.write_text("local-model:\n  unknown: true\n")
    with pytest.raises(ValueError, match="Cannot load model preferences"):
        Config.from_env()
    assert "unknown" in path.read_text()


def test_picker_can_clear_custom_endpoint(project, monkeypatch):
    from echo_ai.ui.model_settings import ModelSettings

    monkeypatch.setenv("ECHO_INFERENCE_PORT", "9002")
    selected = []
    panel = ModelSettings(replace(Config(), base_url="http://custom:8765/v1"),
                          lambda config, **_: selected.append(config), lambda: None)
    panel.fields["base_url"].text = ""
    panel.save()
    assert not panel.error
    assert selected[0].base_url == "http://127.0.0.1:9002/v1"
    save_preferences(selected[0])
    assert "base_url" not in yaml.safe_load(preferences_path().read_text())["local-model"]
