# 10_agents_and_mcp

## Why MCP is included
The user explicitly asked for agentic workflow support. This repo therefore includes:
- an optional FastMCP-based server,
- Claude-oriented subagent briefs under `.claude/agents/`,
- command snippets under `.claude/commands/`.

## Intended usage
- `validate_plan(path)` — schema-level mission plan validation
- `compile_plan(path)` — compile plan and summarize generated intents
- `render_argo(path)` — render Argo Workflow manifests
- `explain_policy(path)` — evaluate OPA policy against a plan

## Positioning among space MCP servers
As of April 2026, 15+ space-related MCP servers exist (Orbit-MCP, IO Aerospace, NASA API, STK, Copernicus, etc.), but all focus on data reading (orbit calculations, imagery access). This project's MCP server is the only one that performs workflow production — compiling mission plans into deployable K8s artifacts with policy validation. See docs/13_market_positioning.md for the full landscape.

## Why this improves reliability
Long-running development often fails because context drifts. MCP + subagent files help keep:
- transcript grounding,
- architecture decisions,
- validation sequences,
- and tooling constraints
available to coding agents as explicit artifacts.
