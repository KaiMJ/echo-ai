"""Resolve runtime settings and their origins without mutating the process environment."""

from dataclasses import asdict, fields

from echo_ai.config.file import (
    config_path,
    load_environment,
    read_document,
    read_model_profile,
    yaml_values,
)
from echo_ai.config.settings import DEFAULT_PROFILE, MODEL_FIELDS, ModelSettings, RuntimeSettings
from echo_ai.config.theme import Theme


def profile_values(name):
    values, _ = read_model_profile(f"builtin:{name}")
    baseline = asdict(ModelSettings())
    baseline.pop("base_url")
    return {**baseline, **values}


def resolve_values(values, sources, environment, environment_sources, *, model_only=False):
    for field in fields(ModelSettings if model_only else RuntimeSettings):
        key = "ECHO_" + field.name.upper()
        if key not in environment:
            continue
        convert = int if field.name == "max_context_chars" else field.type
        raw = environment[key]
        try:
            if convert is bool:
                if raw.lower() not in {"true", "false"}:
                    raise ValueError("Expected true or false")
                values[field.name] = raw.lower() == "true"
            else:
                values[field.name] = convert(raw)
        except ValueError as error:
            raise ValueError(f"Invalid {key}: {raw!r}") from error
        sources[field.name] = f"{environment_sources[key]}: {key}"
    if not values.get("base_url"):
        if values.get("provider", "hosted_vllm") == "hosted_vllm":
            port = int(environment.get("ECHO_INFERENCE_PORT", "8001"))
            if not 1 <= port <= 65535:
                raise ValueError("ECHO_INFERENCE_PORT must be between 1 and 65535")
            values["base_url"] = f"http://127.0.0.1:{port}/v1"
            sources["base_url"] = "local inference port"
        else:
            values["base_url"] = ""
            sources["base_url"] = "provider default"
    return values, sources


def resolve(config_class):
    from echo_ai.config.preferences import preferences_path, read_preferences

    environment, env_sources = load_environment(with_sources=True)
    preferences = read_preferences(environment)
    document = read_document(environment=environment)
    Theme.from_mapping(document.pop("theme", {}))
    values = profile_values(DEFAULT_PROFILE)
    sources = {name: f"builtin:{DEFAULT_PROFILE}" for name in values}
    yaml_settings = yaml_values(document)
    values.update(yaml_settings)
    yaml_source = str(config_path(environment))
    sources.update({name: yaml_source for name in yaml_settings})
    if preferences:
        # A saved selection replaces the entire model, including its connection defaults.
        for name in list(values):
            if name in MODEL_FIELDS and name not in preferences:
                values.pop(name)
                sources.pop(name, None)
        values.update(preferences)
        sources.update({name: str(preferences_path(environment)) for name in preferences})
    values, sources = resolve_values(values, sources, environment, env_sources)
    config = config_class(**values)
    sources = {field.name: sources.get(field.name, "built-in runtime default")
               for field in fields(config)}
    object.__setattr__(config, "sources", sources)
    return config
