# 09_validation_checklist

## Baseline checks (must pass at all times)

These commands must exit 0 before any change is considered complete.

```bash
python3 scripts/verify.py       # file existence + syntax
make test                       # unit tests
make eval                       # golden translation checks
```

- [x] repository tree generated
- [x] required docs generated
- [x] Python files syntax-checked with `compileall`
- [x] sample mission plans included
- [x] golden eval fixtures included
- [x] install scripts pinned to explicit versions
- [x] Argo sample manifest YAML-parsed locally
- [x] phase-2 demo scripts generated

## Agent workflow hardening checks
- [x] `.claude/settings.json` sets `defaultMode` to `plan` (read-only exploration by default)
- [x] PostToolUse hook configured for `Write|Edit` events
- [x] Hook script uses `$CLAUDE_PROJECT_DIR` (no hardcoded paths)
- [x] Hook script includes path traversal guard (`realpath` check)
- [x] Hook runs `verify.py` on every file change
- [x] Hook conditionally runs `pytest` for `src/`, `tests/`, `scripts/` changes
- [x] Hook conditionally runs `eval_runner` for `configs/`, `evals/` changes
- [ ] Hook end-to-end tested inside a live Claude Code session

## Completed prior work
- [x] Policy tests cover all Rego deny rules (test_policy.py)
- [x] Golden eval expansion: 6-field comparison (workflow_name, steps, resource_hints)
- [x] Hera dead dependency removed from pyproject.toml
- [x] Python version aligned to >=3.10
- [x] Kueue workload renderer (render_kueue_job + CLI + 3 tests)
- [x] Kueue cluster integration smoke (admission confirmed)
- [x] Market positioning documented (docs/13_market_positioning.md)
- [x] All docs aligned with ORCHIDE-complementary mission statement

## Per-phase checks (new roadmap)

### Phase 0 — Architecture grounding
- [x] docs/04_architecture.md contains module-to-ORCHIDE mapping
- [x] Each source file's role documented relative to ORCHIDE slides
- [x] No code modified

### Phase 1 — Mission plan schema alignment
- [x] Schema supports ORCHIDE slide 9 fields: orbit, duration_seconds, landscape_type
- [x] New sample plan: configs/mission_plans/sample_orchide_format.yaml
- [x] Golden evals pass with expanded schema (backward-compatible)
- [x] Existing sample plans still load (test_existing_plans_still_load)
- [x] 8 schema-specific tests in tests/test_schema.py

### Phase 2 — Policy guardrails expansion
- [x] 6 new Rego rules: zero priority, acceleration-on-CPU, download-with-services, download-without-visibility, empty-steps, invalid landscape_type
- [x] 12 policy tests (10 negative + 2 positive), every deny rule covered
- [x] `make test` passes, `make opa-smoke` passes

### Phase 3 — Custom translation layer formalization
- [x] WorkflowIntent IR tested independently (10 tests in test_ir.py)
- [x] IR carries ORCHIDE slide 9 fields: orbit, duration_seconds, landscape_type
- [x] Argo and Kueue renderers both consume same IR (verified in test_ir.py)
- [x] Golden evals updated and passing with expanded resource_hints
- [x] docs/04_architecture.md already contains IR layer mapping

### Phase 4 — Workflow / admission rendering hardening
- [x] Argo templates annotated with step phase (slide 10)
- [x] Argo + Kueue annotated with orbital/priority + resource hints
- [x] `argo lint` passes on rendered output
- [x] 6 rendering tests + 3 Kueue tests, all pass (60 total)

### Phase 5 — Extended contracts
#### 5.1 Simulation contracts
- [x] `contracts/simulation.py` — 5 models (AcquisitionReplayEvent, DownloadWindowEvent, WorkflowTrigger, SimulationTimeline, SimulationResult)
- [x] 7 tests, all pass. No runtime logic.

#### 5.2 Packaging contracts
- [x] `contracts/packaging.py` — 6 models (ApplicationIdentity, ApplicationInput, ApplicationOutput, RuntimePreference, PolicyHints, PackageManifest)
- [x] 15 tests, all pass. No OCI build logic.

#### 5.3–5.6 Platform service contracts
- [x] `contracts/storage.py` — 3 models: FileRegistration, FileQuery, FileRecord (D3.1 §3.2.1.2)
- [x] `contracts/monitor.py` — 3 models: MetricPoint, LogEntry, HealthStatus (D3.1 §3.2.1.5)
- [x] `contracts/communication.py` — 2 models: DownlinkRequest, UplinkAck (D3.1 §3.2.1.1.3)
- [x] `contracts/security.py` — 2 models: AuthToken, IntegrityCheck (D3.1 §3.2.1.4)
- [x] 15 platform contract tests, all pass. No real adapters.

### Optional Phase X — Agent workflow hardening (continued)
- [ ] MCP tools tested (tests/test_mcp.py)
- [ ] Compiler emits structured logs
- [ ] All existing tests still pass

## Cluster integration checks (require live cluster)
- [x] K3s / K8s cluster accessible
- [x] Argo Workflows installed and pods Running
- [x] Kueue installed and pods Running
- [x] Kueue demo queues applied (ClusterQueue, LocalQueue, ResourceFlavors)
- [x] OPA CLI installed and policy eval works
- [x] Argo CLI installed and lint passes
- [ ] GPU execution path tested on a real accelerator node
- [ ] MCP server runtime tested with a real MCP host
- [ ] Cluster-level observability stack tested

## Release checks (before tagging a version)
1. `make verify && make test && make eval` exit 0
2. `make argo-smoke` passes (Argo lint)
3. `make opa-smoke` passes (OPA policy eval)
4. `make render-samples` produces valid YAML
5. `make demo-phase2` completes without error
6. No unused dependencies in `pyproject.toml`
7. All docs consistent with ORCHIDE-aligned mission statement
8. `git status` clean (no uncommitted changes)
