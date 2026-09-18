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

    def create(self, workspace: Path, config: dict, parent_id=None) -> str:
        key = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO sessions(id,parent_id,workspace,config) VALUES(?,?,?,?)",
                (key, parent_id, str(workspace), json.dumps(config)),
            )
        return key

    def session(self, key: str) -> dict:
        row = self.db.execute("SELECT * FROM sessions WHERE id=?", (key,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown session: {key}")
        return dict(row)

    def sessions(self) -> list[dict]:
        return [dict(r) for r in self.db.execute("SELECT * FROM sessions ORDER BY created DESC")]

    def add(self, key: str, message: dict):
        with self.db:
            self.db.execute(
                "INSERT INTO messages(session_id,payload) VALUES(?,?)", (key, json.dumps(message))
            )

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
def workspace_lock(workspace):
    """Only one CLI process may recover or change a workspace at a time."""
    with (workspace.parent / "workspace.lock").open("a") as lock:
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
