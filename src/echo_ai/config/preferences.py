"""Model preferences stored alongside session state."""

import yaml

from echo_ai.config import state_path
from echo_ai.config.file import yaml_values
from echo_ai.config.settings import MODEL_FIELDS, RuntimeSettings
from echo_ai.config.setup import write_config


def preferences_path(environment=None):
    return state_path(environment) / "model.yaml"


def read_preferences(environment=None):
    path = preferences_path(environment)
    if not path.exists():
        return {}
    try:
        document = yaml.safe_load(path.read_text())
        values = yaml_values(document, {"local-model": {k: k for k in MODEL_FIELDS}})
        validate_preferences(values)
        return values
    except (OSError, yaml.YAMLError, TypeError, ValueError) as error:
        raise ValueError(f"Cannot load model preferences {path}: {error}") from error


def validate_preferences(values):
    if not isinstance(values, dict) or values.keys() - MODEL_FIELDS:
        raise ValueError("Model preferences must contain only model settings")
    RuntimeSettings(**values)


def save_preferences(config):
    values = {name: getattr(config, name) for name in MODEL_FIELDS}
    if getattr(config, "sources", {}).get("base_url") == "local inference port":
        values.pop("base_url")
    path = preferences_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Atomic replacement; ordinary model selection does not accumulate backup files.
    write_config(path, yaml.safe_dump({"local-model": values}, sort_keys=True),
                 replace=True, keep_backup=False)
