"""Configuration shared by interactive and batch execution."""

import math
import os
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import load_dotenv


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

    def __post_init__(self):
        for name in ("max_steps", "max_tokens", "context_tokens", "timeout"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")
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
        for field in fields(cls):
            key = "ECHO_" + field.name.upper()
            if key in os.environ:
                convert = int if field.name == "max_context_chars" else field.type
                try:
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
