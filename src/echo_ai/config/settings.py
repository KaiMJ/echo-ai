"""Typed settings and validation; startup model tuning comes from packaged presets."""

import math
from dataclasses import dataclass, fields
from dataclasses import field as setting_field
from functools import lru_cache
from importlib.resources import files

import yaml

DEFAULT_PROFILE = "gemma"


@lru_cache
def default_profile():
    resource = files("echo_ai.config") / "presets" / f"{DEFAULT_PROFILE}.yaml"
    return yaml.safe_load(resource.read_text())


def preset_setting(name, fallback=None):
    return setting_field(default_factory=lambda: default_profile().get(name, fallback))


@dataclass(frozen=True)
class ModelSettings:
    base_url: str = preset_setting("base_url", "http://127.0.0.1:8001/v1")
    model: str = preset_setting("model")
    provider: str = preset_setting("provider")
    api_key_env: str = preset_setting("api_key_env", "ECHO_API_KEY")
    request_format: str = preset_setting("request_format")
    reasoning_effort: str = preset_setting("reasoning_effort", "")
    preserve_thinking: bool = preset_setting("preserve_thinking", False)
    max_tokens: int = preset_setting("max_tokens")
    context_tokens: int = preset_setting("context_tokens")
    max_context_chars: int | None = preset_setting("max_context_chars")
    timeout: float = preset_setting("timeout")
    temperature: float = preset_setting("temperature")
    top_p: float = preset_setting("top_p")
    top_k: int = preset_setting("top_k")
    reasoning_enabled: bool = preset_setting("reasoning_enabled")
    return_reasoning: bool = preset_setting("return_reasoning")


MODEL_FIELDS = frozenset(field.name for field in fields(ModelSettings))


@dataclass(frozen=True)
class RuntimeSettings(ModelSettings):
    max_steps: int = 20
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
    sandbox_image: str = "echo-ai-sandbox:local"

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
        if not self.model.strip() or not self.provider.strip():
            raise ValueError("model and provider must not be empty")
        if not self.sandbox_image.strip():
            raise ValueError("sandbox_image must not be empty")
        if self.provider == "hosted_vllm" and not self.base_url.strip():
            raise ValueError("base_url must not be empty for hosted_vllm")
        if self.request_format not in {"vllm", "qwen", "standard"}:
            raise ValueError("request_format must be vllm, qwen, or standard")
        if self.request_format == "qwen" and self.reasoning_effort not in {
            "",
            "low",
            "medium",
            "xhigh",
        }:
            raise ValueError("Qwen reasoning_effort must be low, medium, or xhigh")
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
