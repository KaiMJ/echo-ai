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


def test_empty_sessions_are_reusable_but_never_latest(tmp_path):
    store = Store(tmp_path / "state.db")
    try:
        active = store.create(tmp_path, {}, repo=tmp_path)
        store.add(active, {"role": "user", "content": "Actual work"})
        empty = store.create(tmp_path, {}, repo=tmp_path)
        old_updated = store.session(empty)["updated"]
        store.create(tmp_path, {}, repo=tmp_path, mode="local")
        store.create(tmp_path, {}, repo=tmp_path / "other")
        assert store.resolve("latest", tmp_path)["id"] == active
        assert [s["id"] for s in store.empty_sessions(tmp_path, "sandbox")] == [empty]
        assert store.prepare_empty(empty, {"max_steps": 12})
        assert store.session(empty)["updated"] == old_updated
        assert json.loads(store.session(empty)["config"]) == {"max_steps": 12}
        assert store.resolve(empty)["id"] == empty
        store.start(empty)
        assert not store.empty_sessions(tmp_path, "sandbox")
        assert not store.prepare_empty(empty, {})
        assert not store.prepare_empty(active, {})
    finally:
        store.close()


def test_latest_without_activity_does_not_pick_empty_session(tmp_path):
    store = Store(tmp_path / "state.db")
    try:
        store.create(tmp_path, {}, repo=tmp_path)
        with pytest.raises(ValueError, match="No sessions with activity"):
            store.resolve("latest", tmp_path)
    finally:
        store.close()


def test_session_listing_places_latest_at_bottom(tmp_path):
    from io import StringIO

    from rich.console import Console

    from echo_ai.ui.commands import sessions_panel, sessions_text

    store = Store(tmp_path / "state.db")
    try:
        older = store.create(tmp_path, {}, repo=tmp_path)
        newer = store.create(tmp_path, {}, repo=tmp_path)
        store.db.execute("UPDATE sessions SET updated='2000-01-01' WHERE id=?", (older,))
        text = sessions_text(store, tmp_path)
        assert text.index(older) < text.index(newer)
        output = StringIO()
        Console(file=output, width=100).print(sessions_panel(store, tmp_path))
        assert output.getvalue().index(older) < output.getvalue().index(newer)
    finally:
        store.close()
