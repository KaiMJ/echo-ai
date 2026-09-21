"""YAML settings, packaged model presets, and credential discovery."""

import os
from importlib.resources import files
from pathlib import Path

import yaml
from dotenv import dotenv_values

from echo_ai.config.settings import MODEL_FIELDS

YAML_SECTIONS = {
    "local-model": MODEL_FIELDS,
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


def config_dir():
    root = Path(os.getenv("XDG_CONFIG_HOME") or "~/.config").expanduser()
    if not root.is_absolute():
        root = Path("~/.config").expanduser()
    return root / "echo-ai"


def config_path(environment=None):
    environment = os.environ if environment is None else environment
    if "ECHO_CONFIG_FILE" in environment:
        return Path(environment["ECHO_CONFIG_FILE"]).expanduser()
    local = Path("echo.yaml")
    return local if local.exists() else config_dir() / "echo.yaml"


def environment_path():
    if "ECHO_ENV_FILE" in os.environ:
        return Path(os.environ["ECHO_ENV_FILE"]).expanduser()
    local = Path.cwd() / ".env"
    return local if local.is_file() else config_dir() / ".env"


def load_environment(*, api_key_env=None, with_sources=False):
    """Shell > explicit file, or project .env > global .env; never execute shell code."""
    path = environment_path()
    if "ECHO_ENV_FILE" in os.environ and not path.is_file():
        raise ValueError(f"Configuration file does not exist: {path}")
    paths = [path] if "ECHO_ENV_FILE" in os.environ else [path, config_dir() / ".env"]
    values, sources = {}, {}
    for source in reversed(list(dict.fromkeys(paths))):
        if source.is_file():
            for name, value in dotenv_values(source).items():
                if value is not None and (
                    name.startswith("ECHO_") or name.endswith("_API_KEY") or name == api_key_env
                ):
                    values[name] = value
                    sources[name] = str(source)
    values.update(os.environ)
    sources.update({name: "shell" for name in os.environ})
    return (values, sources) if with_sources else values


def builtin_profiles():
    return files("echo_ai.config") / "presets"


def builtin_profile_names():
    return sorted(p.name.removesuffix(".yaml") for p in builtin_profiles().iterdir()
                  if p.name.endswith(".yaml") and p.name != "echo.yaml" and p.is_file())


def read_model_profile(path):
    """Read one model's request settings and optional local deployment settings."""
    if str(path).startswith("builtin:"):
        name = str(path).removeprefix("builtin:")
        if name not in builtin_profile_names():
            raise ValueError(f"Unknown built-in model profile: {name}")
        source = builtin_profiles() / f"{name}.yaml"
    else:
        source = Path(path)
    try:
        model = yaml.safe_load(source.read_text())
    except (OSError, yaml.YAMLError) as error:
        raise ValueError(f"Cannot load model profile {path}: {error}") from error
    if not isinstance(model, dict):
        raise ValueError(f"Model profile {path} must be a YAML mapping")  # noqa: TRY004
    deployment = model.pop("deployment", {})
    if not isinstance(deployment, dict):
        raise ValueError("deployment must be a YAML mapping")  # noqa: TRY004
    yaml_values({"local-model": model})
    return model, deployment


def read_document(path=None, *, environment=None):
    environment = os.environ if environment is None else environment
    explicit = path is not None or "ECHO_CONFIG_FILE" in environment
    path = Path(path) if path is not None else config_path(environment)
    if not explicit and not path.exists():
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
    return document
