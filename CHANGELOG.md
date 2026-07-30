# Changelog

## Unreleased

### Changed
- A YAML merge key followed by an explicit key is accepted again. Scanning for
  duplicates after the merge source was flattened in conflated an override with a
  key written twice, and rejected a document whose meaning YAML defines. The
  source a `<<:` pulls from is scanned in its own right, since it is a mapping
  the author wrote and is spliced in without ever being constructed: a step
  shared through an anchor could carry `resource_class` twice and load as the
  second one, reading as GPU and running as CPU. `<<` written twice in one
  mapping, and a mapping that merges itself, are refused for the same reason.
- Rendered objects are refused when their annotations would exceed the 262144
  bytes the API server accepts, rather than failing at apply.
- Files are published by renaming a sibling temporary file into place. Writing
  the destination directly follows a symlink, which redirects the write outside
  the output directory and past the ownership check; a symlink at a planned path
  is now refused outright, including one whose target does not exist yet --
  `Path.exists()` follows the link, so such a path read as free space. The
  published file keeps the mode the umask would have given it, because `mkstemp`
  creates 0600 and a rename keeps it, which would have narrowed every artifact
  to the user that rendered it.
- A quoted number must read as the number it becomes. `priority: "50"` is how a
  templated plan writes fifty and stays legal, but pydantic coerces a string with
  Python's numeric grammar, which is wider than the one a reader applies: `'1_0'`
  is ten, `'6e2'` is six hundred. That is the ambiguity the strict loader refuses
  a repeated key for, so it is refused here too.
- Every rendered Kubernetes object is held to the annotation budget. The two
  ResourceClaimTemplate renderers wrote the raw mission id without it, so a
  direct library call could build an object the API server refuses for size
  while the Workflow and Job for the same intent were refused. The budget is the
  API server's own object limit; a client-side `kubectl apply` additionally
  stores the object in a last-applied annotation, which is not counted here.
- A directory entry that cannot be read no longer reads as absent.
  `Path.glob` swallows the error scandir raises, so an unreadable output
  directory came back empty: nothing stale, and a `--prune` that reported
  nothing to do. Reading an artifact also refuses anything that is not a regular
  file -- a fifo named `*.yaml` blocked the read until someone wrote to it, and
  that read happens while the publish lock is held.
- The OPA input is serialised with `allow_nan=False`, and a payload that cannot
  be serialised, or an executable that has gone away since it was found, is a
  fail-closed engine result rather than an exception. The schema path already
  rejects a non-finite number, but `eval_policy` also takes a plain dict.
- The MCP tools require the plan path to be a file. A directory passed
  `exists()` and then failed inside the loader, escaping as a raw tool exception
  instead of the structured error every other rejection produces.
- A boolean is no longer read as an orbit or a duration, and a number is no
  longer read as a timestamp. `orbit: true` became orbit 1 and `timestamp: 0`
  became 1970-01-01, both of which name artifacts after something nobody wrote.
- `render-kueue` reports `status: "projected"` with `complete_service: false`
  when a service has more steps than the one container a Kueue Job carries, so
  automation keying on status does not treat an admission probe as the service.
- `--prune` and the overwrite check identify a mission by a fingerprint of its raw
  id, not by the sanitized `mission-id` label. Sanitizing is lossy: `foo_bar` and
  `foo.bar` both become `foo-bar`, so one mission could prune the other's
  artifacts, and with the same service and timestamp the second render replaced
  the first outright. A render now refuses to overwrite a file it does not own.
- The Kueue Job derives its resources and its own annotations from the step it
  runs. They came from the whole service, so a GPU step followed by an FPGA step
  was rejected as one Pod asking for both, although the Job holds only the GPU
  step. That service is legal and the Argo render expresses it as separate Pods.
- `render-argo` leaves an ordinary Workflow namespace-less again, so the
  namespace is chosen at `argo submit -n` or `kubectl apply -n` time.
  `--dra-fallback` still stamps one, because a claim template is namespaced and
  the Workflow that references it has to match.
- Mission-plan models reject non-finite numbers, and blank mission, service and
  instrument identifiers. `duration_seconds: .inf` is valid YAML, satisfies
  `ge=0`, and made the timeline analysis report a conflict with an event months
  away.
- Mission-plan models reject unknown fields. Pydantic ignores them by default, so
  `execution_mod: parallel` left the service sequential and
  `fallback_resource_clas: cpu` left an accelerator step with no fallback, and the
  plan was still reported schema-valid. `priority` also rejects a boolean, since
  YAML reads `yes`/`on` as one and Python reads it as 1, the lowest ORCHIDE tier.
