import asyncio
import json
from dataclasses import asdict, replace
from io import StringIO
from types import SimpleNamespace

import pytest
from prompt_toolkit.data_structures import Size
from prompt_toolkit.formatted_text import to_formatted_text
from prompt_toolkit.input import DummyInput, create_pipe_input
from prompt_toolkit.output import DummyOutput
from rich.console import Console

from echo_ai.config import Config
from echo_ai.config.models import select_profile
from echo_ai.config.theme import Theme
from echo_ai.runtime.agent import Agent
from echo_ai.runtime.model import Model, completion_kwargs
from echo_ai.runtime.store import Store
from echo_ai.ui.model_settings import ModelSettings
from echo_ai.ui.renderer import Renderer
from echo_ai.ui.terminal import TerminalChat


@pytest.fixture
def agent(tmp_path, monkeypatch):
    from echo_ai.ui import terminal

    monkeypatch.setattr(terminal, "load_theme", Theme)
    monkeypatch.delenv("ECHO_INFERENCE_PORT", raising=False)
    monkeypatch.setenv("XAI_API_KEY", "synthetic-key")
    config = select_profile(Config(max_steps=9, tool_timeout=12), "qwen")
    store = Store(tmp_path / "sessions.db")
    session = store.create(tmp_path, asdict(config))
    agent = Agent(Model(config), store, SimpleNamespace(workspace=tmp_path, mode="local"), session)
    yield agent
    store.close()


def make_chat(agent, tmp_path, input=None):
    renderer = Renderer(Console(file=StringIO()))
    renderer.configure(agent)
    chat = TerminalChat(agent, tmp_path, renderer, input=input or DummyInput(), output=DummyOutput())
    renderer.event_handler = chat.on_event
    return chat


@pytest.mark.parametrize("profile", ["gemma", "qwen", "xai"])
def test_unchanged_settings_save_preserves_serialized_config(profile):
    config = select_profile(Config(), profile)
    saved = []
    panel = ModelSettings(config, lambda value, **_: saved.append(value), lambda: None)
    panel.save()
    assert not panel.error
    assert len(saved) == 1
    assert json.dumps(asdict(saved[0])) == json.dumps(asdict(config))


@pytest.mark.parametrize("effort", ["low", "high"])
def test_current_model_appears_once_with_custom_settings(effort):
    config = replace(select_profile(Config(), "xai"), reasoning_effort=effort, timeout=123.5)
    saved = []
    panel = ModelSettings(config, lambda value, **_: saved.append(value), lambda: None)
    choices = dict(panel.profile.options)
    assert "xai" not in choices
    assert config.model in choices["current"]
    assert {"gemma", "qwen"} <= choices.keys()
    panel.profile.value = "gemma"
    panel.change_profile()
    panel.profile.value = "current"
    panel.change_profile()
    panel.save()
    assert saved == [config]


def test_different_model_from_same_provider_remains_available():
    config = replace(select_profile(Config(), "xai"), model="grok-4.6")
    panel = ModelSettings(config, lambda _: None, lambda: None)
    assert "xai" in dict(panel.profile.options)


@pytest.mark.parametrize("field", ["timeout", "temperature", "top_p", "sandbox_cpus"])
def test_numeric_config_representation_is_stable_on_load(field):
    integer = Config(**{field: 1})
    decimal = Config(**{field: 1.0})
    assert json.dumps(asdict(integer)) == json.dumps(asdict(decimal))
    assert type(getattr(integer, field)) is float
    with pytest.raises(ValueError, match=f"Invalid type for {field}"):
        Config(**{field: True})


