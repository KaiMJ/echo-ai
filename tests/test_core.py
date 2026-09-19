import asyncio
import json
from dataclasses import asdict

import httpx
import pytest

from echo_ai.config import Config
from echo_ai.runtime.agent import Agent
from echo_ai.runtime.model import Model
from echo_ai.runtime.store import Store


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
    events = []
    message, metrics = await model.complete([], [], lambda *event: events.append(event))
    assert json.loads(message["tool_calls"][0]["function"]["arguments"]) == {"path": "a.py"}
    assert metrics["prompt_tokens"] == 20
    drafts = [value for kind, value in events if kind == "tool_call_delta"]
    assert drafts[0]["arguments"] == '{"pa'
    assert drafts[-1] == {"index": 0, "name": "read", "arguments": '{"path":"a.py"}'}


async def test_reasoning_is_emitted_and_not_stored_as_content():
    body = sse(
        {"choices": [{"delta": {"reasoning": "plan "}}]},
        {"choices": [{"delta": {"reasoning_content": "then answer"}}]},
        {"choices": [{"delta": {"content": "done"}, "finish_reason": "stop"}]},
    )
    events = []
    model = Model(Config(), httpx.MockTransport(lambda _: httpx.Response(200, text=body)))
    message, _ = await model.complete([], [], lambda kind, value: events.append((kind, value)))
    assert message["content"] == "done"
    assert message["reasoning"] == "plan then answer"
    assert events == [("reasoning", "plan "), ("reasoning", "then answer"), ("text", "done")]


