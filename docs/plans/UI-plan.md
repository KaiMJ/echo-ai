# Echo UI design plan

Echo is a local coding agent with disposable Docker workspaces. Its terminal UI
should make three things easy: give it a task, follow its progress, and inspect
what changed.

The conversation is the primary surface. Keep diagnostics and detailed traces one
action away instead of surrounding the answer with permanent panels.

## Default screen

```text
 Echo  /  gemma  /  8f3a9e12
  You
  Fix toolbar overflow when the model name is long.

  Echo · Reasoning · Done · details

  Echo · edit · src/echo_ai/ui.py · Done · details

  Echo · bash · pytest tests/test_ui.py · Done · details

  Echo
  The toolbar now fits narrow terminals. All UI tests passed.

 ── Enter send · Alt+Enter newline · F2 details · F1 help
  echo ›


 Echo Context [2,620 / 262,144] 1% · Completed · /help
```

The example transcript illustrates layout, not a guarantee of test results or
model configuration. Runtime content always comes from the current session.

### Visual hierarchy

- **Header:** Echo, the configured model, and a short session ID. One line;
  truncate metadata when space is limited. `/status` shows the full session ID.
- **Transcript:** one column with a small horizontal gutter. Assistant answers
  use normal Markdown, with bold speaker labels. User labels use cyan. Separate
  entries with one blank line.
- **Tool and reasoning rows:** muted labels and explicit status text. Preview up
  to six lines while active, collapse when finished, and open details on click.
  Preserve failure and cancellation labels even when long commands are clipped.
- **Composer:** three lines for input, preceded by a quiet shortcut hint. Keep
  the familiar `echo ›` prompt. No insert/normal modes.
- **Footer:** current context usage and activity. Prioritize token counts over
  metadata at narrow widths; `~` means an estimate.

Use terminal-native colors and the user's background. Reserve red for failures
and yellow for interruptions. Pair color with words so status remains readable
without color. Use borders for overlays, not around every message or panel.

Active work uses a magenta animated spinner; completed traces use green checkmarks.
Keep animation limited to activity icons. Highlight shortcut keys in cyan so they
can be distinguished from their descriptions.

### Empty, running, and interrupted states

An empty transcript invites a task and points to `/help` and `/diff`. Do not show
fake messages, sample metrics, or a dashboard of zeroes.

During a turn the prompt is read-only. The composer hint changes to
`Working · Ctrl-C cancel · F2 details`; scrolling and trace inspection stay usable.
Streaming and completed answers occupy the same entry.

Scrolling back suspends auto-follow and shows `Ctrl-End` to return to the latest
output. A cancelled turn leaves a visible notice and restores input. Failed tool
rows retain their failure status; full output remains available in details.

## Details on demand

### Trace overlay

Click a tool/reasoning row or press F2 for the latest trace. Show arguments and
output in a scrollable Markdown overlay. Esc returns focus to the prompt. Keep
parent and read-only review entries distinct. F1 opens help without interrupting
a running turn or discarding a draft.

Render tool arguments as JSON separately from output. Markdown file reads remove
the tool's line-number prefixes before rendering; other source files use syntax
highlighting. File lists, search matches, and shell output preserve literal text
and line breaks rather than being interpreted as Markdown.

F3 enters selection mode: freeze a snapshot of the visible conversation/details
and release mouse reporting to the terminal. Drag to select and use the terminal's
copy command (usually Ctrl+Shift+C on Linux, Cmd+C on macOS). Agent work continues;
F3 or Esc resumes the live view. Keyboard scrolling remains available in the
snapshot. Many terminals also support Shift+drag to bypass application mouse input.

### Changes

`/diff` displays the existing unified sandbox diff with syntax highlighting.
An unchanged workspace says “No sandbox changes yet.”

A future dedicated inspector should use unified diff by default and offer
side-by-side only when both columns have enough room. Compare against the
sandbox's captured baseline, which can include uncommitted source changes;
do not label it as host `HEAD`.

