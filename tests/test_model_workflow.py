import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest

from echo_ai.config import Config
from echo_ai.config.file import load_environment
from echo_ai.config.models import select_profile
from echo_ai.runtime.agent import Agent
from echo_ai.runtime.errors import RequestRejected
from echo_ai.runtime.model import Model
from echo_ai.runtime.pricing import format_cost
from echo_ai.runtime.store import Store


@pytest.fixture
def workflow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ECHO_ENV_FILE")
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    monkeypatch.setenv("ECHO_STATE_DIR", str(tmp_path))
    store = Store(tmp_path / "sessions.sqlite3")
    config = select_profile(Config(max_steps=9), "xai")
    session = store.create(tmp_path, asdict(config))
    events = []
    agent = Agent(Model(config), store, SimpleNamespace(workspace=tmp_path, mode="local"), session,
                  lambda kind, value: events.append((kind, value)))
    yield agent, events
    store.close()


def test_default_selection_is_global_but_session_only_does_not_replace_it(workflow, monkeypatch):
    agent, _ = workflow
    agent.update_model(agent.model.config)
    assert Config.from_env().model == "grok-4.3"
    assert Config.from_env().reasoning_effort == "low"
    # Only model settings become global, not this session's agent/tool limits.
    assert Config.from_env().max_steps == Config().max_steps
    agent.update_model(select_profile(agent.model.config, "qwen"), make_default=False)
    assert Config.from_env().provider == "xai"
    assert json.loads(agent.store.session(agent.session_id)["config"])["provider"] == "hosted_vllm"
    monkeypatch.setenv("ECHO_MODEL", "explicit-override")
    assert Config.from_env().model == "explicit-override"


def test_detect_dotenv_credentials_without_loading_unrelated_variables(workflow, tmp_path, monkeypatch):
    import os

    (tmp_path / ".env").write_text("XAI_API_KEY=synthetic-project-key\nOTHER_SECRET=not-for-echo\n")
    environment = load_environment()
    assert environment["XAI_API_KEY"] == "synthetic-project-key"
    assert "XAI_API_KEY" not in os.environ
    assert "OTHER_SECRET" not in os.environ
    monkeypatch.setenv("XAI_API_KEY", "synthetic-shell-key")
    assert load_environment()["XAI_API_KEY"] == "synthetic-shell-key"


async def test_missing_key_creates_no_context_trace_or_cost(workflow):
    agent, events = workflow
    with pytest.raises(RequestRejected, match="Missing XAI_API_KEY"):
        await agent.run("Do not save this failed input")
    assert agent.store.messages(agent.session_id) == []
    assert agent.store.model_calls(agent.session_id) == []
    assert agent.store.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 0
    assert agent.store.session_cost(agent.session_id) == (0.0, 0, 0)
    assert events == [("input_rejected", {
        "prompt": "Do not save this failed input", "context_chars": 0,
    })]


async def test_new_dotenv_key_is_loaded_on_retry(workflow, tmp_path, monkeypatch):
    import echo_ai.runtime.model as module

    agent, _ = workflow
    with pytest.raises(RequestRejected):
        await agent.run("rejected")
    (tmp_path / ".env").write_text("XAI_API_KEY=synthetic-project-key\n")

    async def chunks(params, transport):
        assert params["api_key"] == "synthetic-project-key"
        assert [m["content"] for m in params["messages"] if m["role"] == "user"] == ["retry"]
        yield {"choices": [{"delta": {"content": "Done"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(module, "completion_chunks", chunks)
    await agent.run("retry")
    assert len(agent.store.messages(agent.session_id)) == 3


@pytest.mark.parametrize("error", [RequestRejected("401 unauthorized"), RuntimeError("Stream lost")])
async def test_failed_first_response_not_in_future_context(workflow, monkeypatch, error):
    import echo_ai.runtime.model as module

    agent, events = workflow
    monkeypatch.setenv("XAI_API_KEY", "synthetic-key")

    async def chunks(params, transport):
        raise error
        yield  # Keep the async iterator interface.

    monkeypatch.setattr(module, "completion_chunks", chunks)
    with pytest.raises(type(error)):
        await agent.run("failed prompt")
    assert not any(m["role"] == "user" for m in agent.store.messages(agent.session_id))
    assert len(agent.store.model_calls(agent.session_id)) == 1
    assert agent.store.session_cost(agent.session_id) == (
        0.0, 0, 0 if isinstance(error, RequestRejected) else 1,
    )
    assert next(v for k, v in events if k == "input_rejected")["context_chars"] == 0


def test_recover_previous_missing_key_failures(workflow):
    agent, _ = workflow
    store, session = agent.store, agent.session_id
    for _ in range(3):
        store.add(session, {"role": "user", "content": "Earlier rejected input"})
        run = store.start(session)
        call = store.start_model_call(session, run, asdict(agent.model.config))
        store.add_model_event(call, "usage", {"cost_usd": None, "cost_source": "unknown"})
        store.add_model_event(call, "end", {"status": "failed", "error_type": "ValueError",
                                           "error": "Missing XAI_API_KEY. Set it in your shell."})
        store.finish(run, "failed", {"model_calls": 1, "unknown_cost_calls": 1})
    store.recover(session)
    assert store.messages(session) == []
    assert store.session_cost(session) == (0.0, 0, 0)
    assert all(call["status"] == "rejected" for call in store.model_calls(session))
    assert store.session(session)["title"] == ""
    store.recover(session)  # Idempotent.
    assert store.session_cost(session) == (0.0, 0, 0)


def test_cost_format_is_compact_and_marks_estimates():
    assert format_cost(0) == "$0.00 USD"
    assert format_cost(0.000003, estimated=True) == "~$0.00 USD"
    assert format_cost(1.236) == "$1.24 USD"