def test_panel_switch_validate_save_and_resume(agent, tmp_path):
    chat = make_chat(agent, tmp_path)
    chat.editor.text = "draft survives"
    chat.open_model_settings()
    panel = chat.model_settings
    panel.profile.value = "xai"
    panel.change_profile()
    assert panel.fields["model"].text == "grok-4.3"
    panel.reasoning.value = "high"
    panel.fields["temperature"].text = "bad"
    panel.save()
    assert "temperature" in panel.error
    assert agent.model.config.provider == "hosted_vllm"
    panel.fields["temperature"].text = "0.4"
    panel.save()
    assert chat.model_settings is None
    assert chat.editor.text == "draft survives"
    assert chat.app.layout.has_focus(chat.editor)
    config = Config(**json.loads(agent.store.session(agent.session_id)["config"]))
    assert config == agent.model.config
    assert config.provider == "xai" and config.reasoning_effort == "high"
    assert config.max_steps == 9 and config.tool_timeout == 12
    request = completion_kwargs(config, [], [])
    assert request["api_base"] == "https://api.x.ai/v1"
    assert request["reasoning_effort"] == "high" and "extra_body" not in request
    assert chat.renderer.model == "grok-4.3"
    chat.open_model_settings()
    panel = chat.model_settings
    panel.profile.value = "gemma"
    panel.change_profile()
    panel.scope.value = False
    panel.save()
    assert agent.model.config.provider == "hosted_vllm"
    assert agent.model.config.base_url == "http://127.0.0.1:8001/v1"
    assert agent.model.config.api_key_env == "ECHO_API_KEY"
    assert not agent.model.config.reasoning_enabled
    from echo_ai.config.preferences import read_preferences

    saved = read_preferences()
    assert saved["provider"] == "xai" and saved["reasoning_effort"] == "high"


def test_cancel_and_busy_guard(agent, tmp_path):
    chat = make_chat(agent, tmp_path)
    original = agent.model.config
    chat.open_model_settings()
    chat.model_settings.fields["model"].text = "unsaved"
    chat.close_model_settings()
    assert agent.model.config == original
    agent.running = True
    chat.open_model_settings()
    assert chat.model_settings is None
    with pytest.raises(ValueError, match="current turn"):
        agent.update_model(select_profile(original, "xai"))
    assert agent.model.config == original


def test_resume_restores_latest_request_tokens(agent, tmp_path):
    store, session = agent.store, agent.session_id
    run = store.start(session)
    for prompt, completion in [(100, 20), (350, 45)]:
        call = store.start_model_call(session, run, asdict(agent.model.config))
        store.add_model_event(call, "usage", {
            "prompt_tokens": prompt, "completion_tokens": completion,
            "completion_tokens_details": {"reasoning_tokens": 12},
        })
        store.add_model_event(call, "end", {"status": "completed"})
    rejected = store.start_model_call(session, run, asdict(agent.model.config))
    store.add_model_event(rejected, "end", {"status": "rejected"})
    chat = make_chat(agent, tmp_path)
    assert "Context 350 /" in chat.status()
    assert "Gen 45" in chat.status()
    assert not chat.renderer.main.estimated
    assert chat.renderer.main.reasoning_tokens == 12
    assert chat.renderer.calls == 0  # Restoring usage does not replay events.
    empty = store.create(tmp_path, asdict(agent.model.config))
    agent.session_id = empty
    chat.renderer.configure(agent)
    assert chat.renderer.main.context is None
    assert not chat.renderer.main.requested


def test_reasoning_and_model_choices(agent):
    panel = ModelSettings(select_profile(agent.model.config, "xai"), lambda _: None, lambda: None)
    assert "none" in dict(panel.reasoning.options)
    panel.fields["model"].text = "grok-4.6"
    assert "none" not in dict(panel.reasoning.options)
    assert "xhigh" in dict(panel.reasoning.options)
    panel.profile.value = "qwen"
    panel.change_profile()
    assert "high" not in dict(panel.reasoning.options)
    assert "off" in dict(panel.reasoning.options)


async def test_switch_changes_next_request_and_keeps_historic_call_settings(agent, monkeypatch):
    import echo_ai.runtime.model as module

    requests = []

    async def chunks(params, transport):
        requests.append(params)
        yield {"choices": [{"delta": {"content": "Answer", "reasoning_content": "Thinking"},
                             "finish_reason": "stop"}]}

    monkeypatch.setattr(module, "completion_chunks", chunks)
    await agent.run("First")
    agent.update_model(select_profile(agent.model.config, "xai"))
    await agent.run("Second")
    agent.update_model(select_profile(agent.model.config, "qwen"))
    await agent.run("Third")
    assert requests[1]["model"] == "xai/grok-4.3"
    assert "extra_body" not in requests[1]
    history = requests[2]["messages"]
    assistants = [m for m in history if m["role"] == "assistant"]
    assert assistants[0]["reasoning_content"] == "Thinking"
    assert "reasoning_content" not in assistants[1]
    assert all("_echo_model" not in m for m in history)
    calls = agent.store.model_calls(agent.session_id)
    assert [json.loads(call["config"])["provider"] for call in calls] == [
        "hosted_vllm", "xai", "hosted_vllm",
    ]
    assert len(agent.store.messages(agent.session_id)) == 7


