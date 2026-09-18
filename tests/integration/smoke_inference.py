"""Check streaming and a tool round trip against the local inference server."""

import argparse
import json
import os
import time
import urllib.request

from echo_ai.config import Config


def stream(config, messages, tools=None):
    payload = {
        "model": config.model,
        "messages": messages,
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 256,
        "temperature": 0,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if tools:
        payload.update(tools=tools, tool_choice="auto")
    request = urllib.request.Request(
        config.base_url.rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.getenv('ECHO_API_KEY', 'local')}",
        },
    )
    started = time.monotonic()
    first_token = None
    content = ""
    calls = {}
    chunks = 0
    usage = None
    with urllib.request.urlopen(request, timeout=config.timeout) as response:
        for line in response:
            if not line.startswith(b"data: "):
                continue
            raw = line[6:].strip()
            if raw == b"[DONE]":
                break
            event = json.loads(raw)
            usage = event.get("usage") or usage
            for choice in event.get("choices", []):
                delta = choice["delta"]
                if delta.get("content") or delta.get("tool_calls"):
                    if first_token is None:
                        first_token = time.monotonic() - started
                    chunks += 1
                content += delta.get("content") or ""
                for part in delta.get("tool_calls", []):
                    call = calls.setdefault(
                        part["index"],
                        {
                            "id": "",
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        },
                    )
                    if part.get("id"):
                        call["id"] = part["id"]
                    for field in ("name", "arguments"):
                        call["function"][field] += part.get("function", {}).get(field) or ""
    message = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = list(calls.values())
    return message, {
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "first_token_seconds": round(first_token, 3) if first_token else None,
        "stream_chunks": chunks,
        "usage": usage,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    config = Config.from_env()
    parser.add_argument("--base-url", default=config.base_url)
    args = parser.parse_args()
    from dataclasses import replace

    config = replace(config, base_url=args.base_url)
    tools = [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": "Read a workspace file.",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                    "additionalProperties": False,
                },
            },
        }
    ]
    messages = [
        {
            "role": "user",
            "content": "Use the read tool to read answer.txt. Then report the number in it.",
        }
    ]
    message, first = stream(config, messages, tools)
    calls = message.get("tool_calls", [])
    assert len(calls) == 1, message
    call = calls[0]
    assert call["function"]["name"] == "read", call
    assert json.loads(call["function"]["arguments"]) == {"path": "answer.txt"}, call
    messages.extend(
        [message, {"role": "tool", "tool_call_id": call["id"], "content": "The number is 731."}]
    )
    final, second = stream(config, messages, tools)
    assert "731" in final["content"], final
    assert second["stream_chunks"] > 1, second
    print(
        json.dumps(
            {"tool_call": message, "final": final, "tool_request": first, "answer_request": second},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
