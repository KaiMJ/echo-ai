# CLI: prompt_toolkit REPL and Rich renderer

## First interaction contract

Use prompt_toolkit for input editing, multiline prompts, history, and command completion. Use Rich for assistant text, tool status/output, errors, and final diffs. Keep one active turn. The initial CLI runs the async agent loop in the same process; inference and sandboxed tools remain separate.

Proposed commands: `/help`, `/new`, `/status`, and `/exit` in M1; `/resume`, `/branch`, and explicit restore commands in M2. Input history is a convenience, not the authoritative session store.

Interactive chat uses one full-screen `prompt_toolkit.Application` with a persistent transcript, input editor, status footer, and mouse-enabled trace popup. Input becomes read-only during a turn; scrolling and trace inspection remain available. Rich renders Markdown into styled fragments without controlling the terminal. The same answer entry remains visible before and after completion. See [prompt_toolkit application documentation](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/full_screen_apps.html).

Plain mode keeps `PromptSession.prompt_async()` and append-only output. Batch runs retain the Rich renderer.

## Streaming contract

The model adapter emits text deltas and tool-call fragments. The agent loop assembles each complete tool call, validates its name and arguments, executes it, records the result, and requests the next model response. Never execute partial streamed arguments. Keep reasoning separate from final content when the selected model exposes it.

Only the active UI writes to the terminal. Reasoning and tool traces stream as Markdown previews, collapse when complete, and open in a scrollable popup when clicked. Shell tools emit captured output as available; file-tool results arrive at completion. Tool argument fragments are display-only until the complete call is validated. Completed entries cache their Markdown rendering, and UI refreshes are coalesced. The durable transcript remains independent of display refreshes.

## Cancellation and failures

- Ctrl-C while editing clears/cancels that input. During a turn it requests cancellation, closes the model stream, and stops the active tool process in its execution boundary.
- Persist completed tool results and mark interrupted or uncertain effects explicitly. A second interrupt may exit; next startup reconciles the incomplete turn.
- Server disconnects and invalid tool arguments become visible errors. Never automatically replay a tool whose effects are uncertain.
- Always restore the terminal in a `finally` path. Support plain append-only output for redirected stdout or terminals without live rendering.

## M1 acceptance

Exercise multiline input, streaming text, a read/edit/test cycle, a failed tool call, cancellation during generation and during a command, and a server disconnect. Confirm the prompt remains usable after each failure and the saved transcript contains the actual tool results. Check terminal resize and a large output preview without requiring an elaborate UI benchmark suite.
