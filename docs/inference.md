# Local inference

Echo uses the OpenAI-compatible chat endpoint provided by vLLM. The deployment
below runs the requested Gemma checkpoint across two 24 GB RTX 4090s. Model
weights remain outside this repository.

Prerequisites: Docker Compose with GPU support, the NVIDIA container runtime,
and a complete Hugging Face model cache (including `blobs/` and `snapshots/`).

From the repository root:

```bash
cp .env.example .env
# Edit ECHO_MODEL_CACHE in .env to point to your complete model cache.
docker compose up -d
docker logs -f echo-vllm
```

Set the path to your complete cached model directory. On the development machine it is
`/home/mkim/mkim/.cache/huggingface/hub/models--cyankiwi--gemma-4-26B-A4B-it-AWQ-4bit`.

Wait for `Application startup complete`. First startup compiles GPU kernels and
can take several minutes. The compilation cache is a Docker volume.

```bash
curl --fail http://127.0.0.1:8001/health
uv run python tests/integration/smoke_inference.py
```

The smoke check assembles streamed tool-call arguments, returns a synthetic file
result, and checks the streamed final answer. It does not execute model-generated
commands. Stop inference with `docker stop echo-vllm`; restart it with
`docker start echo-vllm`.

The endpoint is `http://127.0.0.1:8001/v1`. Both `gemma` and
`cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` identify the same model. Port 8001 avoids
an existing service on this machine. Set `ECHO_INFERENCE_PORT` in `.env` to change it; the client uses the same port
unless `ECHO_BASE_URL` is explicitly set.

## Pinned configuration

| Component | Value |
| --- | --- |
| Model | `cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit` |
| Cached model revision | `3a7dcb639a4e7b230a0491ab4fa6fac081284d37` |
| vLLM | `0.29.0` |
| PyTorch | `2.13.0+cu130` |
| Transformers | `5.16.1` |
| Image digest | `sha256:c2914767605584b6d8f45686b82de173ecc99e781897aa3d0a66dacd72c51ae1` |
| Pipeline parallelism | 2 GPUs |
| Tensor parallelism | 1 GPU |
| Context, including output | 262,144 tokens (native model limit) |
| Output cap per model call | 16,384 tokens |
| Maximum concurrent sequences | 4 |
| GPU memory utilization | 0.90 |
| Tool and reasoning parsers | `gemma4` |

The checkpoint declares `compressed-tensors` quantization; vLLM reads that
configuration automatically. Do not force `--quantization awq` based on the
repository name. The model's bundled chat template is used. Echo requests
`chat_template_kwargs={"enable_thinking": true}` by default. Set
`reasoning_enabled: false` in `echo.yaml` to disable it. Reasoning traces are
stored locally. `local-model.return_reasoning` controls whether they are sent
back to inference (default: `false`), independently of generation.
Only text inference is enabled.

Sampling follows the model card: temperature 1.0, top-p 0.95, and top-k 64.
`ECHO_TEMPERATURE` overrides temperature for a new session. These settings are
saved in session configuration and benchmark results.

Previously verified at 16,384 context / 4,096 output tokens on 2026-09-18: health and model discovery, streamed automatic tool
choice, JSON argument reconstruction, and a tool-result response all passed.
One warm smoke run took 0.102 seconds for the 15-token tool call and 0.087
seconds for the 16-token answer; time to the first streamed delta was 0.058
and 0.033 seconds respectively. This tiny repeated prompt benefits from caching
and is a compatibility check, not a coding benchmark. Allocated GPU memory was
about 21 GB per card.

The model directory is mounted read-only, the endpoint binds to loopback, and
inference has no repository mount or Docker socket. This GPU service is separate
from the restricted containers that execute coding tools. GPU access requires
a larger device/driver surface than the tool sandbox.

For another machine, change the model cache path and ensure the pinned snapshot
exists. `ECHO_MODEL_REVISION` can select another cached snapshot; rerun the smoke
check after any model or serving change. The deployment runs offline and does
not download missing weights.

References: [vLLM Gemma 4 guide](https://docs.vllm.ai/projects/recipes/en/stable/Google/Gemma4.html),
[model card](https://huggingface.co/cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit).

## Resize and redeploy

The pinned checkpoint's `text_config.max_position_embeddings` is **262,144**.
This was read directly from its cached `config.json`. The old 16,384-token limit
was our explicit serving setting, not the model's native limit. Defaults now use:

```dotenv
ECHO_CONTEXT_TOKENS=262144
ECHO_MAX_TOKENS=16384
ECHO_MAX_NUM_SEQS=4
```

Context includes input and output. The output cap applies to each model call;
it is a ceiling, not a request to always generate that many tokens. The input
budget reserves this allowance plus template/schema overhead. Keep a single
vLLM instance with tensor parallelism across both GPUs; it can serve multiple
requests without duplicating the entire model into separate instances.

At the old 16K setting, the running service reported:

```text
Available KV cache memory: 10.92 GiB
GPU KV cache size: 277,049 tokens
Maximum concurrency for 16,384 tokens per request: 16.91x
```

That report is cache capacity under the old configuration, not a verified
single-request limit or a promise of four simultaneous 256K requests. Gemma
uses sliding-window and full attention; capacity must be checked after changing
the serving limit. Full-window runtime and quality have not yet been validated.
GPU memory utilization remains 0.85.

If `.env` already exists, edit its values: changing `.env.example` does not
update it. Remove an old `ECHO_MAX_CONTEXT_CHARS=32000` override if you want the
input guard to scale to the larger window. Exported shell values also override
`.env`.

Apply the edited settings from the repository root:

```bash
docker compose config --quiet
docker compose up -d --force-recreate inference
docker compose logs -f inference
# Once startup completes (Ctrl-C stops following logs):
uv run echo-ai config
uv run echo-ai doctor
uv run python tests/integration/smoke_inference.py
uv run echo-ai bench --attempts 3 --output tests/benchmarks/results/context-256k.json
```

A container restart does not apply changed Compose arguments; recreation does.
The root Compose project is named `echo`. If migrating the old deployment and
Docker reports that `echo-vllm` already exists, inspect it first with
`docker inspect echo-vllm`; after confirming it is the old Echo inference service,
remove that container with `docker rm -f echo-vllm` and run `up` again. This
interrupts inference. Cached weights remain on the host; Docker cache volumes
are not removed, though the new project may create a fresh compilation cache.

Inspect the startup capacity report:

```bash
docker logs echo-vllm 2>&1 | rg 'Using max model len|Available KV cache memory|GPU KV cache size|Maximum concurrency'
```

Verify that the server advertises 262,144 tokens with `echo-ai doctor`, then
exercise a long task as well as the short smoke test. The function-repair
benchmark checks regressions but does not establish long-context quality.
If startup cannot allocate the required cache, lower `ECHO_CONTEXT_TOKENS` in
`.env` and recreate the service; the client reads the same value. To restore
the historical benchmark configuration, set context to 16,384 and output to
4,096 (both must change), keeping 4 sequences.

Start a **new Echo session** to use the changed client limits. Resumed sessions
keep their saved settings; sessions created before context was configurable
retain the old 16,384-token serving limit.
