"""Public configuration API and runtime precedence (environment > YAML > defaults)."""

import os
from dataclasses import dataclass, fields
from pathlib import Path

from echo_ai.config.file import load_environment, read_document, yaml_values
from echo_ai.config.settings import RuntimeSettings
from echo_ai.config.theme import Theme


@dataclass(frozen=True)
class Config(RuntimeSettings):
    @classmethod
    def from_session(cls, values):
        """Keep pre-context-setting sessions on their original serving limits."""
        return cls(**{"context_tokens": 16384, "max_tokens": 4096, **values})

    @classmethod
    def from_env(cls):
        load_environment()
        values = {}
        document = read_document()
        Theme.from_mapping(document.pop("theme", {}))
        values = yaml_values(document)
        for field in fields(cls):
            key = "ECHO_" + field.name.upper()
            if key in os.environ:
                convert = int if field.name == "max_context_chars" else field.type
                try:
                    if convert is bool:
                        raw = os.environ[key].lower()
                        if raw not in {"true", "false"}:
                            raise ValueError("Expected true or false")
                        values[field.name] = raw == "true"
                    else:
                        values[field.name] = convert(os.environ[key])
                except ValueError as error:
                    raise ValueError(f"Invalid {key}: {os.environ[key]!r}") from error
        if "base_url" not in values:
            port = int(os.getenv("ECHO_INFERENCE_PORT", "8001"))
            if not 1 <= port <= 65535:
                raise ValueError("ECHO_INFERENCE_PORT must be between 1 and 65535")
            values["base_url"] = f"http://127.0.0.1:{port}/v1"
        return cls(**values)


def state_dir() -> Path:
    path = Path(os.getenv("ECHO_STATE_DIR", "~/.local/share/echo-ai")).expanduser()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def load_theme():
    """Appearance always comes from the current config, including on session resume."""
    load_environment()
    document = read_document()
    theme = Theme.from_mapping(document.pop("theme", {}))
    yaml_values(document)
    return theme
