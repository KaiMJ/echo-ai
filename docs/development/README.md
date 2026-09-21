# Development documentation

Start with the [current architecture](architecture.md) for Echo's existing runtime. User-facing setup and working examples belong in [User guides](../guides/README.md).

For the website, see [Landing-page development](landing-page.md), including local checks, terminal captures, and deployment.

For local inference checks and reasoning settings, see [Model verification](model-verification.md).

## Development setup

`uv run echo-ai` runs the checkout; an installed `echo-ai` uses its separately
installed copy. To keep development sessions and settings separate, set
`ECHO_STATE_DIR` to a scratch directory and `XDG_CONFIG_HOME` to a separate config
directory. The checkout's optional `.env` is ignored by Git; use `.env.example`
as a starting point. The local model launcher also reads it for cache paths and ports.

Bundled defaults live in `src/echo_ai/config/presets/`: `echo.yaml` supplies the
setup configuration; `gemma.yaml`, `qwen.yaml`, and `xai.yaml` supply model presets.
Users do not need to copy or edit these files.

## Integration plans

These documents describe proposed implementation work. They do not imply that the described commands or tools are available.

- [Google tools integration](google-tools-integration.md), with a [private development example](google-tools-example.md) unavailable in fresh clones
- [Web research and browser use](web-and-computer-use-architecture.md)
- [Web search](web-search-plan.md)

## Design notes and experiments

These notes explore intended behavior and future designs. Some use present-tense descriptions of proposals; consult the current architecture and source for implemented behavior.

- [Context engineering](context-engineering.md)
- [Lifecycle hooks](hooks-and-lifecycle.md)
- [Sessions and DAG state](sessions-and-dag.md)
- [Skills and MCP](skills-and-mcp.md)
- [Subagents and orchestration](subagents-and-orchestration.md)
- [Multi-agent worktrees](multi-agent-worktrees.md)
- [System 1 routing experiment](system-one.md)

## Documentation conventions

Put instructions for released or runnable behavior in `docs/guides/`. Put architecture, implementation plans, and experiments here, with their status stated near the top. Keep runnable examples in `examples/`, use placeholders for machine-specific values, and keep credentials and generated state outside version control.

When a feature becomes available, update its user guide and README entry alongside the implementation. Link to the guide from the design document instead of maintaining duplicate setup instructions.
