# CLI: prompt_toolkit REPL and Rich renderer

## First interaction contract

Use prompt_toolkit for input editing, multiline prompts, history, and command completion. Use Rich for assistant text, tool status/output, errors, and final diffs. Keep one active turn. The initial CLI runs the async agent loop in the same process; inference and sandboxed tools remain separate.

Proposed commands: `/help`, `/new`, `/status`, and `/exit` in M1; `/resume`, `/branch`, and explicit restore commands in M2. Input history is a convenience, not the authoritative session store.

Use `PromptSession.prompt_async()` for input. Once submitted, suspend the editable prompt and let Rich own terminal output until the turn completes. Then stop live rendering and restore the prompt. This avoids two concurrent cursor managers. If background messages must appear while editing, route them through one coordinated output path using prompt_toolkit's `patch_stdout`; validate redraw behavior before adding concurrent input during generation. See [prompt_toolkit input documentation](https://python-prompt-toolkit.readthedocs.io/en/stable/pages/asking_for_input.html).

## Streaming contract

The model adapter emits text deltas and tool-call fragments. The agent loop assembles each complete tool call, validates its name and arguments, executes it, records the result, and requests the next model response. Never execute partial streamed arguments. Keep reasoning separate from final content when the selected model exposes it.

Only the renderer writes to the terminal. Tools return structured results and captured output. Batch text updates at a modest configurable cadence; keep the durable transcript independent of display refreshes. Begin with a bounded Rich Live region for the current activity and print completed content into terminal scrollback. Limit previews of large outputs and retain full results outside the display. Avoid redrawing an ever-growing transcript. Rich supports explicit refresh control; see [Live display documentation](https://rich.readthedocs.io/en/stable/live.html).

## Cancellation and failures

- Ctrl-C while editing clears/cancels that input. During a turn it requests cancellation, closes the model stream, and stops the active tool process in its execution boundary.
- Persist completed tool results and mark interrupted or uncertain effects explicitly. A second interrupt may exit; next startup reconciles the incomplete turn.
- Server disconnects and invalid tool arguments become visible errors. Never automatically replay a tool whose effects are uncertain.
- Always restore the terminal in a `finally` path. Support plain append-only output for redirected stdout or terminals without live rendering.

## M1 acceptance

Exercise multiline input, streaming text, a read/edit/test cycle, a failed tool call, cancellation during generation and during a command, and a server disconnect. Confirm the prompt remains usable after each failure and the saved transcript contains the actual tool results. Check terminal resize and a large output preview without requiring an elaborate UI benchmark suite.
