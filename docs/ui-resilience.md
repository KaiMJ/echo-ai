# CLI resilience

Interactive chat uses a persistent prompt_toolkit application. Rich formats Markdown into styled text, but prompt_toolkit alone owns the terminal, mouse events, scrolling, input, and footer. Final answers update the same transcript entry used during streaming, avoiding a preview-to-scrollback handoff.

Reasoning and tools show up to six preview lines while active, then collapse. Clicking their header opens a scrollable Markdown popup. Esc closes it; F2 opens the latest trace. Mouse-wheel and page keys browse history, and Ctrl-End resumes following output. Completed Markdown is cached by width and content. Redraws are coalesced at a maximum of ten per second.

Active traces have animated magenta indicators; completed traces use green checks,
with red failure and yellow interruption markers. Shortcut keys are highlighted.
Tool arguments render separately as JSON. Markdown reads remove tool line prefixes;
other source files use syntax highlighting. Listings, shell output, and search
matches remain literal text with their original line breaks.

Dragging in the transcript or popup highlights a frozen snapshot. Ctrl-C requests
copying through the terminal's OSC 52 clipboard support; Esc clears the selection.
This takes priority over cancellation while text is selected. Unsupported terminal
clipboards can use native selection instead.

Alt+y, F3, or `/copy` freezes the displayed entries and disables application mouse reporting so the
terminal can select text by dragging. Copy with the terminal's shortcut (usually
Ctrl+Shift+C on Linux or Cmd+C on macOS). F3 or Esc resumes live output; agent work
continues while the snapshot is displayed. In many terminals Shift+drag also
bypasses mouse reporting. Alt+d or `/details` opens the latest trace without F2.
F1 or `/help` includes these instructions.

The footer labels input context as `Input [used / capacity]` with a percentage.
`Gen` is generated tokens for the current/latest request, including thinking,
answer text, and tool calls. `~` marks character-based estimates until server
usage arrives. Tool argument deltas are cumulative and are not double-counted.
Reported thinking tokens are a subset of completion tokens, not an extra total.
Reviews have separate input and output counters. Narrow terminals prioritize
input token counts; `/status` shows full counters and the output limit.

## Output ownership and backpressure

Input editing pauses during a turn, but the transcript and popup remain interactive. Model tool-argument deltas are display-only; execution still waits for validated complete arguments. Shell output streams within the existing capture limit; structured file tools return their result at completion. Streaming does not change tool execution, cancellation, or storage semantics.

Trace popups are retained in memory for the current chat and are not restored on
resume. Completed reasoning traces are saved with assistant messages in SQLite,
including final responses and tool-call responses. By default, reasoning fields are removed
from every inference request and excluded from the prompt context guard. With
`local-model.return_reasoning: true`, they are included in request history, the
input estimate, and the prompt context guard. Generation counts include thinking
in either mode. Parent
and reviewer sessions save their own traces. Partial interrupted generations are
not persisted. Batch commands retain the Rich renderer; `--plain` and redirected
output remain append-only. No UI performance guarantees have been measured.

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
