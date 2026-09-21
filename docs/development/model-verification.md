# Model settings and verification

Run these commands from the Echo checkout.

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
ECHO_ENV_FILE=.env ECHO_REASONING_EFFORT=xhigh uv run echo-ai
ECHO_ENV_FILE=.env ECHO_MAX_TOKENS=32768 uv run echo-ai
```

Choose the matching model in `/model` before testing. Docker settings come directly
from the deployment profile; client overrides do not silently change server capacity.

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

Sources:

- https://docs.litellm.ai/docs/providers/vllm
- https://docs.litellm.ai/docs/completion/stream
- https://recipes.vllm.ai/Qwen/Qwen3.8-27B
- https://huggingface.co/cyankiwi/Qwen3.8-27B-AWQ-INT4/blob/main/chat_template.jinja
