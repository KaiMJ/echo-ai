"""SQLite transcript and execution state. No side effects are replayed on resume."""

import fcntl
import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA foreign_keys=ON;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, parent_id TEXT REFERENCES sessions(id),
                workspace TEXT NOT NULL, config TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                status TEXT NOT NULL, metrics TEXT NOT NULL DEFAULT '{}',
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)

        columns = {row[1] for row in self.db.execute("PRAGMA table_info(sessions)")}
        for name, definition in {
            "repo": "TEXT",
            "mode": "TEXT NOT NULL DEFAULT 'sandbox'",
            "state_path": "TEXT",
            "title": "TEXT NOT NULL DEFAULT ''",
            "updated": "TEXT",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        self.db.execute(
            "UPDATE sessions SET updated=COALESCE((SELECT MAX(created) FROM runs "
            "WHERE session_id=sessions.id),created) WHERE updated IS NULL"
        )
        if "title" not in columns:
            for row in self.db.execute(
                "SELECT sessions.id, (SELECT json_extract(payload,'$.content') FROM messages "
                "WHERE session_id=sessions.id AND json_extract(payload,'$.role')='user' "
                "ORDER BY id LIMIT 1) AS prompt FROM sessions"
            ).fetchall():
                title = " ".join(str(row["prompt"] or "").split())[:80]
                self.db.execute("UPDATE sessions SET title=? WHERE id=?", (title, row["id"]))
        self.db.commit()

    def create(
        self,
        workspace: Path,
        config: dict,
        parent_id=None,
        *,
        repo=None,
        mode="sandbox",
        state_path=None,
    ) -> str:
        if parent_id:
            parent = self.session(parent_id)
            repo, mode, state_path = parent["repo"], parent["mode"], parent["state_path"]
        key = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO sessions(id,parent_id,workspace,config,repo,mode,state_path,updated) "
                "VALUES(?,?,?,?,?,?,?,strftime('%Y-%m-%d %H:%M:%f','now'))",
                (
                    key,
                    parent_id,
                    str(workspace),
                    json.dumps(config),
                    str(repo) if repo else None,
                    mode,
                    str(state_path) if state_path else None,
                ),
            )
        return key

    def session(self, key: str) -> dict:
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (key,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown session: {key}")
        return dict(row)

    def sessions(self, repo=None, *, include_children=True) -> list[dict]:
        clauses, params = [], []
        if repo is not None:
            clauses.append("repo=?")
            params.append(str(Path(repo).resolve()))
        if not include_children:
            clauses.append("parent_id IS NULL")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT sessions.*, (SELECT count(*) FROM messages "
                "WHERE session_id=sessions.id AND json_extract(payload,'$.role')='user') AS turns "
                "FROM sessions" + where + " ORDER BY updated DESC, rowid DESC",
                params,
            )
        ]

    def resolve(self, pointer, repo=None) -> dict:
        if pointer == "latest":
            matches = self.sessions(repo, include_children=False)
            if not matches:
                raise ValueError("No sessions for this repository. Start with echo-ai chat.")
            return matches[0]
        matches = [s for s in self.sessions() if s["id"].startswith(pointer)]
        if not matches:
            raise ValueError(f"Unknown session: {pointer}")
        if len(matches) != 1:
            raise ValueError(f"Ambiguous session: {pointer}; use a longer ID")
        return matches[0]

    def add(self, key: str, message: dict):
        with self.db:
            self.db.execute(
                "INSERT INTO messages(session_id,payload) VALUES(?,?)", (key, json.dumps(message))
            )

            self.db.execute(
                "UPDATE sessions SET updated=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=?",
                (key,),
            )
            if message.get("role") == "user":
                title = " ".join(str(message.get("content", "")).split())[:80]
                self.db.execute("UPDATE sessions SET title=? WHERE id=? AND title=''", (title, key))

    def messages(self, key: str) -> list[dict]:
        return [
            json.loads(r[0])
            for r in self.db.execute(
                "SELECT payload FROM messages WHERE session_id=? ORDER BY id", (key,)
            )
        ]

    def start(self, key: str) -> str:
        run = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO runs(id,session_id,status) VALUES(?,?,'running')", (run, key)
            )
        return run

    def finish(self, run: str, status: str, metrics: dict):
        with self.db:
            self.db.execute(
                "UPDATE runs SET status=?,metrics=? WHERE id=?", (status, json.dumps(metrics), run)
            )

    def recover(self, key: str):
        """Close incomplete tool exchanges without executing their commands again."""
        messages = self.messages(key)
        pending = {}
        for message in messages:
            if message["role"] == "assistant":
                pending.update({c["id"]: c for c in message.get("tool_calls", [])})
            elif message["role"] == "tool":
                pending.pop(message["tool_call_id"], None)
        for call_id in pending:
            self.add(
                key,
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(
                        {
                            "error": "Interrupted; outcome unknown. Inspect workspace before retrying."
                        }
                    ),
                },
            )
        with self.db:
            self.db.execute(
                "UPDATE runs SET status='interrupted' WHERE session_id=? AND status='running'",
                (key,),
            )

    def close(self):
        self.db.close()


@contextmanager
def workspace_lock(workspace, lock_path=None):
    """Only one CLI process may recover or change a workspace at a time."""
    with (lock_path or workspace.parent / "workspace.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError(
                "This workspace is open in another Echo process. Close it first."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
