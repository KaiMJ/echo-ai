"""Runtime defaults and validation, independent of files and the terminal UI."""

import math
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class RuntimeSettings:
    base_url: str = "http://127.0.0.1:8001/v1"
    model: str = "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit"
    provider: str = "hosted_vllm"
    api_key_env: str = "ECHO_API_KEY"
    request_format: str = "vllm"
    reasoning_effort: str = ""
    preserve_thinking: bool = False
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
        if not self.model.strip() or not self.provider.strip():
            raise ValueError("model and provider must not be empty")
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