Hunk selection and application need backend support before they become UI
controls. Inspection must never implicitly write to the host checkout.

### Session information

`/status` exposes the full session ID, workspace path, and active context usage.
Further diagnostics can live here when their sources are available. Do not show
GPU memory, KV-cache utilization, endpoint health, or throughput unless measured
and attributable to the current request. Unavailable is different from zero.

## Keyboard contract

| Key | Action |
| --- | --- |
| Enter | Send a prompt; close an open overlay |
| Alt+Enter | Insert a newline while editing |
| F1 | Open help |
| F2 | Open the latest tool/reasoning trace, or close an overlay |
| F3 | Toggle terminal selection/copy mode; freeze/resume displayed output |
| Esc | Close the overlay and return to the prompt |
| PgUp / PgDn | Scroll the transcript or open overlay |
| Ctrl+End | Follow the newest output in the active view |
| Ctrl+C | Cancel a running turn; clear idle input; close an overlay first |
| Ctrl+D | Exit when idle; request cancellation while running |

Commands: `/help`, `/diff`, `/status`, `/exit`. Keep Ctrl+D's existing exit behavior.
In selection mode, Enter or Esc first resumes the live view and preserves the draft.
Avoid Ctrl+S, which conflicts with terminal flow control. No global shell or diff
shortcuts until those views exist.

## Responsive behavior

Keep the same single-column structure at every width. Clip chrome by terminal
cell width, including wide Unicode characters. Wrap Markdown to the available
transcript width. Shorten hints below 65 columns and retain context counts ahead
of model metadata. The transcript takes the remaining height after the compact
header, composer, and footer.

Verify ordinary layouts at 120×35, 80×24, and 40×12, and check a 24×8 terminal for
prompt recovery and usable controls. Resize must preserve the draft, selected
trace, and transcript entries. Respect manual scrolling as content arrives.

## Implementation boundaries

| Surface | Existing source |
| --- | --- |
| Transcript, composer, overlays, keyboard input | `src/echo_ai/terminal.py` |
| Activity, context counts, plain/batch presentation | `src/echo_ai/ui.py` |
| Parent and review lifecycle events | `src/echo_ai/agent.py` |
| Model deltas and reported usage | `src/echo_ai/model.py` |
| Sandbox baseline and unified diff | `src/echo_ai/sandbox.py` |
| Persisted sessions and messages | `src/echo_ai/store.py` |

`prompt_toolkit` owns the interactive screen. Rich converts Markdown into styled
fragments; it must not compete for terminal ownership. UI refreshes consume
existing events and must not launch Docker commands or database queries.
Plain mode and batch rendering keep their existing behavior.

Session persistence is not filesystem time travel. Restoring a turn requires
workspace snapshots and defined recovery semantics, beyond listing stored
messages. Likewise, an interactive container shell needs explicit lifecycle,
concurrency, and PTY handling before it can safely share an agent workspace.

## Delivery sequence

1. **Clean default surface — this pass.** Compact identity header, empty state,
   restrained transcript styles, contextual composer hints, F1 help, and a clear
   no-changes state. Preserve streaming, cancellation, context, and trace behavior.
2. **Focused diff inspector.** Add a read-only overlay with file navigation and
   unified diffs; consider side-by-side after narrow-screen behavior is sound.
3. **Session browser.** List persisted sessions and inspect their messages. Label
   unavailable traces explicitly. Add branching only with backend support.
4. **Optional diagnostics and shell.** Introduce measured telemetry or a container
   shell when their data and lifecycle contracts exist. Keep them off the default
   conversation screen.

Validate the first pass with the existing renderer and PTY suite, including
multiline input, mouse/keyboard trace inspection, review attribution, resize,
Ctrl-C cancellation, and prompt recovery. Add focused checks for any new behavior
that those scenarios do not exercise.
