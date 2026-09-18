"""Configuration shared by interactive and batch execution."""

import math
import os
from dataclasses import dataclass, fields
from pathlib import Path

import yaml
from dotenv import load_dotenv

YAML_SECTIONS = {
    "local-model": {
        "base_url",
        "model",
        "reasoning_enabled",
        "return_reasoning",
        "context_tokens",
        "max_tokens",
        "max_context_chars",
        "timeout",
        "temperature",
        "top_p",
        "top_k",
    },
    "agent": {"max_steps", "child_max_steps"},
    "sandbox": {
        "max_workspace_bytes",
        "sandbox_pids",
        "sandbox_memory_bytes",
        "sandbox_cpus",
        "sandbox_file_bytes",
        "sandbox_tmp_bytes",
    },
}
YAML_SECTIONS = {
    section: {name: name for name in names} for section, names in YAML_SECTIONS.items()
}
YAML_SECTIONS["tools"] = {
    "defaults": {"max_output_bytes": "max_output_bytes", "timeout": "tool_timeout"},
    "read": {"max_lines": "read_max_lines", "default_lines": "read_default_lines"},
    "search": {"max_matches_per_file": "search_max_matches"},
    "write": {"max_bytes": "max_write_bytes"},
    "edit": {"max_bytes": "max_edit_bytes"},
    "bash": {"max_timeout": "tool_max_timeout"},
}


def yaml_values(document, schema=YAML_SECTIONS, path="configuration"):
    if not isinstance(document, dict):
        raise ValueError(f"{path} must be a YAML mapping")  # noqa: TRY004 - CLI configuration error
    unknown = document.keys() - schema.keys()
    if unknown:
        raise ValueError(f"Unknown settings in {path}: {', '.join(map(str, unknown))}")
    values = {}
    for name, value in document.items():
        target = schema[name]
        if isinstance(target, dict):
            values.update(yaml_values(value, target, f"{path}.{name}"))
        else:
            values[target] = value
    return values


def load_environment():
    """Load only the explicitly selected file or the current directory's .env."""
    path = Path(os.getenv("ECHO_ENV_FILE", ".env")).expanduser()
    if "ECHO_ENV_FILE" in os.environ and not path.is_file():
        raise ValueError(f"Configuration file does not exist: {path}")
    load_dotenv(path, override=False)


@dataclass(frozen=True)
class Config:
    base_url: str = "http://127.0.0.1:8001/v1"
    model: str = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
    max_steps: int = 20
    max_tokens: int = 16384
    context_tokens: int = 262144
    max_context_chars: int | None = None
    timeout: float = 180
    temperature: float = 1.0
    top_p: float = 0.95
    top_k: int = 64
    reasoning_enabled: bool = True
    return_reasoning: bool = False
    max_workspace_bytes: int = 512 * 1024 * 1024
    max_output_bytes: int = 32768
    max_write_bytes: int = 1024 * 1024
    max_edit_bytes: int = 1024 * 1024
    read_max_lines: int = 500
    read_default_lines: int = 200
    search_max_matches: int = 50
    tool_timeout: int = 60
    tool_max_timeout: int = 120
    child_max_steps: int = 8
    sandbox_pids: int = 128
    sandbox_memory_bytes: int = 1024 * 1024 * 1024
    sandbox_cpus: float = 2.0
    sandbox_file_bytes: int = 64 * 1024 * 1024
    sandbox_tmp_bytes: int = 128 * 1024 * 1024

    def __post_init__(self):
        for field in fields(self):
            value = getattr(self, field.name)
            expected = field.type
            if field.name == "max_context_chars":
                valid = value is None or type(value) is int
            elif expected is float:
                valid = type(value) in (int, float)
            else:
                valid = type(value) is expected
            if not valid:
                raise ValueError(f"Invalid type for {field.name}")
        if not self.base_url.strip() or not self.model.strip():
            raise ValueError("base_url and model must not be empty")
        for name in ("max_steps", "max_tokens", "context_tokens", "timeout"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in (
            "max_workspace_bytes",
            "max_output_bytes",
            "max_write_bytes",
            "max_edit_bytes",
            "read_max_lines",
            "read_default_lines",
            "search_max_matches",
            "tool_timeout",
            "tool_max_timeout",
            "child_max_steps",
            "sandbox_pids",
            "sandbox_memory_bytes",
            "sandbox_cpus",
            "sandbox_file_bytes",
            "sandbox_tmp_bytes",
        ):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        if self.read_default_lines > self.read_max_lines:
            raise ValueError("read_default_lines must not exceed read_max_lines")
        if self.tool_timeout > self.tool_max_timeout:
            raise ValueError("tool_timeout must not exceed tool_max_timeout")
        if self.context_tokens <= self.max_tokens + 1500:
            raise ValueError("context_tokens must exceed max_tokens + 1500 for prompt overhead")
        if self.max_context_chars is not None and self.max_context_chars <= 0:
            raise ValueError("max_context_chars must be positive")
        if not math.isfinite(self.temperature) or self.temperature < 0:
            raise ValueError("temperature must be nonnegative and finite")
        if not 0 < self.top_p <= 1:
            raise ValueError("top_p must be in (0, 1]")
        if self.top_k != -1 and self.top_k < 1:
            raise ValueError("top_k must be -1 (disabled) or positive")

    @property
    def context_char_limit(self):
        # Heuristic only: leave room for output and template/schema overhead.
        derived = (self.context_tokens - self.max_tokens - 1500) * 3
        return min(derived, self.max_context_chars) if self.max_context_chars else derived

    @classmethod
    def from_session(cls, values):
        """Keep pre-context-setting sessions on their original serving limits."""
        return cls(**{"context_tokens": 16384, "max_tokens": 4096, **values})

    @classmethod
    def from_env(cls):
        load_environment()
        values = {}
        path = Path(os.getenv("ECHO_CONFIG_FILE", "echo.yaml")).expanduser()
        if "ECHO_CONFIG_FILE" in os.environ or path.exists():
            try:
                document = yaml.safe_load(path.read_text())
            except (OSError, yaml.YAMLError) as error:
                raise ValueError(f"Cannot load model configuration {path}: {error}") from error
            if document is None:
                document = {}
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
