# Lifecycle Hooks: Pre-Hooks & Post-Hooks Architecture

## 1. Overview: The Interceptor Pattern

In production software engineering, agents must not operate as unconstrained black boxes. Deterministic interception points are required for **security guardrails, PII/secret redaction, auto-formatting, and compliance logging**.

`echo-ai` implements a comprehensive **Lifecycle Hook Pipeline** inspired by Git hooks and web middleware:

```text
                            User Turn Begins
                                   │
                     ┌─────────────▼─────────────┐
                     │     PRE-TURN HOOKS        │  (Session snapshotting, env validation)
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │    PRE-PROMPT HOOKS       │  (Secret scanning, PII redaction, context injection)
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │   System 1 & 2 Inference  │
                     └─────────────┬─────────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │    POST-PROMPT HOOKS      │  (Hallucination audit, token accounting)
                     └─────────────┬─────────────┘
                                   │
                             Is Tool Called?
                                   │
                     YES ──────────┴────────── NO
                     │                         │
      ┌──────────────▼──────────────┐          │
      │    PRE-TOOL-CALL HOOKS      │          │
      │  (Permission gate, Jev      │          │
      │   destructive safety check) │          │
      └──────────────┬──────────────┘          │
                     │ (Allowed?)              │
      ┌──────────────▼──────────────┐          │
      │     Tool Execution          │          │
      │   (Isolated Worktree)       │          │
      └──────────────┬──────────────┘          │
                     │                         │
      ┌──────────────▼──────────────┐          │
      │    POST-TOOL-CALL HOOKS     │          │
      │  (Auto-format ruff/prettier,│          │
      │   log artifact, test-lint)  │          │
      └──────────────┬──────────────┘          │
                     │                         │
                     └─────────────┬───────────┘
                                   │
                     ┌─────────────▼─────────────┐
                     │     POST-TURN HOOKS       │  (Git auto-commit draft, statusline refresh)
                     └───────────────────────────┘
```

---

## 2. Hook Interceptor Protocol (`echo/core/hooks.py`)

All hooks inherit from a standardized abstract interface supporting **Short-Circuiting**, **Payload Modification**, and **Asynchronous Execution**:

```python
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel

class HookDecision(str, Enum):
    CONTINUE = "continue"    # Proceed normally
    MODIFY = "modify"        # Mutate payload and proceed
    BLOCK = "block"          # Abort execution immediately and alert user

class HookResult(BaseModel):
    decision: HookDecision = HookDecision.CONTINUE
    modified_payload: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None

class BaseHook:
    name: str
    priority: int = 100  # Lower numbers run first

    async def execute(self, event_type: str, payload: Dict[str, Any]) -> HookResult:
        raise NotImplementedError
```

---

## 3. High-Value Hook Implementations

### A. Pre-Prompt Hook: `SecretScannerHook`
* **Trigger**: Fires before any prompt or file context is dispatched to the LLM.
* **Function**: Scans for AWS access keys, OpenAI keys, JWT tokens, and private SSH keys using regex and entropy analyzers.
* **Action**: Redacts secrets to `<REDACTED_API_KEY>` before transmission, reducing accidental credential disclosure; this is not a guarantee of detecting every secret.

### B. Pre-Tool-Call Hook: `DestructiveCommandGateHook`
* **Trigger**: Fires immediately before `run_bash` or `write_file`.
* **Function**: Passes command to System 1 (Jev) and regex blocklists (`rm -rf`, `DROP TABLE`, `git push --force`).
* **Action**: If flagged, returns `HookDecision.BLOCK` and displays an interactive approval prompt in the CLI.

### C. Post-Tool-Call Hook: `AutoLintFormatHook`
* **Trigger**: Fires immediately after `edit_chunk` or `write_file` modifies a file.
* **Function**: Runs language-specific formatters and linters (`ruff format` for Python, `prettier` for TypeScript) inside the worktree.
* **Benefit**: Ensures the generated code strictly matches repo style conventions before the developer ever sees it.

### D. Post-Turn Hook: `TelemetryAndCostHook`
* **Trigger**: Fires when a turn finishes.
* **Function**: Calculates exact token usage, model pricing, latency, and cache hit metrics, updating the CLI status display and SQLite telemetry logs.

---

## 4. User-Defined Custom Hooks (`.echohooks.py`)

Developers can define project-specific hooks by placing a `.echohooks.py` file in their repository root:

```python
# .echohooks.py in project root
from echo.core.hooks import BaseHook, HookResult, HookDecision

class EnforceConventionalCommitsHook(BaseHook):
    name = "enforce_conventional_commits"

    async def execute(self, event_type: str, payload: dict) -> HookResult:
        if event_type == "pre_git_commit":
            commit_msg = payload.get("message", "")
            prefixes = ("feat:", "fix:", "docs:", "chore:", "refactor:", "test:")
            if not any(commit_msg.startswith(p) for p in prefixes):
                return HookResult(
                    decision=HookDecision.MODIFY,
                    modified_payload={"message": f"chore: {commit_msg}"},
                    reason="Automatically prefixed with conventional commit tag."
                )
        return HookResult(decision=HookDecision.CONTINUE)
```

For trusted development repositories, explicitly enabled project hooks run in tool workers inside Docker. Do not import generated or project hook code into the daemon. Hook failure, timeout, ordering, and payload validation behavior will be specified when the hook pipeline is implemented.
