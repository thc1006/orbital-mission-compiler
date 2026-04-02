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
- [x] Policy negative tests: 5 tests, 4 deny rules covered (test_policy.py)
- [x] Golden eval expansion: 6-field comparison (workflow_name, steps, resource_hints)
- [x] Hera dead dependency removed from pyproject.toml
- [x] Python version aligned to >=3.10
- [x] Kueue workload renderer (render_kueue_job + CLI + 3 tests)
- [x] Kueue cluster integration smoke (admission confirmed)
- [x] Market positioning documented (docs/13_market_positioning.md)
- [x] All docs aligned with ORCHIDE-complementary mission statement

## Per-phase checks (new roadmap)

### Phase 0 — Architecture grounding
- [ ] docs/04_architecture.md contains module-to-ORCHIDE mapping
- [ ] Each source file's role documented relative to ORCHIDE slides
- [ ] No code modified

### Phase 1 — Mission plan schema alignment
- [x] Schema supports ORCHIDE slide 9 fields: orbit, duration_seconds, landscape_type
- [x] New sample plan: configs/mission_plans/sample_orchide_format.yaml
- [x] Golden evals pass with expanded schema (backward-compatible)
- [x] Existing sample plans still load (test_existing_plans_still_load)
- [x] 8 schema-specific tests in tests/test_schema.py

### Phase 2 — Policy guardrails expansion
- [ ] >= 3 new Rego rules (priority range, visibility, resource class consistency)
- [ ] Every deny rule has positive + negative test
- [ ] `make test` all pass

### Phase 3 — Custom translation layer formalization
- [ ] Explicit IR model is a distinct Pydantic class
- [ ] Argo and Kueue renderers both consume same IR
- [ ] Existing golden evals still pass
- [ ] docs/04_architecture.md updated to show IR layer

### Phase 4 — Workflow / admission rendering hardening
- [ ] All rendered YAML passes `kubectl create --dry-run=server`
- [ ] All rendered Argo YAML passes `argo lint`
- [ ] >= 2 Kueue tests, >= 2 Argo rendering tests

### Phase 5 — Extended contracts
- [ ] `contracts/` directory exists with >= 4 contract definitions
- [ ] Each contract references its ORCHIDE D3.1 source section
- [ ] Contracts are importable and type-checkable

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
