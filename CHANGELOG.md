# Changelog

## v0.5.0 (2026-07-29)

Unified GPU+CPU DRA and a scheduler-level accelerator fallback, re-validated on
Kueue v0.18.3, plus a reproducibility matrix binding the paper's DRA experiments to
exact versions and commits. This is the public release that reproduces the extended
arXiv version (the unified-DRA + scheduler-level-fallback section).

### Added
- `manifests/k8s/kueue/dra-unified/`: the unified GPU+CPU Kueue Configuration
  (`deviceClassMappings` for `gpu.nvidia.com` + `dra.cpu`), ResourceClaimTemplates
  (`firstAvailable` + `exactly`), the three demonstrations (CPU quota cascade,
  `firstAvailable` scheduler fallback, `firstAvailable`-under-Kueue rejection), and a
  dra-driver-cpu install script carrying the kubelet-root-dir workaround.
- `results-v0.18.3-20260716/`: captured live-cluster output for every DRA claim
  (K8s v1.36.1, Kueue v0.18.3, Quadro K2200).
- Compiler `--dra-fallback`: renders a scheduler-route `firstAvailable` RCT and a
  Kueue-route `exactly` RCT; unit + end-to-end CLI guard tests.
- `docs/17_reproducibility.md`: version/commit matrix + paper-claim-to-artifact map.

### Changed
- `render_kueue_job` never emits a `firstAvailable` claim (Kueue rejects it as
  Inadmissible); it uses the `exactly` `gpu.nvidia.com` claim, which Kueue
  quota-counts. Stale manifest/comment predictions corrected to the observed rejection.

## v0.4.2 (2026-07-07)

Camera-ready correctness + adversarial-review pass for the IEEE SMC-IT/SCC
2026 paper. Fixes two latent policy bugs found by review and adds the
experiments the camera-ready describes.

### Fixed
- **OPA Rule 4** (accelerator fallback): now fires on any `gpu`/`fpga` step
  that lacks a `fallback_resource_class`, independent of the optional
  `needs_acceleration` flag. Previously a GPU step that omitted the flag (it
  defaults to `false`) silently bypassed the check, and FPGA steps were not
  covered at all.
- **OPA Rule 10** (landscape_type): guards on `is_string()`, so a
  Pydantic-normalized `null`/absent value is permitted (the field is
  optional); previously Rego null-truthiness denied every plan that omitted
  it, including three shipped samples. A second clause rejects a present
  non-string value on the raw-JSON bypass path (defense-in-depth).
- **benchmark_scaling.py**: the `parse` phase now measures the real
  `yaml.safe_load` + `model_validate` load path, matching the paper's
  "parse (YAML + Pydantic)" figure.

### Added
- `baseline_validator.py` + tests: an in-process Python re-implementation of
  the ten deny rules, proven to reproduce OPA's accept/reject decision on the
  ablation corpus. The §V-B performance baseline.
- `scripts/mcp_agent_demo.py` + two demo plans + golden fixtures: an
  end-to-end demonstration of the MCP tool surface (§IV).
- `docs/experiments/2026-07-07-*.md`: OPA-vs-baseline, MCP demo, and
  30-iteration performance-scaling backing data (Table V).

## v0.4.1 (2026-06-16)

Camera-ready metadata sync. Same code surface as v0.4.0, but
CITATION.cff / README / pyproject.toml internally consistent with the
v0.4.1 version label. Repo metadata now references the Zenodo
**concept DOI** (10.5281/zenodo.19389694) which always resolves to the
latest published version. The paper itself cites the version-specific
DOI for this release (assigned by Zenodo at deposit time).

### Why a patch release
v0.4.0 archive contained `version: "0.3.0"` strings inside CITATION.cff
and pyproject.toml because those files were synced AFTER the v0.4.0 tag.
v0.4.1 closes that gap so the deposited archive is metadata-consistent.

## v0.4.0 (2026-06-16)

Camera-ready release for the IEEE SMC-IT/SCC 2026 paper. DOI:
10.5281/zenodo.20801470.

### Added
- `manifests/k8s/kueue/dra-paper-test/` reproducibility set (6 files)
  for the §V-E DRA Quota Cascade experiment: Kueue Configuration
  patch, ClusterQueue+LocalQueue+ResourceFlavor, ResourceClaimTemplate,
  two-Job test workload, README with apply order and rollback.
- `docs/experiments/2026-06-09-dra-quota-cascade-output.md` — captured
  live-cluster output (host kubeadm K8s v1.36.1 + Kueue v0.17.3 + NVIDIA
  DRA driver + NVIDIA GeForce GT 1030 single-GPU node).

### Notes
- v0.3.0 (the prior tag) is preserved as the §V-D RTX 5080 reference
  point. v0.4.0 adds the §V-E GT 1030 cascade artifacts on top.

## v0.3.0 (2026-04-05)

Tagged release used as the reference artifact for the IEEE SMC-IT/SCC 2026
paper submission (DOI: 10.5281/zenodo.19391965).

### Features
- Real GPU DRA (Dynamic Resource Allocation) experiments: live K8s 1.35 +
  Argo v4.0.1 + Kueue v0.17.0 validation with NVIDIA RTX 5080 against
  `gpu.nvidia.com` DeviceClass.
- Ablation harness (`scripts/ablation_study.py`) producing schema-only,
  policy-only, and combined detection rates across 12 error categories.
- Phase-wise scaling benchmark (`scripts/benchmark_scaling.py`) covering
  parse, OPA, compile, Argo render, and Kueue render at 10–1000 events.

### Testing
- 422 tests across 34 modules (419 passing, 3 skipped pending live cluster
  in author's local environment; 394 passing, 28 skipped in fresh
  environments without OPA binary, k3s, and Argo CLI installed).
- 13 golden translation evaluations comparing rendered IR against
  expected JSON.

### Documentation
- Traceability matrix mapping each schema field, Rego rule, and rendered
  artifact back to ORCHIDE slide references.
- Architecture documentation aligned with paper §III.

## v0.2.1 (2026-04-03)

### Features
- MCP tool expansion: `diff_plans` (structural diff between two mission
  plans) and `check_timeline_conflicts` (interval overlap detection).

### Code quality
- `cli.py` coverage 67% → 99%; total coverage 78% → 84%.

### Documentation
- README counts updated (155 tests, 6 MCP tools at the time).
- Added EUPL-1.2 license badge.

## v0.2.0 (2026-04-03)

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
