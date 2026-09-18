# System 1: Instinct Engine (TypeSafe AI Jev Integration)

> Deferred experiment: routing/Jev is not part of the initial coding loop. Start with one configured Qwen model on vLLM. Performance figures below are hypotheses, not measured results.

## 1. The Dual-Process Paradigm

Cognitive psychology (Daniel Kahneman, *Thinking, Fast and Slow*) distinguishes between two distinct modes of human thought:
* **System 1**: Fast, instinctive, emotional, and non-deliberative.
* **System 2**: Slower, more deliberate, and logical.

In current agent architectures, developers force **high-capability models** to handle **System 1 tasks** (routing, intent classification, safety checks, and tool parameter validation). This creates massive latency bottlenecks (1,500ms–4,000ms) and token cost inflation.

**Echo couples TypeSafe AI’s Jev (System 1) with Frontier LLMs (System 2)** to create a biologically inspired cognitive pipeline:

| Property | Traditional Agent Loop | Echo Dual-Process Loop |
| :--- | :--- | :--- |
| **Router Latency** | 800ms – 2,000ms (Autoregressive LLM) | **70ms – 150ms (Jev Single Forward Pass)** |
| **Router Token Cost** | ~$0.15 / 1M tokens | **$0.042 / 1M tokens (Output tokens free)** |
| **Type Guarantees** | Prone to malformed JSON / regex failure | **Mathematically calibrated typed decisions** |
| **Safety Interception** | Post-hoc regex or slow prompt filters | **Sub-100ms non-autoregressive safety gate** |

---

## 2. API Contract & LiteLLM Pass-Through

Echo interacts with Jev via LiteLLM’s `/typesafe/v1/systemone` pass-through endpoint or directly via `https://api.typesafe.ai/v1/systemone`.

### A. Request Payload
A single Jev request evaluates multiple parallel questions over program state:

```json
{
  "model": "jev-latest",
  "state": "Active File: src/auth.py\nGit Diff: - token_exp = 900\n+ token_exp = 3600\nUser Prompt: Update the test suite to verify 1h token expiration.",
  "questions": {
    "domain": {
      "type": "choice",
      "instructions": "Classify target system domain.",
      "criteria": {
        "coding": "Software engineering, tests, file edits, bash",
        "market": "Stock tickers, financial research, crypto feeds",
        "personal": "Calendar, communication, personal notifications"
      }
    },
    "complexity": {
      "type": "choice",
      "instructions": "Determine reasoning depth required.",
      "criteria": {
        "trivial": "Typos, 1-line changes, formatting, simple queries",
        "standard": "Unit test generation, standard function refactoring",
        "frontier": "Multi-file architecture, debugging race conditions"
      }
    },
    "safety": {
      "type": "choice",
      "instructions": "Detect destructive or irreversible operations.",
      "criteria": {
        "safe": "Standard file reading, writing, and test execution",
        "destructive": "rm -rf, DROP TABLE, force push, exposing secrets"
      }
    }
  }
}
```

### B. Response Payload
```json
{
  "model": "jev-1.13.0",
  "answers": {
    "domain": { "type": "choice", "choice": "coding", "confidence": 0.99 },
    "complexity": { "type": "choice", "choice": "standard", "confidence": 0.91 },
    "safety": { "type": "choice", "choice": "safe", "confidence": 0.99 }
  },
  "usage": {
    "input_tokens": 85,
    "output_tokens": 18
  }
}
```

---

## 3. Applications Across Echo Subsystems

### 1. Sub-100ms Dynamic Model Routing
Based on Jev's `complexity` answer:
* `trivial` (confidence > 0.85) $\to$ Dispatches to the configured low-latency or local model.
* `standard` $\to$ Dispatches to the configured standard model.
* `frontier` $\to$ Dispatches to the configured high-capability model.

### 2. Zero-Latency Destructive Command Interceptor
Before executing any bash command in the execution sandbox:
* If Jev flags `safety == "destructive"`, the command is quarantined and an explicit human-in-the-loop confirmation modal is triggered in Neovim/Ghostty before execution.

### 3. Real-Time Financial News Sifter
For the market research agent:
* Jev evaluates 50 streaming news headlines concurrently in parallel requests.
* Classifies: `sentiment: [bullish, bearish, neutral]` and `actionable: [high, low]`.
* Only headlines scored `actionable == high` trigger deep synthesis in System 2.

### 4. DAG Node Pruning & Compaction Scoring
When session context approaches capacity:
* Jev scores each past turn's relevance to the active working branch ($0.0 \to 1.0$).
* Nodes scored $< 0.25$ are dropped from active prompt assembly without losing the underlying SQLite tree history.
