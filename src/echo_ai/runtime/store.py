"""SQLite transcript and execution state. No side effects are replayed on resume."""

import json
import sqlite3
import uuid
from pathlib import Path

from .locking import workspace_lock

__all__ = ["Store", "workspace_lock"]


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
            CREATE TABLE IF NOT EXISTS tool_changes (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES sessions(id),
                run_id TEXT NOT NULL REFERENCES runs(id),
                tool_call_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                before_ref TEXT NOT NULL,
                after_ref TEXT NOT NULL,
                patch TEXT NOT NULL,
                checkout TEXT,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        """)

        columns = {row[1] for row in self.db.execute("PRAGMA table_info(sessions)")}
        for name, definition in {
            "repo": "TEXT",
            "mode": "TEXT NOT NULL DEFAULT 'sandbox'",
            "state_path": "TEXT",
            "title": "TEXT NOT NULL DEFAULT ''",
            "updated": "TEXT",
            "active_head": "INTEGER",
            "redo_head": "INTEGER",
            "checkout": "TEXT",
            "needs_workspace_sync": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                self.db.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")
        message_columns = {row[1] for row in self.db.execute("PRAGMA table_info(messages)")}
        if "parent_id" not in message_columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN parent_id INTEGER")
            previous = {}
            for row in self.db.execute("SELECT id,session_id FROM messages ORDER BY id"):
                self.db.execute(
                    "UPDATE messages SET parent_id=? WHERE id=?",
                    (previous.get(row["session_id"]), row["id"]),
                )
                previous[row["session_id"]] = row["id"]
            for session_id, head in previous.items():
                self.db.execute(
                    "UPDATE sessions SET active_head=? WHERE id=? AND active_head IS NULL",
                    (head, session_id),
                )
        run_columns = {row[1] for row in self.db.execute("PRAGMA table_info(runs)")}
        for name in ("start_head", "end_head"):
            if name not in run_columns:
                self.db.execute(f"ALTER TABLE runs ADD COLUMN {name} INTEGER")
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
        checkout=None,
    ) -> str:
        if parent_id:
            parent = self.session(parent_id)
            repo, mode, state_path = parent["repo"], parent["mode"], parent["state_path"]
            checkout = parent["checkout"]
        key = uuid.uuid4().hex[:12]
        with self.db:
            self.db.execute(
                "INSERT INTO sessions(id,parent_id,workspace,config,repo,mode,state_path,checkout,updated) "
                "VALUES(?,?,?,?,?,?,?,?,strftime('%Y-%m-%d %H:%M:%f','now'))",
                (
                    key,
                    parent_id,
                    str(workspace),
                    json.dumps(config),
                    str(repo) if repo else None,
                    mode,
                    str(state_path) if state_path else None,
                    checkout,
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
            matches = [s for s in self.sessions(repo, include_children=False) if s["turns"] > 0]
            if not matches:
                raise ValueError(
                    "No sessions with activity for this repository. Start with echo-ai chat."
                )
            return matches[0]
        matches = [s for s in self.sessions() if s["id"].startswith(pointer)]
        if not matches:
            raise ValueError(f"Unknown session: {pointer}")
        if len(matches) != 1:
            raise ValueError(f"Ambiguous session: {pointer}; use a longer ID")
        return matches[0]

    def empty_sessions(self, repo, mode):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM sessions WHERE repo=? AND mode=? AND parent_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM messages WHERE session_id=sessions.id) "
                "AND NOT EXISTS (SELECT 1 FROM runs WHERE session_id=sessions.id) "
                "AND NOT EXISTS (SELECT 1 FROM sessions child WHERE child.parent_id=sessions.id) "
                "ORDER BY updated DESC, rowid DESC",
                (str(Path(repo).resolve()), mode),
            )
        ]

    def prepare_empty(self, key, config):
        """Refresh new-session defaults under the workspace lock, without bumping activity."""
        with self.db:
            result = self.db.execute(
                "UPDATE sessions SET config=? WHERE id=? AND parent_id IS NULL "
                "AND NOT EXISTS (SELECT 1 FROM messages WHERE session_id=sessions.id) "
                "AND NOT EXISTS (SELECT 1 FROM runs WHERE session_id=sessions.id) "
                "AND NOT EXISTS (SELECT 1 FROM sessions child WHERE child.parent_id=sessions.id)",
                (json.dumps(config), key),
            )
        return result.rowcount == 1

    def add(self, key: str, message: dict):
        with self.db:
            head = self.db.execute(
                "SELECT active_head FROM sessions WHERE id=?", (key,)
            ).fetchone()[0]
            inserted = self.db.execute(
                "INSERT INTO messages(session_id,payload,parent_id) VALUES(?,?,?)",
                (key, json.dumps(message), head),
            )

            self.db.execute(
                "UPDATE sessions SET active_head=?,redo_head=NULL,"
                "updated=strftime('%Y-%m-%d %H:%M:%f','now') WHERE id=?",
                (inserted.lastrowid, key),
            )
            if message.get("role") == "user":
                title = " ".join(str(message.get("content", "")).split())[:80]
                self.db.execute("UPDATE sessions SET title=? WHERE id=? AND title=''", (title, key))

    def messages(self, key: str) -> list[dict]:
        head = self.session(key)["active_head"]
        messages = []
        while head is not None:
            row = self.db.execute(
                "SELECT payload,parent_id FROM messages WHERE id=? AND session_id=?", (head, key)
            ).fetchone()
            if row is None:
                raise ValueError("Conversation branch is incomplete")
            messages.append(json.loads(row["payload"]))
            head = row["parent_id"]
        return list(reversed(messages))

    def active_head(self, key):
        return self.session(key)["active_head"]

    def move_head(self, key, head, *, redo=None):
        if head is not None and self.db.execute(
            "SELECT 1 FROM messages WHERE id=? AND session_id=?", (head, key)
        ).fetchone() is None:
            raise ValueError("Unknown conversation checkpoint")
        with self.db:
            self.db.execute(
                "UPDATE sessions SET active_head=?,redo_head=?,needs_workspace_sync=1 WHERE id=?",
                (head, redo, key),
            )

    def clear_workspace_sync(self, key):
        with self.db:
            self.db.execute("UPDATE sessions SET needs_workspace_sync=0 WHERE id=?", (key,))

    def record_tool_change(
        self, session_id, run_id, call_id, name, before, after, patch, checkout=None
    ):
        with self.db:
            self.db.execute(
                "INSERT INTO tool_changes(session_id,run_id,tool_call_id,tool_name,"
                "before_ref,after_ref,patch,checkout) VALUES(?,?,?,?,?,?,?,?)",
                (session_id, run_id, call_id, name, before, after, patch, checkout),
            )

    def tool_changes(self, session_id):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM tool_changes WHERE session_id=? ORDER BY id", (session_id,)
            )
        ]

    def active_tool_changes(self, session_id):
        """Changes made by runs whose user turn is on the active branch."""
        head = self.active_head(session_id)
        lineage = set()
        while head is not None:
            lineage.add(head)
            head = self.parent_head(session_id, head)
        if not lineage:
            return []
        markers = ",".join("?" for _ in lineage)
        return [
            dict(row) for row in self.db.execute(
                "SELECT tool_changes.* FROM tool_changes "
                "JOIN runs ON runs.id=tool_changes.run_id "
                f"WHERE tool_changes.session_id=? AND runs.start_head IN ({markers}) "
                "ORDER BY tool_changes.id",
                (session_id, *lineage),
            )
        ]

    def start(self, key: str) -> str:
        run = uuid.uuid4().hex
        with self.db:
            self.db.execute(
                "INSERT INTO runs(id,session_id,status,start_head) VALUES(?,?,'running',?)",
                (run, key, self.active_head(key)),
            )
        return run

    def finish(self, run: str, status: str, metrics: dict):
        with self.db:
            row = self.db.execute("SELECT session_id FROM runs WHERE id=?", (run,)).fetchone()
            self.db.execute(
                "UPDATE runs SET status=?,metrics=?,end_head=? WHERE id=?",
                (status, json.dumps(metrics), self.active_head(row[0]), run),
            )

    def latest_completed_run(self, key):
        head = self.active_head(key)
        row = self.db.execute(
            "SELECT * FROM runs WHERE session_id=? AND status='completed' AND end_head=? "
            "ORDER BY rowid DESC LIMIT 1", (key, head)
        ).fetchone()
        return dict(row) if row else None

    def run_ending_at(self, key, head):
        row = self.db.execute(
            "SELECT * FROM runs WHERE session_id=? AND status='completed' AND end_head=? "
            "ORDER BY rowid DESC LIMIT 1", (key, head)
        ).fetchone()
        return dict(row) if row else None

    def parent_head(self, key, head):
        row = self.db.execute(
            "SELECT parent_id FROM messages WHERE id=? AND session_id=?", (head, key)
        ).fetchone()
        if row is None:
            raise ValueError("Unknown conversation checkpoint")
        return row[0]

    def changes_for_run(self, run_id):
        return [
            dict(row) for row in self.db.execute(
                "SELECT * FROM tool_changes WHERE run_id=? ORDER BY id", (run_id,)
            )
        ]

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
