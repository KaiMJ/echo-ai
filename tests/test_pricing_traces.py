import asyncio
import json
from dataclasses import asdict

import pytest

from echo_ai.config import Config
from echo_ai.runtime.model import Model
from echo_ai.runtime.pricing import cost_usage
from echo_ai.runtime.store import Store
from echo_ai.runtime.tracing import Trace


def cloud():
    return Config(provider="xai", model="grok-4.3", api_key_env="XAI_API_KEY",
                  request_format="standard", base_url="https://api.x.ai/v1")


def test_reported_estimated_cached_and_unknown_costs():
    config = cloud()
    assert cost_usage(config, {"cost_in_usd_ticks": 12300000}) == {
        "cost_usd": 0.00123, "cost_source": "reported",
    }
    usage = {"prompt_tokens": 1000, "completion_tokens": 100,
             "prompt_tokens_details": {"cached_tokens": 600}}
    assert cost_usage(config, usage)["cost_usd"] == pytest.approx(0.00087)
    assert cost_usage(config, usage)["cost_source"] == "estimated"
    assert cost_usage(config, {})["cost_usd"] is None
    assert cost_usage(Config(), {}) == {"cost_usd": 0.0, "cost_source": "local"}
    long_usage = {"prompt_tokens": 300000, "completion_tokens": 100,
                  "prompt_tokens_details": {"cached_tokens": 100000}}
    assert cost_usage(config, long_usage)["cost_usd"] == pytest.approx(0.5405)


@pytest.mark.parametrize("failure", [RuntimeError("broken stream"), asyncio.CancelledError()])
async def test_partial_traces_survive_failure_and_redact_credentials(tmp_path, monkeypatch, failure):
    import echo_ai.runtime.model as module

    monkeypatch.setenv("XAI_API_KEY", "fake-private-key")

    async def chunks(params, transport):
        yield {"choices": [{"delta": {"content": "partial"}}]}
        raise failure

    monkeypatch.setattr(module, "completion_chunks", chunks)
    store = Store(tmp_path / "state.db")
    session = store.create(tmp_path, asdict(cloud()))
    run = store.start(session)
    trace = Trace(store, session, run, cloud())
    with pytest.raises(type(failure)), trace:
        await Model(cloud()).complete(
            [{"role": "user", "content": "fake-private-key"}], [], lambda *_: None,
        )
    store.close()
    store = Store(tmp_path / "state.db")
    events = store.model_events(trace.call_id)
    text = json.dumps(events)
    assert "fake-private-key" not in text and "api_key" not in text
    assert not (tmp_path / "traces").exists()
    assert [event["event"] for event in events] == ["start", "request", "chunk", "usage", "end"]
    assert events[2]["data"]["choices"][0]["delta"]["content"] == "partial"
    assert trace.usage["cost_usd"] is None
    assert events[-1]["data"]["status"] == (
        "cancelled" if isinstance(failure, asyncio.CancelledError) else "failed"
    )
    store.close()


def test_session_cost_includes_children_and_persists(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    parent = store.create(tmp_path, asdict(cloud()))
    child = store.create(tmp_path, asdict(cloud()), parent)
    for key, cost, estimated, unknown in [(parent, 0.02, 0, 1), (child, 0.01, 1, 0)]:
        run = store.start(key)
        store.finish(run, "completed", {"cost_usd": cost, "estimated_cost_calls": estimated,
                                        "unknown_cost_calls": unknown})
    store.close()
    store = Store(path)
    total, estimated, unknown = store.session_cost(parent)
    assert total == pytest.approx(0.03) and estimated == unknown == 1
    store.close()


async def test_agent_saves_call_trace_and_cost(tmp_path, monkeypatch):
    from types import SimpleNamespace

    import echo_ai.runtime.model as module
    from echo_ai.runtime.agent import Agent

    monkeypatch.setenv("XAI_API_KEY", "synthetic-key")

    async def chunks(params, transport):
        yield {"choices": [{"delta": {"content": "Done."}, "finish_reason": "stop"}]}
        yield {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 2,
                                         "cost_in_usd_ticks": 50000}}

    monkeypatch.setattr(module, "completion_chunks", chunks)
    store = Store(tmp_path / "calls.db")
    config = cloud()
    session = store.create(tmp_path, asdict(config))
    agent = Agent(Model(config), store, SimpleNamespace(workspace=tmp_path, mode="local"), session)
    result = await agent.run("Hello")
    assert result["metrics"]["cost_usd"] == pytest.approx(0.000005)
    assert store.session_cost(session) == (0.000005, 0, 0)
    call = store.model_calls(session)[0]
    events = store.model_events(call["id"])
    assert json.loads(call["config"])["model"] == "grok-4.3"
    assert events[0]["data"]["model"] == "grok-4.3"
    assert any(event["event"] == "response" for event in events)
    assert events[-1]["data"]["status"] == "completed"
    store.close()


def test_sqlite_trace_is_incremental_and_recovers_abandoned_calls(tmp_path):
    path = tmp_path / "state.db"
    store = Store(path)
    session = store.create(tmp_path, asdict(cloud()))
    run = store.start(session)
    call = store.start_model_call(session, run, {"model": "grok-4.3"})
    store.add_model_event(call, "chunk", {"text": "partial"})
    reader = Store(path)
    assert reader.model_events(call)[0]["data"] == {"text": "partial"}
    assert reader.session_cost(session) == (0.0, 0, 1)
    store.add_model_event(call, "usage", {"cost_usd": 0.02, "cost_source": "reported"})
    assert reader.session_cost(session) == (0.02, 0, 0)
    store.close()  # Simulate process exit without a trace end event or run metrics.
    reader.recover(session)
    assert reader.model_calls(session)[0]["status"] == "interrupted"
    assert reader.session_cost(session) == (0.02, 0, 0)
    assert len(reader.model_events(call)) == 2
    reader.close()


def test_existing_database_gains_trace_tables_without_losing_sessions(tmp_path):
    path = tmp_path / "old.db"
    store = Store(path)
    session = store.create(tmp_path, asdict(cloud()))
    store.add(session, {"role": "user", "content": "Existing history"})
    store.db.executescript("DROP TABLE model_events; DROP TABLE model_calls;")
    store.close()
    store = Store(path)
    assert store.messages(session)[0]["content"] == "Existing history"
    assert store.model_calls(session) == []
    store.close()
