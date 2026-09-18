# Local inference: vLLM and Qwen

## Initial decision

Start with **vLLM serving a Qwen model** through its OpenAI-compatible HTTP API. Exact checkpoint, revision, precision, tool parser, context length, and endpoint are deployment configuration. No exact model ID is committed as a project default.

Choose a vLLM-compatible checkpoint format for the initial deployment. The earlier GGUF download remains a separate experiment; its successful llama.cpp smoke test does not validate the new deployment. Keep weights, environments, and caches on the existing data filesystem. There is no need to move them into the repository or the home filesystem.

The development host has two 24 GB GPUs and 128 GB system RAM. Select a checkpoint that fits with room for KV cache and runtime buffers; a modest model/context is sufficient to establish the coding loop. Use one GPU if it fits comfortably, otherwise configure tensor parallelism and verify memory use. A precise checkpoint choice remains open; do not download multiple variants merely to begin development.

## Deployment checklist

1. Select one compatible Qwen checkpoint and a vLLM release; record model commit and package versions locally.
2. Install vLLM in its own environment, separate from Echo's CLI and the earlier SGLang environment. Check the selected release's GPU/driver requirements.
3. Start a loopback-only server with explicit model alias, context limit, and device settings. Stop any earlier inference server using those GPUs before loading the new one.
4. Configure tool choice, tool-call parser, chat template, and reasoning settings for that exact checkpoint and vLLM version. Qwen variants do not all use the same parser; follow the selected release's documentation.
5. Verify health, model listing, text streaming, and a complete tool-call/result/follow-up exchange with JSON argument validation.
6. Exercise a read/edit/test task in a disposable checkout, a failed tool call, and cancellation. Save settings and outcomes.

Local utilities under the Git-ignored `scripts/` directory cover Docker, uv, and earlier llama.cpp/SGLang experiments; they are not included in a fresh clone. vLLM installation and launch automation still need to be added when the deployment is selected. This plan review does not install vLLM, download another model, or stop running services.

## Echo integration

Configure base URL, served model alias, and optional authentication in the model adapter. Keep the vLLM server separate from the CLI and the Docker tool sandbox. The first agent uses one model and one active turn, with a bounded tool loop and saved session state.

Text deltas and tool calls must be handled as separate event types. Accumulate streamed arguments until complete, validate before execution, and send results back with the corresponding tool-call IDs. A short greeting test alone is not sufficient evidence of tool compatibility.

## Deferred optimization

Alternative engines, speculative decoding, cache tuning, routing, and throughput comparisons come after a working coding agent. Record basic memory, latency, and failures while developing, without establishing a benchmark project as a prerequisite. Later comparisons should control weights, chat template, context, decoding settings, and workload; session DAG structure alone does not establish a prefix-cache hit.

## References

- [vLLM GPU installation](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
- [vLLM tool calling](https://docs.vllm.ai/en/latest/features/tool_calling/)
- [Qwen vLLM deployment guide](https://github.com/QwenLM/Qwen3/blob/main/docs/source/deployment/vllm.md)

Consult documentation for the chosen release when fixing the exact launch arguments.
