"""Session model presets without loading or changing credential files."""

from dataclasses import replace

from echo_ai.config.file import load_environment
from echo_ai.config.resolver import profile_values, resolve_values


def select_profile(current, name):
    environment, env_sources = load_environment(with_sources=True)
    values = profile_values(name)
    sources = {field: f"builtin:{name}" for field in values}
    if current.provider == values["provider"] and current.base_url and (
        getattr(current, "sources", {}).get("base_url") != "local inference port"
    ):
        values["base_url"] = current.base_url
        sources["base_url"] = "current connection"
    values, sources = resolve_values(values, sources, environment, env_sources, model_only=True)
    config = replace(current, **values)
    object.__setattr__(config, "sources", {**getattr(current, "sources", {}), **sources})
    return config


def reasoning_choices(config):
    if config.request_format == "qwen":
        return [("off", "Off"), ("", "Default"), ("low", "Low"),
                ("medium", "Medium"), ("xhigh", "Extra high")]
    if config.request_format == "vllm":
        return [("off", "Off"), ("", "On")]
    choices = [("", "Provider default")]
    if config.provider == "xai" and config.model.startswith("grok-4.3"):
        choices.append(("none", "None"))
        choices.extend((value, value.capitalize()) for value in ("low", "medium", "high"))
    elif config.provider == "xai" and config.model.startswith(("grok-4.5", "grok-4.6")):
        choices.extend((value, value.capitalize()) for value in ("low", "medium", "high"))
        if config.model.startswith("grok-4.6"):
            choices.append(("xhigh", "Extra high"))
    elif config.reasoning_effort:
        choices.append((config.reasoning_effort, config.reasoning_effort))
    return choices


def reasoning_value(config):
    if config.request_format in {"qwen", "vllm"} and not config.reasoning_enabled:
        return "off"
    return config.reasoning_effort if config.reasoning_enabled else ""
