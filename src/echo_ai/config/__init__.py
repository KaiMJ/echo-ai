"""Runtime configuration: environment > model preferences > YAML > packaged defaults."""

from dataclasses import dataclass
from pathlib import Path

from echo_ai.config.file import load_environment, read_document, yaml_values
from echo_ai.config.settings import RuntimeSettings
from echo_ai.config.theme import Theme


@dataclass(frozen=True)
class Config(RuntimeSettings):
    @classmethod
    def from_env(cls):
        from echo_ai.config.resolver import resolve

        return resolve(cls)


def state_path(environment=None) -> Path:
    environment = load_environment() if environment is None else environment
    return Path(environment.get("ECHO_STATE_DIR", "~/.local/share/echo-ai")).expanduser()


def state_dir() -> Path:
    path = state_path()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def load_theme():
    """Appearance always comes from the current config, including on session resume."""
    document = read_document(environment=load_environment())
    theme = Theme.from_mapping(document.pop("theme", {}))
    yaml_values(document)
    return theme
