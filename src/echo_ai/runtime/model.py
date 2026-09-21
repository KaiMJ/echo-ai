"""LiteLLM SDK streaming transport; no automatic retries of model turns."""

import json
import os
import time
from contextlib import aclosing
from copy import deepcopy

import httpx

from echo_ai.config import Config
from echo_ai.config.file import load_environment
from echo_ai.runtime.errors import RequestRejected
from echo_ai.runtime.pricing import cost_usage
from echo_ai.runtime.tracing import record


def request_messages(messages, *, return_reasoning=False, model_identity=None):
    """Build inference history according to the configured reasoning replay policy."""
    history = []
    for message in messages:
        replay = return_reasoning and (
            model_identity is None or message.get("_echo_model", model_identity) == model_identity
        )
        excluded = {"_echo_model"}
        if not replay:
            excluded.update({"reasoning", "reasoning_content"})
        history.append({k: v for k, v in message.items() if k not in excluded})
    return history


def completion_kwargs(config, messages, tools):
    """Keep provider-specific parameters at the transport boundary."""
    history = request_messages(
        messages, return_reasoning=config.return_reasoning,
        model_identity=f"{config.provider}/{config.model}",
    )
    if config.request_format == "qwen":
        for message in history:
            reasoning = message.pop("reasoning", None)
            if reasoning is not None:
                message.setdefault("reasoning_content", reasoning)
    params = {
        "model": f"{config.provider}/{config.model}",
        "messages": deepcopy(history),
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": config.max_tokens,
        "temperature": config.temperature,
        "top_p": config.top_p,
        "timeout": config.timeout,
        "num_retries": 0,
    }
    if tools:
        params.update(tools=deepcopy(tools), tool_choice="auto")
    if config.base_url:
        params["api_base"] = config.base_url
    key = load_environment(api_key_env=config.api_key_env).get(config.api_key_env)
    if key:
        params["api_key"] = key
    elif config.provider == "hosted_vllm":
        params["api_key"] = "local"
    elif config.provider == "xai":
        raise RequestRejected(
            f"Missing {config.api_key_env}. Set it in your shell or the selected credential file "
            "(the current project's .env is detected automatically)."
        )
    if config.request_format in {"vllm", "qwen"}:
        template = {"enable_thinking": config.reasoning_enabled}
        if config.request_format == "qwen":
            template["preserve_thinking"] = config.preserve_thinking
            if config.reasoning_enabled and config.reasoning_effort:
                template["reasoning_effort"] = config.reasoning_effort
        params["extra_body"] = {
            "top_k": config.top_k,
            "chat_template_kwargs": template,
            # hosted_vllm strips reasoning_content in its message adapter.
            # The explicit body preserves our validated history/replay policy.
            "messages": history,
        }
        if tools:
            # Keep the schema seen by vLLM identical to Echo's validation schema.
            # hosted_vllm otherwise removes additionalProperties constraints.
            params["extra_body"]["tools"] = deepcopy(tools)
    elif config.reasoning_enabled and config.reasoning_effort:
        params["reasoning_effort"] = config.reasoning_effort
    return params


class FinishCheckedStream(httpx.AsyncByteStream):
    """Require a real vLLM finish marker before LiteLLM synthesizes one at EOF."""

    def __init__(self, stream):
        self.stream = stream

    async def __aiter__(self):
        pending = b""
        finished = False
        async for block in self.stream:
            pending += block
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                if line.startswith(b"data:"):
                    data = line[5:].strip()
                    if data and data != b"[DONE]":
                        event = json.loads(data)
                        finished |= any(c.get("finish_reason") for c in event.get("choices", []))
                    elif data == b"[DONE]" and not finished:
                        raise RuntimeError("Incomplete model stream; no partial tools executed.")
            yield block
        if not finished:
            raise RuntimeError("Incomplete model stream; no partial tools executed.")

    async def aclose(self):
        await self.stream.aclose()


async def check_vllm_response(response):
    if response.is_success:
        if response.is_stream_consumed:
            async for _ in FinishCheckedStream(httpx.ByteStream(response.content)):
                pass
        else:
            response.stream = FinishCheckedStream(response.stream)


async def completion_chunks(params, transport=None):
    # Avoid the SDK's startup fetch of its optional remote pricing table.
    os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    import litellm
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler
    from openai import APIError

    client = None
    stream = None
    try:
        if params["model"].startswith("hosted_vllm/") or transport is not None:
            client = AsyncHTTPHandler()
            await client.client.aclose()
            client.client = httpx.AsyncClient(
                transport=transport,
                timeout=params["timeout"],
                event_hooks={"response": [check_vllm_response]}
                if params["model"].startswith("hosted_vllm/") else {},
            )
            params = {**params, "client": client}
        stream = await litellm.acompletion(**params)
        async for chunk in stream:
            yield chunk.model_dump(exclude_none=True)
    except APIError as error:
        if getattr(error, "status_code", None) in {400, 401, 403, 404, 422, 429}:
            raise RequestRejected(f"Model request rejected: {error}") from error
        raise RuntimeError(f"Model request failed: {error}") from error
    finally:
        if stream is not None:
            await stream.aclose()
        if client is not None:
            await client.client.aclose()


class Model:
    def __init__(self, config: Config, transport=None):
        self.config = config
        self.transport = transport

    def check_ready(self):
        completion_kwargs(self.config, [], [])

    async def complete(self, messages: list[dict], tools: list[dict], emit):
        usage = {}
        try:
            return await self._complete(messages, tools, emit, usage)
        except RequestRejected:
            usage.update(cost_usd=0.0, cost_source="rejected")
            raise
        finally:
            if "cost_source" not in usage:
                usage.update(cost_usage(self.config, usage))
            record("usage", usage)
            emit("model_cost", usage)

    async def _complete(self, messages, tools, emit, usage):
        started = time.monotonic()
        text, thinking, calls = "", "", {}
        first_token = None
        finished = False
        params = completion_kwargs(self.config, messages, tools)
        record("request", {k: v for k, v in params.items() if k not in {"api_key", "api_base"}})
        async with aclosing(completion_chunks(params, self.transport)) as chunks:
            async for chunk in chunks:
                record("chunk", chunk)
                if chunk.get("error"):
                    raise RuntimeError(str(chunk["error"]))
                usage.update(chunk.get("usage") or {})
                for choice in chunk.get("choices", []):
                    delta = choice.get("delta", {})
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content") or ""
                    if reasoning:
                        thinking += reasoning
                        if first_token is None:
                            first_token = time.monotonic() - started
                        emit("reasoning", reasoning)
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
                        emit("tool_call_delta", {"index": index, **call["function"]})
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
        if thinking:
            message["reasoning"] = thinking
        record("response", message)
        usage.update(seconds=time.monotonic() - started, ttft=first_token)
        return message, usage
