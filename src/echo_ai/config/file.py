"""Configuration file structure and explicit environment loading."""

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

YAML_SECTIONS = {
    "local-model": {
        "base_url",
        "model",
        "provider",
        "api_key_env",
        "request_format",
        "reasoning_effort",
        "preserve_thinking",
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
        "sandbox_image",
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


def read_model_profile(path):
    """Read one model's request settings and optional local deployment settings."""
    try:
        model = yaml.safe_load(Path(path).read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Cannot load model profile {path}: {error}") from error
    if not isinstance(model, dict):
        raise ValueError(f"Model profile {path} must be a YAML mapping")  # noqa: TRY004
    deployment = model.pop("deployment", {})
    if not isinstance(deployment, dict):
        raise ValueError("deployment must be a YAML mapping")  # noqa: TRY004
    yaml_values({"local-model": model})
    return model, deployment


def read_document():
    path = Path(os.getenv("ECHO_CONFIG_FILE", "echo.yaml")).expanduser()
    if "ECHO_CONFIG_FILE" not in os.environ and not path.exists():
        document = {}
    else:
        try:
            document = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as error:
            raise ValueError(f"Cannot load configuration {path}: {error}") from error
    if document is None:
        document = {}
    if not isinstance(document, dict):
        raise ValueError("configuration must be a YAML mapping")  # noqa: TRY004
    profile = os.getenv("ECHO_MODEL_PROFILE", document.pop("model-profile", ""))
    if profile:
        if not isinstance(profile, str):
            raise ValueError("model-profile must be a path string")
        profile_path = Path(profile).expanduser()
        if not profile_path.is_absolute():
            profile_path = path.parent / profile_path
        model, _ = read_model_profile(profile_path)
        overrides = document.get("local-model", {})
        if not isinstance(overrides, dict):
            raise ValueError("local-model must be a YAML mapping")
        document["local-model"] = {**model, **overrides}
    return document
