# Evaluation and Benchmarking Plan

## Status and Goals

This is a proposed evaluation plan; no harness or benchmark results exist yet. Numerical goals are adjustable, not release requirements. Begin with a small fixed set of coding tasks and expand when measurements become useful for development.

## Initial Measurements

| Metric | What to record |
| :--- | :--- |
| Task success | Tests, requested behavior, and compliance with user constraints; record failures as well as successes. |
| Latency | End-to-end time, time to first generated token, routing time, and tool time separately; report distributions rather than one best run. |
| Cost | All model calls, retries, routing, and compaction; compare cost per successful task alongside total spend. |
| Context behavior | Token usage, available provider cache metrics, and retention of explicit constraints after compaction. |
| Recovery | Session persistence across restart, interrupted-tool reconciliation, and conversation/code restore behavior. |
| Integration | Validation results for all merges, including clean merges; investigate AST merging only after observing actual conflicts. |

Record repository commit, task, model/version, configuration, tool versions, and execution environment. Compare changes on the same tasks and disclose small sample sizes. Tests passing after compaction do not establish lossless memory.

## Milestone Acceptance vs. Performance Experiments

The README milestones contain concrete functional acceptance scenarios. Performance thresholds can be set or revised after measuring a baseline. Small correctness checks should accompany implementation; a broad benchmark suite is not a prerequisite for the first working agent.

## Routing Experiments

Compare a fixed model, deterministic routing, and optional Jev routing on the same tasks. Measure quality, total latency, cost, and routing mistakes. Include timeouts and uncertain responses; do not assume typed output establishes decision correctness. Adopt routing if the observed tradeoff helps the coding workflow.

## Later Evaluation

Consider SWE-bench once the coding loop and reproducible sandbox setup work. Use its official harness, fixed task selections, and a declared compute/model budget. Add concurrency stress tests when subagents exist, and local-backend comparisons using the protocol in [local-inference.md](local-inference.md).
