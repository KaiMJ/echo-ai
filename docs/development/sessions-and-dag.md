# Sessions & Context Engine: Directed Acyclic Graph (DAG) State Model

## 1. The Problem with Linear Session Histories

Most agent harnesses store conversation history as a flat array:
```json
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."},
  {"role": "assistant", "content": "..."}
]
```

Echo aims to retain alternative conversation branches, associate them with code checkpoints, and preserve important constraints when assembling a bounded context window. Conversation history and workspace state must be tracked separately.

---

## 2. Echo's DAG Session Architecture

In Echo, every turn is an immutable node in a **Directed Acyclic Graph (DAG)** stored in SQLite. Each node points to its `parent_id`.

```text
                  [Node 0: System Prompt]
                             │
                  [Node 1: User Query]
                             │
               [Node 2: Assistant Plan & Tools]
                   /                      \
      [Node 3a: Refactor via AST]    [Node 3b: Alternative regex approach]
                  │                              │
      [Node 4a: Tests failed]        [Node 4b: Tests passed! (ACTIVE HEAD)]
```

### SQLite Schema (`echo/core/session.py`)

```sql
CREATE TABLE IF NOT EXISTS session_nodes (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    parent_id TEXT,
    branch_name TEXT DEFAULT 'main',
    role TEXT NOT NULL, -- 'system', 'user', 'assistant', 'tool'
    content TEXT,
    tool_calls JSON,
    tool_call_id TEXT,
    model_used TEXT,
    token_count INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(parent_id) REFERENCES session_nodes(id)
);

CREATE INDEX IF NOT EXISTS idx_session_parent ON session_nodes(session_id, parent_id);
```

### Branching and Rollback Mechanics
* **`echo fork <node_id> [new_branch_name]`**: Creates a new pointer child from `<node_id>`. Context prior to `<node_id>` is preserved; context after it is left on the other branch.
* **`echo checkout <branch_name>`**: Switches the active conversation head; it does not implicitly restore code.
* **`echo log --tree`**: Visualizes the conversation tree in Ghostty using Unicode ASCII connectors.

---

### Planned Restore Modes

- **Conversation only:** switch the active conversation head and re-read the current workspace before continuing.
- **Code only:** restore a selected workspace checkpoint and record that action in the current conversation.
- **Conversation and code:** restore the associated checkpoint and conversation head as a coordinated operation.

The schema above is a sketch; checkpoint references, active branch heads, and restore operation state still need to be designed during M2. Define checkpoint timing and coverage for tracked files, untracked files, deletions, and unsaved editor buffers. Preserve newer user changes or surface a conflict before restoration. Stop active writes during restore and make interrupted restores recoverable before exposing combined restore.

A checkpoint does not reverse network requests, published changes, or other external effects. Keep recovery snapshots outside generated tools' writable reach so an accidental deletion cannot erase both the workspace and its recovery data.

## 3. Structured Context Compaction Engine

When the active branch context exceeds **70% of the model's token watermark**, Echo runs an automated compaction pass:

```
Watermark Breached (> 70% Context)
                │
                ▼
┌────────────────────────────────────────────────────────┐
│ 1. PARTITION CONTEXT WINDOW                            │
│ - Preserved Window: Last N turns (active working set)  │
│ - Compaction Window: All preceding historical turns    │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ 2. STRUCTURED STATE EXTRACTION (System 2 Pass)         │
│ Generates a strict schema:                             │
│ - Primary Goal & Objective                             │
│ - Architecture Decisions Made                          │
│ - Constraints & Edge Cases Discovered                  │
│ - Files Read, Created, or Modified                     │
└───────────────────────┬────────────────────────────────┘
                        │
                        ▼
┌────────────────────────────────────────────────────────┐
│ 3. ATOMIC CHECKPOINT INJECTION                         │
│ Compacted turns are replaced in active prompt by       │
│ the checkpoint summary node, saving 60–80% tokens.     │
│ (Original nodes remain safely preserved in SQLite).    │
└────────────────────────────────────────────────────────┘
```

### Intent Preservation
Structured summaries aim to preserve concrete developer facts, but may lose information. Evaluate constraint retention separately from test success and retain original history for retrieval:
```markdown
### [Echo Context Checkpoint - Turns 1 to 14 Compacted]
* **Target Objective**: Migrate SQLite driver from synchronous sqlite3 to aiosqlite.
* **Architectural Decisions**:
  - Connection pooling configured via asynccontextmanager.
  - Foreign key constraints explicitly enabled via PRAGMA foreign_keys = ON.
* **Files Touched**:
  - Modified: `echo/core/session.py`, `tests/test_session.py`
  - Created: `echo/core/db.py`
* **Pending Task**: Complete test migration in `test_branching()`.
```
