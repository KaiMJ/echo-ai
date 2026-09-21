"""The same profile supplies both request limits and the vLLM command."""

import importlib.util
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def manager():
    path = Path(__file__).resolve().parents[1] / "scripts" / "deploy_local_model.py"
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
    runtime, server = manager.read_model_profile("builtin:qwen")
    server["max_num_seq"] = 1
    monkeypatch.setattr(manager, "read_model_profile", lambda _: (runtime, server))
    with pytest.raises(ValueError, match="exactly these keys"):
        manager.deployment("qwen", {"ECHO_HF_HUB_CACHE": str(tmp_path)})


def test_custom_deployment_profile(manager, tmp_path):
    runtime, server = manager.read_model_profile("builtin:qwen")
    runtime["context_tokens"] = 100000
    server["tensor_parallel_size"] = 1
    path = tmp_path / "custom.yaml"
    path.write_text(yaml.safe_dump({**runtime, "deployment": server}))
    settings, _, _, rendered = manager.deployment(
        "qwen", {"ECHO_HF_HUB_CACHE": str(tmp_path)}, path
    )
    command = yaml.safe_load(rendered)["services"]["inference"]["command"]
    assert settings.context_tokens == 100000
    assert command[command.index("--tensor-parallel-size") + 1] == "1"


@pytest.fixture
def cli(manager, monkeypatch, tmp_path):
    monkeypatch.setattr(manager, "ROOT", tmp_path)
    monkeypatch.delenv("ECHO_ENV_FILE", raising=False)
    monkeypatch.delenv("ECHO_HF_HUB_CACHE", raising=False)
    monkeypatch.delenv("ECHO_GEMMA_HUB_CACHE", raising=False)
    calls = []
    monkeypatch.setattr(manager.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    return manager, calls


@pytest.mark.parametrize("action", ["status", "logs", "stop"])
@pytest.mark.parametrize("prefix", [[], ["qwen"]])
def test_controls_need_no_model_files_or_environment(cli, action, prefix, monkeypatch):
    manager, calls = cli
    monkeypatch.setattr(manager, "deployment", lambda *a: pytest.fail("read deployment"))
    manager.main([*prefix, action])
    command = calls[0][0][0]
    assert command[-1] == "inference"
    assert "--env-file" not in command
    assert calls[0][1]["input"] is None
    if action == "status":
        assert "--all" in command


def test_log_controls(cli):
    manager, calls = cli
    manager.main(["logs", "--no-follow", "--tail", "25"])
    command = calls[0][0][0]
    assert command[-4:] == ["logs", "--tail", "25", "inference"]


def test_discovery_without_setup(cli, capsys):
    manager, calls = cli
    manager.main([])
    assert "Examples:" in capsys.readouterr().out
    manager.main(["models"])
    output = capsys.readouterr().out
    assert "qwen:" in output and "gemma:" in output
    assert "GPUs: 2" in output and "Revision:" in output
    assert not calls


@pytest.mark.parametrize("args", [["up"], ["qwen"], ["qwen", "up", "--wait-timeout", "0"]])
def test_invalid_cli_arguments(cli, args):
    manager, calls = cli
    with pytest.raises(SystemExit) as error:
        manager.main(args)
    assert error.value.code == 2
    assert not calls


def test_explicit_missing_env_is_reported(cli, tmp_path):
    manager, calls = cli
    with pytest.raises(ValueError, match="Environment file not found"):
        manager.main(["status", "--env-file", str(tmp_path / "missing")])
    assert not calls


def test_relative_env_path_resolved_before_compose_changes_directory(cli, tmp_path, monkeypatch):
    manager, calls = cli
    env = tmp_path / "settings.env"
    env.write_text("ECHO_INFERENCE_PORT=8123\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(manager, "load_dotenv", lambda *a, **kw: None)
    manager.main(["status", "--env-file", "settings.env"])
    command = calls[0][0][0]
    assert command[command.index("--env-file") + 1] == str(env)


def test_startup_failure_has_recovery_instructions(cli, monkeypatch):
    manager, _ = cli
    monkeypatch.setattr(
        manager,
        "deployment",
        lambda *a: (manager.Config(), Path("/hf"), Path("/hf/model"), "override"),
    )
    monkeypatch.setattr(manager, "validate", lambda *a: None)

    def fail(command, **kwargs):
        raise manager.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(manager.subprocess, "run", fail)
    with pytest.raises(ValueError, match="logs --no-follow"):
        manager.main(["qwen", "up"])


def test_missing_snapshot_explains_cache_layout(manager, tmp_path):
    with pytest.raises(ValueError, match="hub directory containing models--"):
        manager.validate(manager.Config(), tmp_path, tmp_path / "missing")


def test_up_uses_timeout_and_prints_matching_connection(cli, monkeypatch, capsys):
    manager, calls = cli
    monkeypatch.setenv("ECHO_INFERENCE_PORT", "8123")
    monkeypatch.setattr(
        manager,
        "deployment",
        lambda *a: (manager.Config(), Path("/hf"), Path("/hf/model"), "override"),
    )
    monkeypatch.setattr(manager, "validate", lambda *a: None)
    manager.main(["qwen", "up", "--wait-timeout", "90"])
    command = calls[0][0][0]
    assert command[command.index("--wait-timeout") + 1] == "90"
    assert calls[0][1]["input"] == "override"
    output = capsys.readouterr().out
    assert "ECHO_BASE_URL=http://127.0.0.1:8123/v1" in output
    assert "ECHO_MODEL_PROFILE=builtin:qwen" in output
    assert "ECHO_ENV_FILE=" not in output


def test_missing_docker_explains_requirement(cli, monkeypatch):
    manager, _ = cli

    def fail(*args, **kwargs):
        raise FileNotFoundError("docker")

    monkeypatch.setattr(manager.subprocess, "run", fail)
    with pytest.raises(ValueError, match="Install Docker with the Compose plugin"):
        manager.main(["status"])
