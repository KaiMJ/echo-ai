"""The same profile supplies both request limits and the vLLM command."""

import importlib.util
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def manager():
    path = Path(__file__).resolve().parents[1] / "models" / "manage.py"
    spec = importlib.util.spec_from_file_location("echo_deploy", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_both_profiles_supply_model_and_context_to_deployment(manager, tmp_path):
    for name in ("gemma", "qwen"):
        settings, cache, snapshot, rendered = manager.deployment(
            name, {"ECHO_HF_HUB_CACHE": str(tmp_path)}
        )
        service = yaml.safe_load(rendered)["services"]["inference"]
        command = service["command"]
        assert command[command.index("--max-model-len") + 1] == str(settings.context_tokens)
        assert settings.max_tokens == 65536
        assert command[command.index("--max-num-seqs") + 1] == "1"
        assert settings.model in command
        assert snapshot.is_relative_to(cache)
        assert service["volumes"][0]["bind"]["create_host_path"] is False


def test_separate_cache_override_and_missing_cache(manager, tmp_path):
    _, cache, _, _ = manager.deployment(
        "gemma",
        {
            "ECHO_HF_HUB_CACHE": str(tmp_path / "default"),
            "ECHO_GEMMA_HUB_CACHE": str(tmp_path / "gemma"),
        },
    )
    assert cache == tmp_path / "gemma"
    with pytest.raises(ValueError, match="Set ECHO_HF_HUB_CACHE"):
        manager.deployment("qwen", {})


def test_deployment_rejects_unknown_options(manager, tmp_path, monkeypatch):
    runtime, server = manager.read_model_profile(manager.ROOT / "models/qwen.yaml")
    server["max_num_seq"] = 1
    monkeypatch.setattr(manager, "read_model_profile", lambda _: (runtime, server))
    with pytest.raises(ValueError, match="exactly these keys"):
        manager.deployment("qwen", {"ECHO_HF_HUB_CACHE": str(tmp_path)})
