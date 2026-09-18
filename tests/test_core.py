import asyncio
import json
from dataclasses import asdict

import httpx
import pytest

from echo_ai.agent import Agent
from echo_ai.config import Config
from echo_ai.model import Model
from echo_ai.store import Store


def sse(*chunks):
    return "".join("data: " + json.dumps(c) + "\n\n" for c in chunks) + "data: [DONE]\n\n"


async def test_fragmented_tools_and_usage():
    body = sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call1",
                                "function": {"name": "read", "arguments": '{"pa'},
                            }
                        ]
                    }
                }
            ]
        },
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": 'th":"a.py"}'}}]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {"choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 5}},
    )
    model = Model(Config(), httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    message, metrics = await model.complete([], [], lambda *_: None)
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"path": "a.py"}
    assert metrics["prompt_tokens"] == 20


@pytest.mark.parametrize("ending", [None, "length"])
async def test_incomplete_generation_never_returns_tools(ending):
    body = sse(
        {
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {"index": 0, "id": "x", "function": {"name": "bash", "arguments": "{}"}}
                        ]
                    },
                    "finish_reason": ending,
                }
            ]
        }
    )
    model = Model(Config(), httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    with pytest.raises(RuntimeError):
        await model.complete([], [], lambda *_: None)


class FakeSandbox:
    def __init__(self, workspace):
        self.workspace = workspace
        self.calls = []

    async def execute(self, name, args):
        self.calls.append((name, args))
        return {"output": "ok"}


class FakeModel:
    config = Config()

    def __init__(self, messages):
        self.responses = iter(messages)

    async def complete(self, *_):
        response = next(self.responses)
        if isinstance(response, BaseException):
            raise response
        return response, {}


def call(name, args, key="call1"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": key,
                "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }
        ],
    }


async def test_validation_and_persistence(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, asdict(Config()))
    sandbox = FakeSandbox(tmp_path)
    model = FakeModel(
        [call("bash", {"command": "pwd", "timeout": -1}), {"role": "assistant", "content": "done"}]
    )
    result = await Agent(model, store, sandbox, key).run("test")
    assert result["status"] == "completed"
    assert not sandbox.calls
    assert "error" in json.loads(store.messages(key)[3]["content"])
    store.close()


def test_recovery_marks_unknown_without_replay(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    store.add(key, call("bash", {"command": "touch done"}))
    store.start(key)
    store.close()
    store = Store(tmp_path / "state.db")
    store.recover(key)
    store.recover(key)
    assert len(store.messages(key)) == 2
    assert "outcome unknown" in store.messages(key)[1]["content"]
    assert store.db.execute("SELECT status FROM runs").fetchone()[0] == "interrupted"
    store.close()


async def test_review_child_cannot_mutate(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    sandbox = FakeSandbox(tmp_path)
    model = FakeModel(
        [call("bash", {"command": "touch nope"}), {"role": "assistant", "content": "done"}]
    )
    await Agent(model, store, sandbox, key, child=True).run("review")
    assert not sandbox.calls
    store.close()


async def test_cancel_records_status(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    with pytest.raises(asyncio.CancelledError):
        await Agent(FakeModel([asyncio.CancelledError()]), store, FakeSandbox(tmp_path), key).run(
            "go"
        )
    assert store.db.execute("SELECT status FROM runs").fetchone()[0] == "cancelled"
    store.close()


async def test_delegate_links_sessions_and_shares_budget(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    sandbox = FakeSandbox(tmp_path)
    model = FakeModel(
        [
            call("delegate", {"task": "Read a.py"}),
            call("read", {"path": "a.py"}, "child-call"),
            {"role": "assistant", "content": "Reviewed a.py"},
            {"role": "assistant", "content": "Review complete"},
        ]
    )
    result = await Agent(model, store, sandbox, key).run("review")
    children = [s for s in store.sessions() if s["parent_id"] == key]
    assert len(children) == 1
    assert result["metrics"]["model_calls"] == 4
    assert result["metrics"]["tool_calls"] == 2
    assert sandbox.calls == [("read", {"path": "a.py"})]
    store.close()


async def test_cancel_between_tools_does_not_replay(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    message = call("read", {"path": "a.py"})
    message["tool_calls"].extend(call("bash", {"command": "touch changed"}, "second")["tool_calls"])

    class CancelSandbox(FakeSandbox):
        async def execute(self, name, args):
            if name == "bash":
                raise asyncio.CancelledError
            return await super().execute(name, args)

    sandbox = CancelSandbox(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        await Agent(FakeModel([message]), store, sandbox, key).run("go")
    store.recover(key)
    results = [m for m in store.messages(key) if m["role"] == "tool"]
    assert len(results) == 2
    assert "outcome unknown" in results[1]["content"]
    assert sandbox.calls == [("read", {"path": "a.py"})]
    store.close()


async def test_resumed_review_gets_a_fresh_budget_each_turn(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    model = FakeModel(
        [
            {"role": "assistant", "content": "First review"},
            {"role": "assistant", "content": "Second review"},
        ]
    )
    model.config = Config(max_steps=1)
    agent = Agent(model, store, FakeSandbox(tmp_path), key, child=True)
    assert (await agent.run("first"))["status"] == "completed"
    assert (await agent.run("second"))["status"] == "completed"
    store.close()
