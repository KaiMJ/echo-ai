# Context Engineering: Dynamic Discovery & Smart Context Loading

## 1. The Context Inflation Problem

Traditional agents suffer from two context failure modes:
1. **Under-contextualization (Hallucination)**: The agent edits a file without understanding external caller signatures, leading to broken interfaces.
2. **Over-contextualization (Token Exhaustion & Degradation)**: The agent dumps whole files (often 10,000+ lines) into the prompt. This exhausts token budgets, breaks prompt caching, and degrades the model's instruction-following attention (*"Lost in the Middle"* problem).

**echo-ai** adopts a **Dynamic Context Discovery** architecture (inspired by Cursor's context engineering and Aider's AST repo maps).

```text
                             User Prompt in Terminal REPL
                                            │
                                            ▼
                  ┌──────────────────────────────────────────────────┐
                  │    System 1 (Jev): Fast Intent & Target Scope    │
                  │    Extracts: Target symbols, impacted subsystems │
                  └─────────────────────────┬────────────────────────┘
                                            │
                                            ▼
                  ┌──────────────────────────────────────────────────┐
                  │          Smart Context Loader Pipeline           │
                  ├──────────────────────────────────────────────────┤
                  │ 1. Tree-sitter Symbol Skeleton (Repo Map)        │
                  │    Only classes, functions, and type signatures  │
                  │ 2. Exact AST Chunk Slicing                       │
                  │    Load lines 40–85 of `auth.py`, not all 800    │
                  │ 3. Static Prefix Cache Alignment                 │
                  │    Stable prompt prefix for 90% cache hit rate   │
                  └─────────────────────────┬────────────────────────┘
                                            │
                                            ▼
                           Compact High-Signal Context
                           (2,500 tokens vs. 45,000 tokens)
```

---

## 2. The 3-Tier Context Assembly Engine

Instead of feeding full files, `echo-ai`'s `ContextLoader` assembles context hierarchically:

### Tier 1: The Tree-sitter Skeleton (Repo Map)
* Uses Tree-sitter to parse the entire codebase into a lightweight graph of identifiers:
  ```python
  # Repo Map Extract (Only 120 tokens for an entire module!)
  class SessionStore:
      def __init__(self, db_path: Path): ...
      async def add_turn(self, parent_id: str, role: str, content: str) -> str: ...
      async def get_branch(self, head_id: str) -> List[SessionNode]: ...
  ```
* Gives the LLM global topological awareness without loading thousands of lines of implementation code.

### Tier 2: Just-In-Time (JIT) AST Chunk Slicing
* When the agent needs to edit or inspect a function:
  * It does **not** load the whole 1,200-line file.
  * It slices the specific AST node (`FunctionDef: verify_jwt`) plus 10 lines of parent context.

### Tier 3: Artifact-ized Tool Outputs
* Instead of dumping raw 5,000-line compiler logs or terminal outputs into the context window:
  * Echo-AI writes raw tool output to a temporary scratch file on disk (`.echo/scratch/build.log`).
  * The context window only receives a structured 5-line synopsis:
    `[Test Failed: 2 errors in tests/test_session.py:42. Traceback preview: ... Full log: .echo/scratch/build.log]`

---

## 3. Prompt Cache Alignment Strategy

Some model providers offer **Prompt Caching** for identical prompt prefixes. Support, pricing, and latency benefits depend on the configured provider and model; measure them for Echo workloads.

`echo-ai` guarantees prompt cache stability:
1. **Zero Dynamic Headers**: Dynamic timestamps, random session IDs, and git branch names are forbidden in the top 2,000 tokens.
2. **Stable Block Ordering**:
   ```text
   [Static Core Instructions]    <--- 100% CACHED (Never changes)
   [System Tool Definitions]     <--- 100% CACHED
   [Project Rules: .echorules]   <--- 100% CACHED
   ------------------------------ CACHE CHECKPOINT
   [Active Repo Map Skeleton]    <--- Semi-stable
   [Compacted DAG State]         <--- Compacted incrementally
   [Active User Turn & Slice]    <--- Dynamic (at the bottom)
   ```
