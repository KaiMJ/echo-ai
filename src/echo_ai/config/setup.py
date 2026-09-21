"""Portable starter configuration and validated, atomic edits."""

import os
import shlex
import shutil
import subprocess
import tempfile
from importlib.resources import files
from pathlib import Path

from echo_ai.config.file import config_dir, read_document, yaml_values
from echo_ai.config.settings import RuntimeSettings
from echo_ai.config.theme import Theme


def validate(path):
    document = read_document(path, use_environment=False)
    Theme.from_mapping(document.pop("theme", {}))
    RuntimeSettings(**yaml_values(document))


def backup(path):
    descriptor, name = tempfile.mkstemp(prefix=path.name + ".backup-", dir=path.parent)
    with os.fdopen(descriptor, "wb") as output:
        output.write(path.read_bytes())
    return Path(name)


def write_config(path, content, *, replace=False):
    """Validate beside the destination so relative model profiles keep their meaning."""
    descriptor, name = tempfile.mkstemp(suffix=".yaml", prefix=".echo-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w") as output:
            output.write(content)
        validate(temporary)
        saved = backup(path) if path.exists() and replace else None
        if replace:
            os.replace(temporary, path)
        else:
            # A concurrent setup must not overwrite another process's configuration.
            os.link(temporary, path)
        return saved
    finally:
        temporary.unlink(missing_ok=True)


def setup(*, edit=False, reset=False, path=None):
    """Only an explicit path allows setup to modify project/development settings."""
    path = Path(path).expanduser().absolute() if path else config_dir() / "echo.yaml"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    templates = files("echo_ai.config") / "templates"
    saved = None
    if not path.exists() or reset:
        content = (templates / "echo.yaml").read_text()
        saved = write_config(path, content, replace=reset)
    if edit:
        editor = shlex.split(os.getenv("VISUAL") or os.getenv("EDITOR") or "vi")
        if not editor or shutil.which(editor[0]) is None:
            raise ValueError("Set EDITOR to an installed editor, then run echo-ai setup --edit.")
        descriptor, name = tempfile.mkstemp(prefix=".echo-edit-", suffix=".yaml", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(path.read_text())
            result = subprocess.run([*editor, str(temporary)], check=False)
            if result.returncode:
                raise ValueError("Editor exited unsuccessfully; configuration was preserved.")
            content = temporary.read_text()
            if content != path.read_text():
                try:
                    saved = write_config(path, content, replace=True)
                except ValueError as error:
                    recovery = backup(temporary)
                    raise ValueError(f"{error}. Original preserved; edited draft: {recovery}") from error
        finally:
            temporary.unlink(missing_ok=True)
    validate(path)
    return path, saved
