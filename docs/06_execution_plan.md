# 06_execution_plan

## Mission statement
Build the ground-side ORCHIDE-aligned mission plan compiler: schema validation → policy guardrails → workflow compilation → admission semantics, with interface contracts for simulation, packaging, and platform service integration.

## Completed work

| ID | Scope | Status |
|---|---|---|
| M0 | Transcript-grounded schema + compiler skeleton | Done |
| M1 | Policy validation + golden evals | Done |
| M2 | Argo rendering + K3s lab scripts + Kueue manifests + OPA/Argo smoke | Done |
| M2.5 | Agent workflow hardening (settings.json, PostToolUse hook) | Done |
| 3A | Policy negative tests (12 tests, 10 deny rules) | Done |
| 3B | Golden eval expansion (6-field comparison) | Done |
| 3C | Hera dead dependency removed | Done |
| 3D | Python version alignment (>=3.10) | Done |
| 4A | Kueue workload renderer + CLI + 3 tests | Done |
| 4B | Kueue cluster integration smoke (admission confirmed) | Done |

---

## Roadmap

### Phase 0 — Architecture grounding
> Map existing code to ORCHIDE slide architecture. No code changes.

- **Goal**: Document which source file implements which ORCHIDE concept.
- **ORCHIDE ref**: Slide 7 (Ground/Space split), slide 15 (tech ecosystem), slide 23 (translation layer).
- **Deliverables**: Module-to-slide mapping table in docs/04_architecture.md.
- **Validation**: `make verify`
- **Done criteria**:
  - [ ] docs/04_architecture.md contains file → ORCHIDE-slide mapping.
  - [ ] No code modified.

### Phase 1 — Mission plan schema
> Align Pydantic schema with ORCHIDE slide 9 format. TDD.

- **Goal**: Schema represents the structured mission plan fields from slide 9.
- **ORCHIDE ref**: Slide 9 (plan table), D3.1 §3.2.1.1.2 (Mission Planner).
- **Deliverables**:
  - Expanded `schemas.py`: per-detector workflow/priority, orbit, event duration, landscape type.
  - New sample plan matching ORCHIDE format.
  - Updated golden evals.
- **Validation**: `make verify && make test && make eval`
- **Done criteria**:
  - [ ] Schema can represent slide 9 table (DATESZ, ORBIT, EV, DT_EV, INST, TYPE_D1-D4, VISI, WORKFLOW_D1-D4, PRIORITY_D1-D4).
  - [ ] At least 1 new sample plan using expanded fields.
  - [ ] Backward-compatible with existing plans.
  - [ ] Golden evals pass.

### Phase 2 — Policy guardrails
> Expand OPA/Rego rules to cover slide 9 and slide 14 semantics. TDD.

- **Goal**: Policy pack validates priority ranges, visibility constraints, resource class consistency.
- **ORCHIDE ref**: Slide 9 (priority 1-4), slide 14 (CPU/GPU/FPGA), slide 20 (Security Manager).
- **Deliverables**:
  - New Rego rules: priority range, visibility-workflow coherence, resource class validation.
  - Positive + negative test per rule.
- **Validation**: `make test && make opa-smoke`
- **Done criteria**:
  - [ ] >= 3 new Rego deny rules.
  - [ ] Every rule has positive + negative test.
  - [ ] All tests pass.

### Phase 3 — Custom translation layer
> Formalize the IR between mission plan parsing and workflow rendering. TDD.

- **Goal**: Clean parse → IR → render separation matching slide 23 architecture.
- **ORCHIDE ref**: Slide 23 (Priority Queue → Custom Translation Layer → API-wrapper → Argo API).
- **Deliverables**:
  - Explicit IR Pydantic model, distinct from plan schema and render output.
  - compiler.py refactored so Argo and Kueue renderers both consume the same IR.
  - IR-level tests independent of renderers.
- **Validation**: `make verify && make test && make eval`
- **Done criteria**:
  - [ ] IR is a distinct Pydantic class with its own tests.
  - [ ] Both renderers consume the same IR.
  - [ ] Existing golden evals still pass.

### Phase 4 — Workflow / admission rendering
> Harden Argo and Kueue renderers. TDD.

- **Goal**: Rendered YAML passes dry-run and lint.
- **ORCHIDE ref**: Slide 23 (Argo API), slide 14 (resource classes).
- **Deliverables**:
  - Argo: resource requests/limits, proper DAG deps, metadata annotations.
  - Kueue: ResourceFlavor mapping, priority class.
- **Validation**: `make test && make argo-smoke && bash scripts/kueue_integration_smoke.sh`
- **Done criteria**:
  - [ ] `kubectl create --dry-run=server` passes for rendered YAML.
  - [ ] `argo lint` passes.
  - [ ] >= 2 tests each for Argo and Kueue renderers.

### Phase 5 — Extended contracts
> Interface specs only. No runtime implementations.

- **Goal**: Define the interfaces that a full ORCHIDE-compatible ground system would need.
- **ORCHIDE ref**: Slide 7 (Ground Level), D3.1 §2.4.1 (SDK, Simulation, Management), §3.2.1.2-3.2.1.5 (platform services).
- **Deliverables**:
  - `contracts/` directory with Pydantic models or JSON Schema:
    - **Simulation contract** — input/output spec for ground-side simulation (D3.1 §2.4.1.2).
    - **Packaging contract** — OCI image packaging spec (D3.1 §5.1).
    - **Storage Manager contract** — file register/query interface (D3.1 §3.2.1.2).
    - **Monitor Manager contract** — metrics/logs collection interface (D3.1 §3.2.1.5).
    - **Communication Manager contract** — downlink scheduling interface (D3.1 §3.2.1.1.3).
    - **Security Manager contract** — authentication/encryption interface (D3.1 §3.2.1.4).
  - Each contract references its ORCHIDE D3.1 section.
  - **No runtime implementation.** Type stubs and docstrings only.
- **Validation**: `make verify && make test`
- **Done criteria**:
  - [ ] `contracts/` exists with >= 4 contract files.
  - [ ] Each file has a docstring citing the ORCHIDE source.
  - [ ] Contracts are importable and pass type-checking.
  - [ ] Zero runtime logic.

### Optional — Agent workflow hardening
> Only after Phase 0–5 core is stable.

These tools serve the mainline but do not lead it:
- MCP smoke tests (tests/test_mcp.py).
- Structured logging in compiler (JSON format).
- Additional Claude Code skills/commands.
- Subagent configurations.

- **Validation**: `make test`
- **Done criteria**:
  - [ ] MCP tools tested (or skipped when fastmcp missing).
  - [ ] Compiler emits structured logs.
  - [ ] All existing tests still pass.
