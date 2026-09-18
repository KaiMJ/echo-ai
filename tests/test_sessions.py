import json
import sqlite3

import pytest

from echo_ai.runtime.store import Store


def test_migrate_old_sessions_without_changing_mode(tmp_path):
    path = tmp_path / "state.db"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE sessions (id TEXT PRIMARY KEY, parent_id TEXT, "
            "workspace TEXT NOT NULL, config TEXT NOT NULL, created TEXT NOT NULL)"
        )
        db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?)",
            ("old", None, "/workspace", json.dumps({}), "2026-01-01 00:00:00"),
        )
    store = Store(path)
    assert store.session("old")["mode"] == "sandbox"
    assert store.session("old")["updated"] == "2026-01-01 00:00:00"
    assert store.resolve("old")["id"] == "old"
    assert store.sessions()[0]["turns"] == 0
    store.close()
    Store(path).close()


def test_latest_is_repository_scoped_and_excludes_children(tmp_path):
    store = Store(tmp_path / "state.db")
    repo = tmp_path / "repo"
    first = store.create(repo, {}, repo=repo, mode="local", state_path=tmp_path)
    second = store.create(repo, {}, repo=repo)
    store.add(first, {"role": "user", "content": "Fix\n  the bug"})
    # Give explicit timestamps so this test does not depend on clock resolution.
    store.db.execute("UPDATE sessions SET updated='2099-01-01' WHERE id=?", (first,))
    child = store.create(repo, {}, first)
    store.create(tmp_path / "other", {}, repo=tmp_path / "other")
    assert store.resolve("latest", repo)["id"] == first
    assert store.resolve(second[:8])["id"] == second
    assert store.session(child)["mode"] == "local"
    assert store.session(child)["state_path"] == str(tmp_path)
    assert store.session(first)["title"] == "Fix the bug"
    assert store.sessions(repo, include_children=False)[0]["turns"] == 1
    with pytest.raises(ValueError, match="No sessions"):
        store.resolve("latest", tmp_path / "missing")
    with pytest.raises(ValueError, match="Ambiguous"):
        store.resolve("")
    store.close()
