# Changelog

## v0.2.0 (unreleased)

### Security
- **S-H1**: MCP tools now validate file paths — reject traversal, absolute paths, directory components (CWE-22)
- **S-H2**: OPA subprocess has 30s timeout with `OPA_TIMEOUT_SECONDS` constant (CWE-400)
- **S-H3**: OPA stderr no longer leaked to caller (CWE-209)
- **S-M6**: opa_smoke.sh uses mktemp + trap cleanup (CWE-377)
- .gitignore adds .env exclusion

### Features
- **Parallel rendering**: `execution_mode: parallel` now produces fan-out DAG (no depends)
- Execution mode annotation (`orbital/execution-mode`) in rendered workflows

### Code quality
- **H-1**: policy.py stdout/stderr handling fixed
- **H-2**: workflow_name sanitized at creation time (unified truncation)
- **H-3**: `sanitize_k8s_name` renamed to public API (no underscore)
- **H-4**: eval_runner uses `__file__`-based paths (CWD-independent)
- `mcp/__init__.py` added, `MissionPlan.events` enforces min_length=1
- Priority range documented (0-100 vs ORCHIDE 1-4)

### Infrastructure
- GitHub Actions CI pipeline with coverage + OPA cache
- Docker image: non-root user, .dockerignore, smoke tests
- Makefile PYTHONPATH fixed (`make test` works for fresh clones)

### Testing
- 142+ tests (up from 98 in v0.1.0)
- MCP smoke tests (5 tools via async API)
- Docker smoke tests (3 tests, skip when no daemon)
- Security tests: path traversal (6), OPA timeout (3), policy output (4)
- Coverage ~78% (up from 57%)

### Documentation
- Strategic analysis document (docs/14_strategic_analysis.md)
- Full-review Phase 1-3 reports in .full-review/

## v0.1.1 (2026-04-02)

### Changes since v0.1.0
- Fix #8: compiler logs skipped non-acquisition events
- Fix #14: eval_runner auto-discovers golden cases via glob
- Fix schema gaps: orbit Field(ge=0), duration_seconds Field(ge=0), mission_id not empty
- Coverage 57% → 74%, compilation summary logging
- CI: pytest --cov, OPA cache, smoke all plans, pytest-cov==6.0.0

## v0.1.0 (2026-04-02)

First release of the ground-side ORCHIDE-aligned mission plan compiler.

### Core
- **Mission plan schema** aligned with ORCHIDE KubeCon EU 2026 slide 9: orbit, duration_seconds, landscape_type, StepPhase (preprocessing/ai/postprocessing), ExecutionMode (sequential/parallel).
- **Policy guardrails**: 10 OPA/Rego deny rules covering mission_id, events, services, GPU fallback, zero priority, acceleration coherence, download constraints, empty steps, landscape type.
- **Custom translation layer**: `compile_plan_to_intents()` produces `WorkflowIntent` IR with computed resource_hints (9 fields including execution_mode).
- **Argo Workflow renderer**: DAG-based workflows with phase annotations, priority metadata, resource hints, RFC 1123 name sanitization. Passes `argo lint` v4.0.1.
- **Kueue Job renderer**: optional admission mapping with GPU resource requests, nodeSelector, tolerations. Cluster admission confirmed via integration smoke test.

### Contracts (interface definitions only — no runtime)
- `contracts/simulation.py`: 5 models (AcquisitionReplayEvent, DownloadWindowEvent, WorkflowTrigger, SimulationTimeline, SimulationResult)
- `contracts/packaging.py`: 6 models (ApplicationIdentity, ApplicationInput/Output, RuntimePreference, PolicyHints, PackageManifest)
- `contracts/storage.py`: 3 models (FileRegistration, FileQuery, FileRecord)
- `contracts/monitor.py`: 3 models (MetricPoint, LogEntry, HealthStatus)
- `contracts/communication.py`: 2 models + 1 enum (DownlinkRequest, UplinkAck, UplinkStatus)
- `contracts/security.py`: 2 models (AuthToken, IntegrityCheck)

### Agent tooling
- Claude Code settings.json (defaultMode: plan, PostToolUse hook)
- 12 agents, 10 commands, 8 skills (includes wshobson/agents selection)
- Market positioning document with cross-validated competitive analysis

### Documentation
- 28 .md files aligned with ORCHIDE-complementary mission statement
- Source-to-ORCHIDE-slide mapping table in docs/04_architecture.md
- Validation layering table (schema vs policy defense-in-depth)

### Testing
- 98 tests across 8 test files
- 2 golden eval cases
- OPA smoke, Argo lint, Kueue integration smoke all passing
