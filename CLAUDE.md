# CLAUDE.md

Start here:
1. `README.md`
2. `docs/00_transcript_grounding.md`
3. `docs/05_breakthrough_direction.md`
4. `docs/04_architecture.md`
5. `docs/07_installation_matrix.md`

## Repo intent
This repo is a **ground development scaffold** for a mission-plan-aware orchestration platform inspired by the ORCHIDE session. It intentionally focuses on:
- mission plan → workflow compilation,
- policy guardrails,
- resource/admission semantics,
- observability,
- agent-ready tooling.

It intentionally does **not** pretend to solve:
- radiation hardening,
- full onboard HA,
- OTA update guarantees,
- complete satellite security posture.

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
