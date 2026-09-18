# CLI resilience

The current target is one prompt_toolkit REPL with a Rich streaming renderer. Neovim and concurrent multi-session displays are deferred. No UI performance guarantees have been measured.

## Output ownership and backpressure

Suspend editable input while a turn streams; restore it after the renderer stops. Route all terminal output through one renderer. Batch text updates, retain tool/turn boundaries, and bound display previews. Large tool logs belong in stored results rather than an ever-growing live display. A bounded queue must apply backpressure or coalesce display-only updates without discarding transcript content.

Use a modest refresh cadence initially. Optimize after observing an actual problem, and keep UI work separate from inference and tool execution.

## Initial checks

| Scenario | Expected behavior |
| --- | --- |
| Fast text stream | Readable output and complete stored response |
| Long command output | Bounded preview; full result retained separately |
| Ctrl-C during inference or tool execution | Cancellation state recorded; prompt recovers |
| Server disconnect or invalid tool call | Error displayed; uncertain tool effects are not replayed |
| Terminal resize / narrow screen | Content remains readable; next prompt is usable |
| Redirected output | Plain append-only output without live cursor control |

These are planned acceptance checks, not an existing test suite. Multi-agent stress tests can be added with the concurrency milestone. See the [CLI contract](cli.md).
