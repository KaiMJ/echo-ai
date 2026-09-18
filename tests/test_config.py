import json
import os

import httpx
import pytest

from echo_ai.config import Config
from echo_ai.model import Model


@pytest.fixture
def clean_config(tmp_path, monkeypatch):
    for name in os.environ:
        if name.startswith("ECHO_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_yaml_and_environment_precedence(clean_config, monkeypatch):
    (clean_config / "echo.yaml").write_text(
        "local-model:\n  reasoning_enabled: false\n  context_tokens: 32000\n  max_tokens: 4000\n"
        "  temperature: 0.2\n  max_context_chars: null\n"
        "agent:\n  max_steps: 12\nsandbox:\n  max_workspace_bytes: 1024\n"
        "tools:\n  read:\n    max_lines: 300\n  edit:\n    max_bytes: 2048\n"
    )
    (clean_config / ".env").write_text("ECHO_TEMPERATURE=0.5\n")
    monkeypatch.setenv("ECHO_MAX_TOKENS", "5000")
    config = Config.from_env()
    assert not config.reasoning_enabled
    assert config.context_tokens == 32000
    assert config.max_tokens == 5000
    assert config.temperature == 0.5
    assert config.max_steps == 12
    assert config.max_workspace_bytes == 1024
    assert config.read_max_lines == 300
    assert config.max_edit_bytes == 2048
    monkeypatch.setenv("ECHO_REASONING_ENABLED", "true")
    assert Config.from_env().reasoning_enabled
    monkeypatch.setenv("ECHO_REASONING_ENABLED", "nope")
    with pytest.raises(ValueError, match="ECHO_REASONING_ENABLED"):
        Config.from_env()


@pytest.mark.parametrize(
    "content",
    [
        "unknown: true",
        "- model",
        'reasoning_enabled: "false"',
        "context_tokens: small",
        "max_tokens: true",
        "top_k: 1.5",
        "context_tokens: 100",
        "temperature: -1",
        'model: ""',
        "model: [",
    ],
)
def test_invalid_yaml(clean_config, content):
    (clean_config / "echo.yaml").write_text("local-model:\n  " + content)
    with pytest.raises(ValueError):
        Config.from_env()


def test_explicit_path_and_defaults(clean_config, monkeypatch):
    assert Config.from_env() == Config()
    path = clean_config / "custom.yaml"
    monkeypatch.setenv("ECHO_CONFIG_FILE", str(path))
    with pytest.raises(ValueError, match="Cannot load"):
        Config.from_env()
    path.write_text("local-model:\n  model: custom\n")
    assert Config.from_env().model == "custom"
    assert Config.from_session({}).reasoning_enabled


@pytest.mark.parametrize("return_reasoning", [False, True])
async def test_transport_reasoning_policy_and_disables_generation(return_reasoning):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        chunk = {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]}
        return httpx.Response(200, text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")

    messages = [
        {
            "role": "assistant",
            "content": "answer",
            "reasoning": "private trace",
            "reasoning_content": "other trace",
        }
    ]
    model = Model(
        Config(reasoning_enabled=False, return_reasoning=return_reasoning),
        httpx.MockTransport(respond),
    )
    await model.complete(messages, [], lambda *_: None)
    assert requests[0]["chat_template_kwargs"] == {"enable_thinking": False}
    expected = messages if return_reasoning else [{"role": "assistant", "content": "answer"}]
    assert requests[0]["messages"] == expected
    assert messages[0]["reasoning"] == "private trace"


@pytest.mark.parametrize(
    "content",
    [
        "unknown: {}",
        "local-model: []",
        "sandbox: null",
        "sandbox:\n  temperature: 1",
        "agent:\n  model: wrong",
    ],
)
def test_invalid_sections(clean_config, content):
    (clean_config / "echo.yaml").write_text(content)
    with pytest.raises(ValueError):
        Config.from_env()


def test_all_config_fields_have_yaml_sections():
    from dataclasses import fields

    from echo_ai.config import YAML_SECTIONS

    def leaves(schema):
        return [
            field
            for value in schema.values()
            for field in (leaves(value) if isinstance(value, dict) else [value])
        ]

    names = leaves(YAML_SECTIONS)
    assert len(names) == len(set(names))
    assert set(names) == {field.name for field in fields(Config)}


def test_reasoning_replay_yaml_and_env(clean_config, monkeypatch):
    (clean_config / "echo.yaml").write_text("local-model:\n  return_reasoning: true\n")
    assert Config.from_env().return_reasoning
    monkeypatch.setenv("ECHO_RETURN_REASONING", "false")
    assert not Config.from_env().return_reasoning
    assert not Config.from_session({}).return_reasoning
