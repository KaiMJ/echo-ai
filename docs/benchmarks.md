# Benchmarks

Run from a checkout with local inference and the sandbox image ready:

```bash
uv run echo-ai bench --attempts 3 --output tests/benchmarks/results/local-gemma.json
```

The suite contains ten authored Python function-repair tasks: arithmetic mean,
ordered deduplication, chunking, slug generation, nonmutating dictionary merge,
list flattening, nested lookup, bracket matching, inclusive ranges, and word counts.

Each attempt starts from a fresh Git fixture in a disposable Docker workspace.
The agent can write its own tests. Independent acceptance checks are supplied
only after the agent stops. A pass requires both a completed agent turn and
successful acceptance checks. A correct patch from a turn that exhausts its
budget is recorded as a failure.

Results include prompts' code version hashes, model settings, sandbox image ID,
per-task status, latency, usage, verification output, and the submitted patch.
Session IDs refer to the local SQLite transcripts. Patches are captured before
acceptance checks execute. Model requests have no automatic retries.

## Interpretation

This is a small engineering regression suite, not SWE-bench or a measure of
general repository-level coding ability. There are no large dependencies,
multi-file architectural tasks, or hidden real-world bug reports. Three attempts
per task are too few for strong statistical claims.

Elapsed task time includes the agent loop and verification, but excludes fixture
creation and the initial workspace copy. First-token time is for the first model
request. Prompt token totals include repeated context across requests. Tool time
includes container startup and cleanup. Warm inference caches affect timings.

The development review found that Gemma sometimes appended demonstration tests
to production modules. Asking for separate tests improved file organization,
but exposed repeated writes and step-limit failures in some runs. The current
prompt asks it to stop after passing checks; unchanged writes now return an
explicit no-change observation. Results should be judged by both code and turn
completion, not just a final claim from the model.

Five empty Bash calls measured a median of about 0.40 seconds for fresh container
startup, execution, and cleanup. See [raw sandbox timings](../tests/benchmarks/results/sandbox-overhead.json).
This baseline excludes repository copying and model inference.

## Local results — 2026-09-18

Two RTX 4090s (24 GB each), vLLM 0.29.0, the pinned Gemma AWQ checkpoint,
16K context, thinking disabled, and the restricted Docker image. Each cohort
contains three attempts at all ten tasks. Top-p is 0.95 and top-k is 64.

| Metric | Temperature 0.2 | Temperature 1.0 (default) |
| --- | ---: | ---: |
| Completed turn and passing acceptance checks | 25/30 | **28/30** |
| Patches passing acceptance checks | 30/30 | 30/30 |
| Median task time | 7.6 s | 7.5 s |
| P95 task time (nearest rank) | 19.0 s | 17.3 s |
| Median first-token latency | 58 ms | 58 ms |
| Total prompt tokens, including repeated context | 409,503 | 345,297 |
| Total completion tokens | 29,861 | 32,713 |

The default follows the model author's recommended sampling. These small,
sequential cohorts suggest fewer stalls at that setting; they do not establish
statistical significance or an optimal temperature.

The two default-setting failures were chunking attempts 1 and 3. Both produced
code that passed the independent checks, then repeatedly wrote the same file
until the 20-call limit. They remain failures in the headline score. This is an
unresolved model behavior; the runtime stops and preserves the workspace rather
than claiming the task completed. Inspect the diff before continuing.

Review also found some model-written tests duplicated the implementation instead
of importing it. Passing the agent's own tests is therefore insufficient; the
independent acceptance checks are the score's authority. This suite does not
measure general test quality or maintainability.

Raw results, including failures and submitted patches:

- [Default sampling](../tests/benchmarks/results/local-gemma.json)
- [Low-temperature comparison](../tests/benchmarks/results/low-temperature-gemma.json)
- Earlier exploratory runs: [initial prompt](../tests/benchmarks/results/initial-gemma.json),
  [separate-test guidance](../tests/benchmarks/results/prompt-separation-gemma.json).
  Those runs used earlier instrumentation and should not be treated as controlled comparisons.

Measurements were taken from a dirty development tree. Source hashes record the
modules at run start; the recorded Git commit alone does not identify that tree.
Model/runtime configuration is in the JSON and [inference guide](inference.md).
The CLI's doctor authentication handling was corrected after the default cohort
started; the measured agent, transport, sandbox, and benchmark modules are unchanged.

To repeat the temperature comparison on the current code:

```bash
ECHO_TEMPERATURE=0.2 uv run echo-ai bench --attempts 3 --output low-temperature.json
ECHO_TEMPERATURE=1.0 uv run echo-ai bench --attempts 3 --output default-temperature.json
```
