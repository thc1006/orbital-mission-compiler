# AGENTS.md

## Repo objective
Build a **Mission Plan Compiler** for cloud-native satellite-style orchestration:
- mission plan ingestion,
- policy validation,
- workflow compilation,
- priority/admission decisions,
- observability hooks,
- optional MCP interface for coding agents.

## Mandatory working sequence
1. Read `docs/00_transcript_grounding.md`.
2. Read `docs/05_breakthrough_direction.md`.
3. Read `docs/04_architecture.md`.
4. Read `docs/07_installation_matrix.md`.
5. Only then modify code, scripts, or manifests.

## Build / test / lint / dev commands
- `make verify` — required pre-commit validation
- `make test` — unit tests
- `make lint` — Ruff
- `make fmt` — Ruff format
- `make compile-sample` — compile sample mission plan
- `make eval` — run golden translation checks
- `make print-tree` — show repo tree

## Done criteria
A change is done only if:
- relevant docs are updated,
- `make verify` passes,
- changed behavior is covered by tests or eval fixtures,
- assumptions and unknowns are recorded in `docs/08_risks_and_unknowns.md`,
- public-facing workflow examples are regenerated if schemas changed.

## Forbidden
- Do not claim flight readiness.
- Do not silently change pinned versions in docs or scripts.
- Do not introduce unverified install commands without adding an official source to `docs/11_research_log.md`.
- Do not replace transcript-grounded statements with inference unless explicitly labeled.
- Do not add “latest” floating versions to scripts.

## Document update rules
Update docs when changing:
- system boundaries → `docs/04_architecture.md`
- tool choices → `docs/03_tooling_matrix.md` and `docs/07_installation_matrix.md`
- validation assumptions → `docs/09_validation_checklist.md`
- transcript interpretation → `docs/00_transcript_grounding.md`

## When to write a plan first
Write or update a plan document before coding if you are:
- changing architecture,
- introducing a new external dependency,
- changing workflow semantics,
- adding a new subagent / MCP surface,
- altering admission / policy logic.

## Required checks after every non-trivial change
1. `make verify`
2. `make test`
3. `make eval`
4. update docs if behavior or interfaces changed

## Recommended subagents
See `.claude/agents/`:
- `researcher.md`
- `systems-architect.md`
- `k8s-platform.md`
- `observability.md`
- `eval-engineer.md`
