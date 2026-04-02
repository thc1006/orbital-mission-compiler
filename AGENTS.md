# AGENTS.md

## Mission statement
Build the ground-side ORCHIDE-aligned mission plan compiler: schema validation → policy guardrails → workflow compilation → admission semantics, with interface contracts for simulation, packaging, and platform service integration.

## Repo objective
Core mainline (implement):
1. mission plan schema (Pydantic, aligned with ORCHIDE slide 9 format),
2. policy guardrails (OPA/Rego — absent in ORCHIDE),
3. custom translation layer: mission plan → workflow intent IR → Argo artifacts,
4. workflow / admission rendering (Argo YAML + Kueue Job YAML).

Extended (define contracts only, not implementations):
- simulation contracts,
- packaging contracts,
- platform service contracts (Storage, Monitor, Communication, Security Manager).

Optional (serve the mainline, do not lead it):
- MCP interface, Claude Code hooks/skills/subagents, structured logging.

Explicit non-goals:
- full developer platform or SDK,
- full simulation framework,
- real EOS / Zot / Vector / OpenSearch / Prometheus integration,
- onboard orchestration, flight-ready / HA-ready / OTA-ready claims.

See `docs/13_market_positioning.md` for competitive analysis.

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
- Do not claim to replace ORCHIDE or any onboard platform; this repo is a ground-side complement.
- Do not silently change pinned versions in docs or scripts.
- Do not introduce unverified install commands without adding an official source to `docs/11_research_log.md`.
- Do not replace transcript-grounded statements with inference unless explicitly labeled.
- Do not add “latest” floating versions to scripts.

## TDD / Agile rules
1. **Test-first**: new features or semantic changes must start with a failing test (`tests/`) or failing golden eval (`evals/golden/`). Write the test, confirm it fails, then implement.
2. **Gate**: a change is not done until `make verify && make test && make eval` all exit 0. Do not merge, commit, or declare completion before this passes.
3. **Doc-sync**: any change to schemas, compiler, policy, or rendering must update the relevant docs before the gate check:
   - schema changes → `docs/04_architecture.md`
   - compiler/rendering changes → `docs/04_architecture.md`, `docs/12_phase2_local_demo.md`
   - policy changes → `docs/08_risks_and_unknowns.md`, add eval fixtures
   - dependency changes → `docs/07_installation_matrix.md`, `docs/11_research_log.md`
   - validation changes → `docs/09_validation_checklist.md`

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
