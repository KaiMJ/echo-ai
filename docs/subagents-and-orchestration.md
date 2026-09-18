# Subagents & Orchestration: Hierarchical Swarms & Task DAGs

## 1. Orchestration Topologies

`echo-ai` avoids hardcoded, linear single-agent loops. Depending on task complexity, the runtime deploys one of three orchestration topologies:

```text
A. HIERARCHICAL (Default)         B. PIPELINE (Linear)         C. SWARM (Independent Parallel)
       [Planner Agent]             [Spec Agent]                 [Coordinator]
       /      |      \                  │                       /      |      \
 [Coder]   [Tester]  [Reviewer]    [Coder Agent]           [Worker 1][Worker 2][Worker 3]
       \      |      /                  │                       \      |      /
       [Arbiter Agent]             [Verifier Agent]              [Aggregator]
```

### 1. Hierarchical (Planner-Specialist)
* **Planner Agent**: Deconstructs user intent into a Directed Acyclic Graph (Task DAG) of sub-tasks.
* **Specialist Subagents**: Spawned inside isolated Git Worktrees (`.echo/worktrees/<task-id>`).
* **Arbiter Agent**: Reconciles concurrent worktree outputs and validates tests before committing to the main branch.

### 2. Pipeline (Deterministic Staged Flow)
* Step 1: Research & Discovery $\to$ Step 2: Architecture Spec $\to$ Step 3: Implementation $\to$ Step 4: Verification.

### 3. Swarm (High-Throughput Parallelism)
* Used for broad tasks like reviewing 20 pull requests or sifting 50 market earnings reports simultaneously.

---

## 2. Inter-Agent Communication: Typed Mailbox Protocol

Subagents do not communicate via freeform string concatenation. All messages pass through a typed **Agent Mailbox** over an async event queue:

```python
class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_id: str
    recipient_id: str  # Specific agent ID or "broadcast"
    message_type: str  # "task_request" | "task_complete" | "clarification" | "conflict_alert"
    payload: Dict[str, Any]
    timestamp: float
```

### The Task DAG (Dependency Graph)
When the Planner decomposes a project, it generates a dependency graph:

```python
class TaskNode(BaseModel):
    task_id: str
    description: str
    assigned_role: str        # e.g., "frontend_coder", "backend_coder", "tester"
    dependencies: List[str]   # Task IDs that must complete first
    status: str               # "pending" | "running" | "completed" | "failed"
    worktree_path: Optional[str] = None
```

If Task C depends on Task A and Task B:
* Task A (Database migration) and Task B (Frontend UI mock) run **concurrently in parallel Git Worktrees**.
* Task C (Integration testing) automatically wakes up only when both Task A and Task B emit `task_complete`.

---

## 3. Subagent Specialization Prompts & Boundaries

Subagents operate under strict role constraints to prevent cross-talk and token bloat:

| Role | Allowed Tools | Constraint |
| :--- | :--- | :--- |
| **Planner** | `read_file`, `grep_search`, `list_dir` | **Forbidden from writing or editing code**. Pure structural decomposition. |
| **Coder** | `edit_chunk`, `write_file`, `read_file` | Locked to specific AST nodes / file boundaries. |
| **Tester** | `execute_bash` (`pytest`, `npm test`) | Executes verification inside the isolated worktree sandbox. |
| **Arbiter** | `git_merge`, `tree_sitter_patch`, `execute_bash` | Resolves 3-way conflicts and verifies build integrity. |