async def test_reasoning_is_saved_but_never_sent(tmp_path):
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui.renderer import Renderer

    renderer = Renderer(Console(file=StringIO()))
    requests, events, input_counts = [], [], []

    def emit(kind, value):
        previous_input = renderer.active.context
        renderer.emit(kind, value)
        events.append((kind, value))
        if kind == "model_start":
            input_counts.append(renderer.active.context)
        if kind == "reasoning":
            assert renderer.active.context == previous_input
            assert renderer.active.generated_chars > 0

    tool = call("list", {"path": "."})["tool_calls"][0]
    bodies = iter(
        [
            sse(
                {"choices": [{"delta": {"reasoning": "Inspect "}}]},
                {"choices": [{"delta": {"reasoning_content": "the files."}}]},
                {
                    "choices": [
                        {
                            "delta": {"tool_calls": [{"index": 0, **tool}]},
                            "finish_reason": "tool_calls",
                        }
                    ]
                },
            ),
            sse(
                {
                    "choices": [
                        {
                            "delta": {"content": "Done", "reasoning": "Finished"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            ),
            sse({"choices": [{"delta": {"content": "Next answer"}, "finish_reason": "stop"}]}),
        ]
    )

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, text=next(bodies))

    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    agent = Agent(
        Model(Config(), httpx.MockTransport(respond)),
        store,
        FakeSandbox(tmp_path),
        key,
        emit,
    )
    await agent.run("Inspect files")
    assistant = requests[1]["messages"][-2]
    assert "reasoning" not in assistant
    assert assistant["content"] is None
    assert requests[1]["messages"][-1]["role"] == "tool"
    start = [value for kind, value in events if kind == "model_start"][1]
    assert start["context_chars"] == len(json.dumps(requests[1]["messages"]))
    assert [m["reasoning"] for m in store.messages(key) if "reasoning" in m] == [
        "Inspect the files.",
        "Finished",
    ]
    await agent.run("Another task")
    assert all("reasoning" not in message for message in requests[2]["messages"])
    assert input_counts == [(len(json.dumps(request["messages"])) + 2) // 3 for request in requests]
    store.close()


async def test_saved_reasoning_does_not_consume_prompt_budget(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    message = {**call("list", {"path": "."}), "reasoning": "x" * 6000}
    model = FakeModel([message, {"role": "assistant", "content": "Recovered"}])
    model.config = Config(max_context_chars=5000)
    agent = Agent(model, store, FakeSandbox(tmp_path), key)
    assert (await agent.run("Inspect"))["text"] == "Recovered"
    assert any(m.get("reasoning") == "x" * 6000 for m in store.messages(key))
    assert all("reasoning" not in m for request in model.requests for m in request)
    store.close()


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
        self.requests = []

    async def complete(self, messages, *_):
        self.requests.append(json.loads(json.dumps(messages)))
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
    events = []
    with pytest.raises(asyncio.CancelledError):
        await Agent(
            FakeModel([asyncio.CancelledError()]),
            store,
            FakeSandbox(tmp_path),
            key,
            lambda kind, value: events.append((kind, value)),
        ).run("go")
    assert store.db.execute("SELECT status FROM runs").fetchone()[0] == "cancelled"
    assert events[-1][0] == "run_end"
    assert events[-1][1]["status"] == "cancelled"
    store.close()


async def test_delegate_links_sessions_and_shares_budget(tmp_path):
    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    sandbox = FakeSandbox(tmp_path)
    model = FakeModel(
        [
            {**call("delegate", {"task": "Read a.py"}), "reasoning": "Parent plan"},
            {**call("read", {"path": "a.py"}, "child-call"), "reasoning": "Child plan"},
            {"role": "assistant", "content": "Reviewed a.py"},
            {"role": "assistant", "content": "Review complete"},
        ]
    )
    events = []
    result = await Agent(
        model, store, sandbox, key, lambda kind, value: events.append((kind, value))
    ).run("review")
    children = [s for s in store.sessions() if s["parent_id"] == key]
    assert len(children) == 1
    assert result["metrics"]["model_calls"] == 4
    assert result["metrics"]["tool_calls"] == 2
    assert "Child plan" not in json.dumps(model.requests[2])
    assert any(m.get("reasoning") == "Child plan" for m in store.messages(children[0]["id"]))
    assert "Parent plan" not in json.dumps(model.requests[2])
    assert "Parent plan" not in json.dumps(model.requests[3])
    assert any(m.get("reasoning") == "Parent plan" for m in store.messages(key))
    assert "Child plan" not in json.dumps(model.requests[3])
    assert sandbox.calls == [("read", {"path": "a.py"})]
    assert ("child_task", "Read a.py") in events
    assert ("child_tool_detail", {"name": "read", "args": {"path": "a.py"}}) in events
    child_end = next(value for kind, value in events if kind == "child_run_end")
    assert child_end["status"] == "completed"
    assert events[-1][0] == "run_end"
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
        agent = Agent(FakeModel([message]), store, sandbox, key)
        agent.permissions.yolo = True
        await agent.run("go")
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


@pytest.mark.parametrize("return_reasoning", [False, True])
async def test_reasoning_policy_covers_history_tool_loop_and_input_counter(
    tmp_path, return_reasoning
):
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui.renderer import Renderer

    store = Store(tmp_path / "state.db")
    key = store.create(tmp_path, {})
    store.add(key, {"role": "assistant", "content": "Earlier", "reasoning_content": "Old trace"})
    model = FakeModel(
        [
            {**call("list", {"path": "."}), "reasoning": "Current trace"},
            {"role": "assistant", "content": "Done", "reasoning": "Final trace"},
        ]
    )
    model.config = Config(return_reasoning=return_reasoning)
    renderer = Renderer(Console(file=StringIO()))
    inputs = []

    def emit(kind, value):
        renderer.emit(kind, value)
        if kind == "model_start":
            inputs.append(renderer.active.context)
            assert renderer.active.return_reasoning == return_reasoning

    await Agent(model, store, FakeSandbox(tmp_path), key, emit).run("Inspect")
    assert ("Old trace" in json.dumps(model.requests[0])) == return_reasoning
    assert ("Current trace" in json.dumps(model.requests[1])) == return_reasoning
    assert inputs == [(len(json.dumps(request)) + 2) // 3 for request in model.requests]
    assert any(m.get("reasoning") == "Final trace" for m in store.messages(key))
    store.close()
