"""OpenAI-compatible streaming transport; no automatic retries of model turns."""

import json
import os
import time

import httpx

from .config import Config


class Model:
    def __init__(self, config: Config, transport=None):
        self.config = config
        self.transport = transport

    async def complete(self, messages: list[dict], tools: list[dict], emit):
        started = time.monotonic()
        text, calls, usage = "", {}, {}
        first_token = None
        finished = False
        headers = {"Authorization": f"Bearer {os.getenv('ECHO_API_KEY', 'local')}"}
        async with (
            httpx.AsyncClient(timeout=self.config.timeout, transport=self.transport) as client,
            client.stream(
                "POST",
                self.config.base_url.rstrip("/") + "/chat/completions",
                headers=headers,
                json={
                    "model": self.config.model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "max_tokens": self.config.max_tokens,
                    "temperature": self.config.temperature,
                    "top_p": self.config.top_p,
                    "top_k": self.config.top_k,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            ) as response,
        ):
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("error"):
                    raise RuntimeError(str(chunk["error"]))
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    content = delta.get("content") or ""
                    if content:
                        if first_token is None:
                            first_token = time.monotonic() - started
                        text += content
                        emit("text", content)
                    for fragment in delta.get("tool_calls", []):
                        if first_token is None:
                            first_token = time.monotonic() - started
                        index = fragment["index"]
                        call = calls.setdefault(
                            index,
                            {
                                "id": "",
                                "type": "function",
                                "function": {"name": "", "arguments": ""},
                            },
                        )
                        if fragment.get("id"):
                            call["id"] += fragment["id"]
                        function = fragment.get("function", {})
                        call["function"]["name"] += function.get("name") or ""
                        call["function"]["arguments"] += function.get("arguments") or ""
                    reason = choice.get("finish_reason")
                    if reason:
                        if reason not in ("stop", "tool_calls"):
                            raise RuntimeError(
                                f"Generation stopped with {reason}; no partial tools executed."
                            )
                        finished = True
        if not finished:
            raise RuntimeError("Incomplete model stream; no partial tools executed.")
        ordered = [calls[i] for i in sorted(calls)]
        if not text and not ordered:
            raise RuntimeError("Model returned no text or tool calls.")
        if any(not c["id"] or not c["function"]["name"] for c in ordered):
            raise RuntimeError("Malformed tool call in model response.")
        if len({c["id"] for c in ordered}) != len(ordered):
            raise RuntimeError("Duplicate tool call IDs.")
        message = {"role": "assistant", "content": text or None}
        if ordered:
            message["tool_calls"] = ordered
        return message, {"seconds": time.monotonic() - started, "ttft": first_token, **usage}
