# 10_agents_and_mcp

## Why MCP is included
The user explicitly asked for agentic workflow support. This repo therefore includes:
- an optional FastMCP-based server,
- Claude-oriented subagent briefs under `.claude/agents/`,
- command snippets under `.claude/commands/`.

## Intended usage
- `validate_plan(path)` — schema-level mission plan validation
- `compile_plan(path)` — compile plan and summarize generated intents

## Why this improves reliability
Long-running development often fails because context drifts. MCP + subagent files help keep:
- transcript grounding,
- architecture decisions,
- validation sequences,
- and tooling constraints
available to coding agents as explicit artifacts.
