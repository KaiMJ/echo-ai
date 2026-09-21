"""Never load developer credentials or preferences during automated tests."""

import os

import pytest


@pytest.fixture(autouse=True)
def isolated_user_state(tmp_path, monkeypatch):
    for name in list(os.environ):
        if name.startswith("ECHO_") or name == "XAI_API_KEY":
            monkeypatch.delenv(name)
    credential_file = tmp_path / "test-credentials.env"
    credential_file.write_text("")
    monkeypatch.setenv("ECHO_ENV_FILE", str(credential_file))
    monkeypatch.setenv("ECHO_STATE_DIR", str(tmp_path / "echo-state"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "user-config"))
    monkeypatch.setenv("HOME", str(tmp_path))
