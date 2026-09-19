# Models and local inference

Echo uses the **LiteLLM Python SDK** in its own process, installed by
`uv sync --locked`. Docker runs vLLM. There is no LiteLLM proxy or proxy config.

## Where settings live

| File                | Responsibility                                              |
| ------------------- | ----------------------------------------------------------- |
| `models/qwen.yaml`  | All Qwen request settings and its `deployment` section      |
| `models/gemma.yaml` | All Gemma request settings and its `deployment` section     |
| `echo.yaml`         | Selected `model-profile` and shared agent/tool/UI settings  |
| `.env`              | Machine-specific cache paths and credentials                |
| `compose.yaml`      | Shared Docker resources, pinned vLLM image and health check |
| `models/manage.py`  | Reads a model profile, validates files, and invokes Compose |

## Start or switch models

```bash
uv sync --locked
uv run python models/manage.py qwen check
uv run python models/manage.py qwen up
uv run echo-ai doctor
uv run echo-ai
```

```bash
uv run python models/manage.py qwen config  # review the complete Compose config
uv run python models/manage.py qwen status
uv run python models/manage.py qwen logs
uv run python models/manage.py qwen stop

uv run python models/manage.py gemma up
ECHO_MODEL_PROFILE=models/gemma.yaml uv run echo-ai doctor
ECHO_MODEL_PROFILE=models/gemma.yaml uv run echo-ai
```

## Output and context limits

Both profiles use:

```yaml
context_tokens: 262144
max_tokens: 65536
deployment:
  max_num_seqs: 1
```

`max_tokens` is the **maximum output per model turn**, including reasoning and
final text/tool calls.

## Reasoning and sampling

```bash
ECHO_REASONING_EFFORT=xhigh uv run echo-ai
ECHO_MAX_TOKENS=32768 uv run echo-ai
```

Relative profile paths resolve next to `echo.yaml`. Docker settings come directly
from the profile; client overrides do not silently change server capacity.

## Verification

```bash
uv run python tests/integration/smoke_inference.py
uv run python tests/integration/smoke_sdk.py --profile qwen --no-thinking
uv run python tests/integration/smoke_sdk.py --profile qwen --effort low
uv run python tests/integration/smoke_sdk.py --profile qwen --effort medium
uv run python tests/integration/smoke_sdk.py --profile qwen --effort xhigh
```

The SDK test checks reasoning/text separation, a streamed tool call, the tool-result
turn with reasoning replay, final text, and token usage. It does not execute shell
tools. Echo rejects incomplete or truncated generations before executing tools.

## External providers later

Add another file in `models/` with a LiteLLM `provider`, unprefixed `model` name,
`request_format: standard`, `base_url: ""` for its default endpoint, and
`api_key_env` naming the credential variable. Set the provider's context/output
limits and supported sampling/reasoning settings. Omit `deployment` for remote
models; no Docker changes are required.

The standard adapter omits vLLM-specific `top_k` and template kwargs. Provider
restrictions still need validation with actual credentials. Keep
`return_reasoning: false` until that provider's history format is tested.

Sources:

- https://docs.litellm.ai/docs/providers/vllm
- https://docs.litellm.ai/docs/completion/stream
- https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- https://huggingface.co/cyankiwi/Qwen3.8-27B-AWQ-INT4/blob/main/chat_template.jinja
