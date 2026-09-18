# Neovim Integration: MessagePack RPC Architecture (`echo.nvim`)

> Deferred: Neovim is outside the current roadmap. Build the prompt_toolkit/Rich CLI first; this document retains a possible future editor design.

## 1. Design Philosophy

Unlike tools that force developers into a cramped terminal window inside Neovim (`:terminal aider` or `:terminal claude`), **Echo is headless-first**.

Neovim communicates with the running Echo daemon over a **Unix Domain Socket** (`/tmp/echo.sock`) using binary **MessagePack RPC**.

```text
┌────────────────────────────────────────────────────────┐
│                   NEOVIM INSTANCE                      │
│                                                        │
│  [Code Buffer: app.py]                                 │
│  def process_transaction(user_id, amount):             │
│      # Echo Virtual Text: Proposed fix (extmark)       │
│      validate_funds(user_id, amount)                   │
│                                                        │
│  [Statusline: lualine.nvim]                            │
│  [NVDA: $118.40 ▲] [Echo: Idle (Sonnet)] [Cost: $0.12]   │
└───────────────────────────┬────────────────────────────┘
                            │ Unix Socket / MessagePack RPC
┌───────────────────────────▼────────────────────────────┐
│                    ECHO DAEMON                         │
│  Reads active buffer context, cursor, and registers.   │
│  Streams inline diffs, notifications, and telemetry.   │
└────────────────────────────────────────────────────────┘
```

---

## 2. Remote Procedure Call (RPC) Specification

### Exported Daemon Methods (Callable by Neovim):
* `echo.prompt(session_id, prompt, file_path, line_start, line_end, buffer_content)`:
  Dispatches an agent turn with precise editor selection and file context.
* `echo.cancel(session_id)`:
  Halts active generation or running tool execution.
* `echo.rollback(session_id, target_node_id)`:
  Rewinds active session DAG to an earlier node.
* `echo.get_status()`:
  Returns active model, token count, cost, and telemetry for the statusline.

### Exported Neovim Methods (Callable by Echo Daemon):
* `nvim_buf_set_extmark`: Renders inline ghost text or virtual lines previewing code suggestions.
* `nvim_open_win`: Opens floating inspection modals for agent thoughts and research memos.
* `vim.diff`: Spawns a side-by-side diff view comparing current buffer with proposed changes.
* `vim.notify`: Dispatches native floating notifications for alerts and completed background tasks.

---

## 3. Keyboard Protocol & Ergonomics

| Keybinding | Action | Description |
| :--- | :--- | :--- |
| `<leader>ea` | **Echo Ask** | Grabs visual selection or current buffer context and opens input prompt. |
| `<leader>ed` | **Echo Diff** | Toggles side-by-side diff split for proposed code changes. |
| `<Tab>` | **Echo Accept** | Commits the streamed virtual text diff into the active buffer. |
| `<Esc>` | **Echo Reject** | Clears virtual text suggestions and rejects changes. |
| `<leader>er` | **Echo Rollback** | Opens telescope picker displaying session DAG branches to rewind context. |
| `<leader>es` | **Echo Stocks** | Pops a floating window rendering real-time market research and signals. |
