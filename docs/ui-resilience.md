# CLI resilience

Interactive chat uses a persistent prompt_toolkit application. Rich formats Markdown into styled text, but prompt_toolkit alone owns the terminal, mouse events, scrolling, input, and footer. Final answers update the same transcript entry used during streaming, avoiding a preview-to-scrollback handoff.

Reasoning and tools show up to six preview lines while active, then collapse. Clicking their header opens a scrollable Markdown popup. Esc closes it; F2 opens the latest trace. Mouse-wheel and page keys browse history, and Ctrl-End resumes following output. Completed Markdown is cached by width and content. Redraws are coalesced at a maximum of ten per second.

The footer shows context as `[used / capacity]` with a percentage; `~` marks an estimate until prompt usage arrives from the server. Reviews have separate context windows. Narrow terminals prioritize token counts over model metadata and shortcuts.

## Output ownership and backpressure

Input editing pauses during a turn, but the transcript and popup remain interactive. Model tool-argument deltas are display-only; execution still waits for validated complete arguments. Shell output streams within the existing capture limit; structured file tools return their result at completion. Streaming does not change tool execution, cancellation, or storage semantics.

Traces are retained in memory for the current chat. Reasoning is not part of the persisted model conversation and is not restored on resume. Batch commands retain the Rich renderer; `--plain` and redirected output remain append-only. No UI performance guarantees have been measured.

## Initial checks

| Scenario | Expected behavior |
| --- | --- |
| Fast text stream | Readable output and complete stored response |
| Long command output | Bounded preview; full result retained separately |
| Ctrl-C during inference or tool execution | Cancellation state recorded; prompt recovers |
| Server disconnect or invalid tool call | Error displayed; uncertain tool effects are not replayed |
| Terminal resize / narrow screen | Content remains readable; next prompt is usable |
| Redirected output | Plain append-only output without live cursor control |

Renderer and PTY tests in `tests/test_ui.py` cover streaming, resize, context attribution, cancellation, and prompt recovery. Multi-agent stress tests can be added with the concurrency milestone. See the [CLI contract](cli.md).
