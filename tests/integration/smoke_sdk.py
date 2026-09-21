"""Live LiteLLM SDK test: reasoning/text separation and a streamed tool round trip."""

import argparse
import asyncio
import json
import os
from dataclasses import replace

from echo_ai.config import Config
from echo_ai.runtime.model import Model


async def run(config):
    model = Model(config)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a file to find a secret number.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    events = []
    messages = [
        {
            "role": "user",
            "content": "Use the read tool to read answer.txt. Report the number in it.",
        }
    ]
    first, usage1 = await model.complete(messages, tools, lambda kind, value: events.append(kind))
    calls = first.get("tool_calls", [])
    assert len(calls) == 1, first
    call = calls[0]
    assert call["function"]["name"] == "read", call
    assert json.loads(call["function"]["arguments"]) == {"path": "answer.txt"}, call
    messages.extend(
        [first, {"role": "tool", "tool_call_id": call["id"], "content": "The number is 731."}]
    )
    final, usage2 = await model.complete(messages, tools, lambda kind, value: events.append(kind))
    assert "731" in final["content"], final
    for message in (first, final):
        assert "<think>" not in (message["content"] or ""), message
        assert "<tool_call>" not in (message["content"] or ""), message
    if config.reasoning_enabled:
        assert "reasoning" in events, "No parsed reasoning events"
    else:
        assert not first.get("reasoning") and not final.get("reasoning"), "Unexpected thinking"
    assert "tool_call_delta" in events and "text" in events, events
    assert usage1.get("completion_tokens", 0) > 0 and usage2.get("completion_tokens", 0) > 0
    print(
        json.dumps(
            {
                "model": config.model,
                "context_tokens": config.context_tokens,
                "max_output_tokens": config.max_tokens,
                "thinking": config.reasoning_enabled,
                "effort": config.reasoning_effort,
                "tool": call["function"],
                "answer": final["content"],
                "reasoning_chars": sum(len(m.get("reasoning", "")) for m in (first, final)),
                "usage": [usage1, usage2],
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=["gemma", "qwen"], default="qwen")
    parser.add_argument("--effort", choices=["low", "medium", "xhigh"])
    parser.add_argument("--no-thinking", action="store_true")
    args = parser.parse_args()
    os.environ["ECHO_MODEL_PROFILE"] = f"builtin:{args.profile}"
    config = Config.from_env()
    if args.effort:
        config = replace(config, reasoning_effort=args.effort)
    if args.no_thinking:
        config = replace(config, reasoning_enabled=False)
    asyncio.run(run(config))


if __name__ == "__main__":
    main()
