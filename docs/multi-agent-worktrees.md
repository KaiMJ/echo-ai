# Concurrency & Multi-Agent Execution: Git Worktrees & AST Locking

> **Planning decision:** Concurrency is a later coding-agent milestone. Start with ordinary Git three-way merges and validate every integration, including clean merges. The AST design below is an experiment, not a prerequisite or a measured performance result. Worktrees separate checkouts; Docker and mount policy provide the development execution boundary.

## 1. Concurrency Isolation via Git Worktrees

When multiple autonomous agents (or an agent and a developer) collaborate on the same repository, sharing a single working directory causes race conditions, corrupted syntax, and broken test environments.

Echo plans to use Git worktrees for separate agent checkouts. Measure creation time and disk usage on actual repositories.

```
                              Primary Git Repository
                           Branch: `main` (Developer HUD)
                                        │
           ┌────────────────────────────┴────────────────────────────┐
           ▼                                                         ▼
Worktree: `.echo/worktrees/w1`              Worktree: `.echo/worktrees/w2`
Branch: `echo/feature-auth`                 Branch: `echo/feature-billing`
Agent 1: Auth Specialist                   Agent 2: Billing Specialist
Isolated tests, bash, and builds            Isolated tests, bash, and builds
```

### Key Advantages
1. **Shared Object Database**: Worktrees share Git objects but maintain separate checked-out files.
2. **Creation Cost**: Measure checkout time rather than assuming a fixed latency.
3. **Separate Workspaces**: Run build tools and tests in a disposable Docker workspace with explicit mounts. A worktree alone does not constrain shell access.

---

## 2. Low-Latency Merge Pipeline: Fast-Path vs. Slow-Path

Git three-way merges can handle many non-overlapping edits, including line shifts. Measure actual conflicts before building an AST alternative. Non-overlapping syntax changes can still introduce semantic conflicts.

Echo implements a **Two-Tier AST Merge Architecture**:

```
                       Multiple Concurrent Agent Edits
                                     │
                     ┌───────────────▼───────────────┐
                     │   Tree-sitter AST Partition   │
                     │ (Parses function/class nodes) │
                     └───────────────┬───────────────┘
                                     │
                     Do target AST node ranges overlap?
                                     │
                     NO ─────────────┴───────────── YES (Overlapping conflict)
                     │                              │
                     ▼                              ▼
        FAST-PATH: Patch Application           SLOW-PATH: Arbiter Agent
        - Merges non-overlapping nodes         - Feeds 3-way conflict + intents
        - Latency: < 5 milliseconds            - Synthesizes combined code
        - Zero LLM token cost                  - Runs test suite in worktree
                     │                              │
                     └───────────────┬──────────────┘
                                     ▼
                        Validate Integrated Result
```

### A. Fast-Path: AST-Level Symbol Locking (Tree-sitter)
* Before subagents execute, the Planner Agent passes target files through **Tree-sitter**.
* Tree-sitter maps the file into an Abstract Syntax Tree (AST):
  - `ClassDef: UserProfile` (Lines 12–50)
  - `ClassDef: BillingManager` (Lines 75–120)
* Agent A is granted an AST lock on `UserProfile`.
* Agent B is granted an AST lock on `BillingManager`.
* Because their AST coordinate trees are orthogonal, Echo applies their respective patches programmatically in **under 5 milliseconds** without calling an LLM.

### B. Slow-Path: The Arbiter Agent
If two agents legitimately edit the exact same function or symbol:
1. Git produces standard conflict markers (`<<<<<<< HEAD`, `=======`, `>>>>>>>`).
2. The **Arbiter Agent** is invoked with:
   - The common ancestor version.
   - Agent A's goal & diff.
   - Agent B's goal & diff.
   - Conflicting markers.
3. The Arbiter synthesizes a unified implementation.
4. **Verification Gate**: The Arbiter triggers the local test runner (`pytest` or `npm test`) inside the ephemeral worktree.
5. If tests pass, the branch is integrated. If tests fail, it rolls back and alerts the developer.

All proposed integration paths must validate the combined result before accepting it. A clean Git or AST merge is not evidence that shared interfaces remain correct. Preserve the previous state and report failures; define the final application/review policy during the concurrency milestone.
