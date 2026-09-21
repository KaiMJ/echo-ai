# Development documentation

Start with the [current architecture](architecture.md) for Echo's existing runtime. User-facing setup and working examples belong in [User guides](../guides/README.md).

For the website, see [Landing-page development](landing-page.md), including local checks, terminal captures, and deployment.

For local inference checks and reasoning settings, see [Model verification](model-verification.md).

See the [public security and usability review](public-readiness-review.md) for findings, validation, and remaining release checks.

## Integration plans

These documents describe proposed implementation work. They do not imply that the described commands or tools are available.

- [Google tools integration](google-tools-integration.md)
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