- The Kueue Job is labelled `standalone-primary-step`, not `admission-proxy`. It
  is a workload of its own: it reserves quota for itself, does not gate the Argo
  Workflow, and applying both artifacts runs the primary step twice. Kueue's own
  Argo integration works the other way round, admitting each Pod Argo creates via
  a queue-name label, and is per-Pod rather than whole-workflow atomic.
- `--prune` deletes only artifacts belonging to the missions the current render
  wrote, identified by a `managed-by` label this tool stamps rather than by the
  `orbital/` prefix an operator may also use. Another mission's output in the
  same directory, the cluster-scoped priority classes, and a hand-written file
  are all out of scope.
- `render-argo --namespace` is stamped on the Workflow in every mode. It was
  applied only when a DRA claim template was also emitted, so a plain render
  accepted the flag and produced a namespace-less manifest.
- A resource request may not be negative, a ServiceAccount name is validated
  label by label, and step images, names and node-selector keys and values are
  checked when the plan loads.
- The Kueue Job records the step it runs and the steps it does not. A Kueue Job
  carries one container, so a multi-step service is admitted as its primary step;
  that projection is now on the object (`orbital/executed-step`,
  `orbital/steps-not-in-this-job`), in the CLI output, and in what the live
  validation reports, instead of a complete-looking artifact.
- A ServiceAccount name is validated as a DNS subdomain and a queue name as a
  subdomain capped at a label value's 63 characters. Both were checked as DNS
  labels, which rejects the dots and lengths the API server accepts (verified
  against a live API server).
- `render-kueue --dra-fallback` writes the scheduler-route `firstAvailable` claim
  to its own `*-scheduler-fallback.yaml` instead of the `*-kueue.yaml` bundle. The
  Job is admitted on the `exactly` claim and never references the `firstAvailable`
  one, so a single file read as though the admitted Job falls back, and applying it
  created a claim template nothing in the bundle consumed. Each rendered template
  now carries an `orbital/dra-route` label (`scheduler` or `kueue`).
- Workflow names are deduplicated after Kubernetes name normalization. Service ids
  that differ only in characters normalization drops (`foo_bar` vs `foo.bar`)
  previously produced one object name and one file, losing all but one service.
- A mission plan with a duplicate YAML mapping key is rejected rather than resolved
  to the last value.
- Operator-supplied `--namespace`, `--queue`, `--service-account` and the Kueue
  cpu/memory requests are validated before rendering, instead of being copied into
  the manifest and failing at `kubectl apply`. See the name-class entry above for
  which class each one is checked against.

### Added
- `render-argo --argo-lint`, an opt-in gate that renders into a staging directory,
  lints the set the output directory will hold, and publishes only if the linter
  accepts. Publishing is all-or-nothing: displaced files are kept aside until the
  whole set lands and restored if it does not, and concurrent publishes into one
  directory are serialised. A lint verdict exits 1; a gate that could not run --
  CLI absent, timeout, signal, an exit status that is not a verdict, or nothing
  rendered to lint -- exits 2.
- `--prune` on `render-argo` and `render-kueue`. A render writes what the plan
  describes; it does not empty the output directory, so after a plan shrinks the
  manifests for what is gone stay behind and `kubectl apply -f <dir>` redeploys
  them. They are now reported under `stale` and removed only when asked, and only
  when they carry this tool's own labels.
- `render-argo --service-account`, for the kubectl-apply path: `argo submit
  --serviceaccount` cannot be used on the multi-doc `--dra-fallback` bundle,
  because `argo submit` drops the ResourceClaimTemplate document.

### Fixed
- The MCP `render_argo` tool reads the plan once. It judged the file and then
  handed the path to the writer, which read it again, so a file replaced between
  the two reads was rendered under a verdict reached on the content it replaced.
- Kubernetes quantity validation follows the documented `resource.Quantity`
  grammar rather than a character class, which accepted `.`, `1..2`, `1e`,
  `1.2.3` and `1K`. Checked differentially against `resource.ParseQuantity`.
- The MCP `render_argo` tool now fails closed with `policy_engine_unavailable`
  like the other tools, instead of calling the renderer directly and surfacing a
  raw exception.
- A required CI job installs the MCP extra and runs the MCP tests, treating a skip
  as a failure. FastMCP is in a separate extra that CI did not install, and the
  MCP test modules skip themselves without it, so the MCP surface was never
  exercised by the required check.
- CI installs the pinned Argo CLI and lints with it. The Argo smoke previously
  printed "argo CLI not found; skipped argo lint" and still passed, so its only
  real gate never ran.

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
