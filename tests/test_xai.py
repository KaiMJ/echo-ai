"""Exercise the real LiteLLM xAI adapter using synthetic HTTP responses only."""

import asyncio
import json

import httpx
import pytest

from echo_ai import cli
from echo_ai.config import Config
from echo_ai.config.file import read_model_profile
from echo_ai.runtime.model import Model, completion_kwargs


def xai_config():
    values, _ = read_model_profile("builtin:xai")
    return Config(**values)


async def test_xai_cache_routing_survives_resume_and_isolates_sessions(tmp_path, monkeypatch):
    from test_core import FakeSandbox

    from echo_ai.runtime.agent import Agent
    from echo_ai.runtime.store import Store

    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    requests = []

    async def chunks(params, transport=None):
        requests.append(params)
        yield {"choices": [{"delta": {"content": "Done."}, "finish_reason": "stop"}]}

    monkeypatch.setattr("echo_ai.runtime.model.completion_chunks", chunks)
    config = xai_config()
    store = Store(tmp_path / "state.db")
    try:
        first = store.create(tmp_path, {})
        second = store.create(tmp_path, {})
        model = Model(config)
        sandbox = FakeSandbox(tmp_path)
        agent = Agent(model, store, sandbox, first)
        await agent.run("First message")
        await agent.run("Follow-up")
        await Agent(Model(config), store, sandbox, first).run("Resumed")
        await Agent(model, store, sandbox, second).run("Separate session")
        assert [p["extra_headers"]["x-grok-conv-id"] for p in requests] == [
            first, first, first, second,
        ]
        assert requests[1]["messages"][:len(requests[0]["messages"])] == requests[0]["messages"]
        assert "extra_headers" not in completion_kwargs(
            Config(), [], [], conversation_id=first,
        )
    finally:
        store.close()


async def test_xai_stream_tool_round_trip(monkeypatch):
    monkeypatch.setenv("XAI_API_KEY", "test-xai-key")
    requests = []

    def respond(request):
        assert str(request.url) == "https://api.x.ai/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer test-xai-key"
        assert request.headers["x-grok-conv-id"] == "session-1"
        body = json.loads(request.content)
        requests.append(body)
        assert "chat_template_kwargs" not in body and "top_k" not in body
        assert body["reasoning_effort"] == "low"
        if len(requests) == 1:
            deltas = [
                ({"reasoning_content": "Checking."}, None),
                ({"tool_calls": [{"index": 0, "id": "call_1", "type": "function",
                  "function": {"name": "list", "arguments": '{"path":'}}]}, None),
                ({"tool_calls": [{"index": 0, "function": {"arguments": '"."}'}}]}, None),
                ({}, "tool_calls"),
            ]
        else:
            assert body["messages"][-1]["tool_call_id"] == "call_1"
            assert "reasoning" not in body["messages"][-2]
            deltas = [({"content": "Done."}, None), ({}, "stop")]
        chunks = [
            {"id": "response-1", "object": "chat.completion.chunk", "created": 1,
             "model": "grok-4.3", "choices": [{"index": 0, "delta": delta,
                                                "finish_reason": finish}]}
            for delta, finish in deltas
        ]
        chunks.append({"id": "response-1", "object": "chat.completion.chunk", "created": 1,
                       "model": "grok-4.3", "choices": [],
                       "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25,
                                 "cost_in_usd_ticks": 375000}})
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"},
            text="".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks)
            + "data: [DONE]\n\n",
        )

    model = Model(xai_config(), httpx.MockTransport(respond))
    messages = [{"role": "user", "content": "List files."}]
    tools = [{"type": "function", "function": {"name": "list", "parameters": {
        "type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"],
    }}}]
    async with asyncio.timeout(10):
        first, usage = await model.complete(
            messages, tools, lambda *_: None, conversation_id="session-1",
        )
    assert first["reasoning"] == "Checking."
    assert json.loads(first["tool_calls"][0]["function"]["arguments"]) == {"path": "."}
    assert usage["prompt_tokens"] == 20
    assert usage["cost_usd"] == pytest.approx(0.0000375)
    assert usage["cost_source"] == "reported"
    messages.extend([first, {"role": "tool", "tool_call_id": "call_1", "content": "[]"}])
    second, _ = await model.complete(
        messages, tools, lambda *_: None, conversation_id="session-1",
    )
    assert second["content"] == "Done."


async def test_missing_xai_key_is_actionable(monkeypatch, capsys):
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    config = xai_config()
    with pytest.raises(ValueError, match="Missing XAI_API_KEY"):
        completion_kwargs(config, [], [])
    assert await cli.status(config) == 1
    assert "detected automatically" in " ".join(capsys.readouterr().out.split())


async def test_xai_http_auth_failure_is_not_unknown_cost(monkeypatch):
    from echo_ai.runtime.errors import RequestRejected

    monkeypatch.setenv("XAI_API_KEY", "synthetic-key")
    model = Model(xai_config(), httpx.MockTransport(lambda _: httpx.Response(
        401, json={"error": {"message": "Invalid API key", "type": "authentication_error"}},
    )))
    events = []
    with pytest.raises(RequestRejected):
        await model.complete([], [], lambda kind, value: events.append((kind, value)))
    usage = next(value for kind, value in events if kind == "model_cost")
    assert usage["cost_usd"] == 0 and usage["cost_source"] == "rejected"


async def test_unavailable_model_is_quiet_and_can_be_changed(monkeypatch, capsys):
    from dataclasses import replace

    from echo_ai.runtime.errors import RequestRejected

    monkeypatch.setenv("XAI_API_KEY", "synthetic-key")

    def respond(request):
        if json.loads(request.content)["model"] == "unavailable-model":
            return httpx.Response(404, json={"error": {
                "message": "Model unavailable-model not found", "type": "not_found_error",
            }})
        chunk = {"id": "response-1", "object": "chat.completion.chunk", "created": 1,
                 "model": "grok-4.3", "choices": [{"index": 0,
                 "delta": {"content": "Recovered."}, "finish_reason": "stop"}]}
        return httpx.Response(200, headers={"content-type": "text/event-stream"},
                              text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")

    config = xai_config()
    model = Model(replace(config, model="unavailable-model"), httpx.MockTransport(respond))
    with pytest.raises(RequestRejected, match="unavailable-model"):
        await model.complete([], [], lambda *_: None)
    model.config = config
    response, _ = await model.complete([], [], lambda *_: None)
    assert response["content"] == "Recovered."
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""
