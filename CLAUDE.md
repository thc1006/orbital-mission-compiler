# CLAUDE.md

Start here:
1. `README.md`
2. `docs/00_transcript_grounding.md`
3. `docs/13_market_positioning.md`
4. `docs/04_architecture.md`
5. `docs/07_installation_matrix.md`

## Mission statement
Build the ground-side ORCHIDE-aligned mission plan compiler: schema validation → policy guardrails → workflow compilation → admission semantics, with interface contracts for simulation, packaging, and platform service integration.

## Repo intent
This repo is a **ground-side mission plan compiler** that complements onboard platforms like ORCHIDE. ORCHIDE's D3.1 states that it only covers the "Deferred Phase" (on-satellite workflow execution) and receives mission plans via a deployment interface — but does not generate, validate, or compile those plans. This repo fills that gap.

Core mainline (implement):
1. mission plan schema (aligned with ORCHIDE slide 9 format),
2. policy guardrails (OPA/Rego — not present in ORCHIDE),
3. custom translation layer: mission plan → workflow intent IR → Argo artifacts,
4. workflow / admission rendering (Argo YAML + Kueue Job YAML).

Extended (define contracts only, not implementations):
- simulation, packaging, platform service contracts (Storage, Monitor, Communication, Security Manager).

Optional (serve the mainline, do not lead it):
- MCP interface, Claude Code hooks/skills/subagents, structured logging.

It intentionally does **not** build:
- a full developer platform or SDK,
- a full simulation framework,
- real EOS / Zot / Vector / OpenSearch / Prometheus integration,
- onboard orchestration,
- radiation hardening, full HA, OTA guarantees, or flight-ready claims.

## Working preferences
- Prefer small, reviewable changes.
- Keep code generation deterministic.
- Prefer explicit schemas and golden tests over vague prompts.
- Use official docs before proposing dependency or CLI changes.
- Keep GPU paths optional with CPU fallback.

## Hard constraints
- Do not edit pinned versions in scripts without updating `docs/07_installation_matrix.md`.
- Do not add dependencies unless the package name and install command are verified from official sources.
- Do not remove transcript-grounding notes.
- Do not write architecture claims that exceed what the transcript and docs support.
- Do not claim to replace ORCHIDE; position as ground-side complement.
- Refer to `docs/13_market_positioning.md` for competitive landscape context.

## Key implementation notes
- Core logic lives in `src/orbital_mission_compiler/`.
- Sample plans live in `configs/mission_plans/`.
- Golden evals live in `evals/golden/`.
- Bootstrap and install flows live in `scripts/`.
- MCP entry point is `src/orbital_mission_compiler/mcp/server.py`.

## Preferred workflow
- inspect docs
- inspect schemas
- run tests/evals
- make smallest coherent change
- rerun `make verify`

## If asked to extend the system
Prefer one of these directions:
1. richer mission plan schema
2. stronger policy pack
3. Kueue admission integration
4. richer Argo rendering
5. telemetry export
6. MCP tools for plan validation / compilation