@pytest.mark.parametrize("size", [Size(rows=24, columns=80), Size(rows=18, columns=52)])
async def test_settings_keyboard_navigation_save_cancel_and_modal_isolation(agent, tmp_path, size):
    async def wait_for(predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    with create_pipe_input() as pipe:
        chat = make_chat(agent, tmp_path, pipe)
        chat.app.output.get_size = lambda: size
        task = asyncio.create_task(chat.app.run_async())
        try:
            await wait_for(lambda: chat.app.is_running)
            pipe.send_text("/model\r")
            await wait_for(lambda: chat.model_settings is not None)
            pipe.send_text("\x1b[C")  # Current session -> xAI
            await wait_for(lambda: chat.model_settings.profile.value == "xai")
            pipe.send_text("\x1b[B")  # Down: preset -> model ID.
            await wait_for(lambda: chat.app.layout.has_focus(chat.model_settings.fields["model"]))
            model_text = chat.model_settings.fields["model"].text
            pipe.send_text("\x1b[A")  # Up works from a text field too.
            await wait_for(lambda: chat.app.layout.has_focus(chat.model_settings.profile.control))
            assert chat.model_settings.fields["model"].text == model_text
            pipe.send_text("\x1b[B\x1b[B\x1b[C")  # Model -> reasoning -> medium.
            await wait_for(lambda: chat.model_settings.reasoning.value == "medium")
            pipe.send_text("\x1b[D")
            await wait_for(lambda: chat.model_settings.reasoning.value == "low")
            pipe.send_text("\x1b[C")
            await wait_for(lambda: chat.model_settings.reasoning.value == "medium")
            await asyncio.sleep(0.05)
            screen = chat.app.renderer.last_rendered_screen
            visible = "\n".join(
                "".join(screen.data_buffer[y][x].char for x in range(size.columns))
                for y in range(size.rows)
            )
            assert "Model settings" in visible and "Save" in visible
            assert "Window too small" not in visible
            pipe.send_text("\x1b[B" * 8)  # Remaining fields -> Save button.
            await wait_for(lambda: "Save" in "".join(
                part[1] for part in to_formatted_text(
                    getattr(chat.app.layout.current_control, "text", "")
                )
            ))
            pipe.send_text("\r")
            await wait_for(lambda: chat.model_settings is None)
            assert agent.model.config.reasoning_effort == "medium"
            pipe.send_text("/model\r")
            await wait_for(lambda: chat.model_settings is not None)
            pipe.send_text("\x1b[Z")  # Shift+Tab must navigate, not toggle tool approval.
            await asyncio.sleep(0.05)
            assert not agent.permissions.yolo
            pipe.send_text("\x1b")
            await wait_for(lambda: chat.model_settings is None)
            assert agent.model.config.provider == "xai"
        finally:
            if chat.app.is_running:
                chat.app.exit()
            await asyncio.wait_for(task, 3)


def test_legacy_reasoning_is_attributed_before_switch(agent):
    agent.store.add(agent.session_id, {"role": "assistant", "content": "Old", "reasoning": "Local"})
    agent.update_model(replace(select_profile(agent.model.config, "xai"), return_reasoning=True))
    history = completion_kwargs(agent.model.config, agent.store.messages(agent.session_id), [])
    assert "reasoning" not in history["messages"][0]


async def test_failed_key_check_restores_draft_and_clears_context_display(agent, tmp_path, monkeypatch):
    agent.update_model(select_profile(agent.model.config, "xai"))
    monkeypatch.delenv("XAI_API_KEY")
    chat = make_chat(agent, tmp_path)
    agent.emit = chat.renderer.emit
    await chat.submit("Retry this input")
    assert not any(entry.kind == "user" for entry in chat.entries)
    assert any(entry.title == "Error" for entry in chat.entries)
    assert chat.editor.text == "Retry this input"
    assert chat.renderer.active.context == 0
    assert chat.renderer.unknown_cost_calls == 0
    assert agent.store.session_cost(agent.session_id) == (0.0, 0, 0)
