# 12_phase2_local_demo

This document defines the **second-stage local demo surface** for the repository.

## Scope
The demo adds four concrete surfaces:
1. minimal **OPA** execution against a mission plan,
2. **Argo manifest smoke test** against rendered workflow YAML,
3. **Kueue queue examples** with `ResourceFlavor`, `ClusterQueue`, `LocalQueue`, and sample Jobs,
4. a **GPU/CPU fallback workflow sample** that prefers GPU-labelled nodes but keeps a CPU-compatible execution path.

## Why this stage exists
The ORCHIDE KubeCon EU 2026 presentation (slides 9, 10, 23) confirms three points actionable for a ground-side developer lab:
- mission plans are the control entry point (slide 9),
- Argo/K3s are execution backends reached through a custom translation layer (slide 23),
- applications can be configured for CPU, FPGA, or GPU resources (slide 14).

This repo demonstrates the ground-side translation and validation surfaces, complementing ORCHIDE's onboard orchestrator without reproducing it.

## Demo commands
```bash
make render-samples
make argo-smoke
make opa-smoke   # requires official OPA CLI in PATH
```

If you have a cluster:
```bash
bash scripts/install_k3s.sh
bash scripts/install_argo.sh
bash scripts/install_kueue.sh
bash scripts/kueue_demo_apply.sh
kubectl apply -f manifests/k8s/argo/00-workflow-executor-rbac.yaml
```

## GPU/CPU fallback interpretation
This demo implements **soft fallback**, not hard device-plugin failover:
- the workflow step is marked as `resource_class: gpu`,
- it declares `fallback_resource_class: cpu`,
- it uses **preferred** node affinity for GPU-labelled nodes,
- the container command can still execute a CPU-compatible path when no GPU device is present.

This matches the transcript’s statement that applications are configured according to CPU / FPGA / GPU needs, but avoids claiming an onboard ukAccel-compatible implementation.

## Files added in stage 2
- `configs/mission_plans/sample_gpu_cpu_fallback.yaml`
- `manifests/examples/argo-gpu-cpu-fallback.yaml`
- `manifests/k8s/kueue/*.yaml`
- `manifests/k8s/argo/00-workflow-executor-rbac.yaml`
- `scripts/opa_smoke.sh`
- `scripts/argo_smoke.sh`
- `scripts/kueue_demo_apply.sh`
- `scripts/demo_phase2.sh`

## Agent workflow hardening

The repository includes a Claude Code hook that automatically verifies changes after every file write or edit.

### Configuration
- `.claude/settings.json` — sets default permission mode to `plan` and registers the PostToolUse hook.
- `.claude/hooks/run-verify-async.sh` — runs `verify.py` on every change; conditionally runs `pytest` or `eval_runner` depending on which subtree was modified.

### How it works
1. Claude Code writes or edits a file.
2. The PostToolUse hook fires asynchronously.
3. The hook resolves the modified file path from the tool input JSON.
4. A path traversal guard ensures only project files are checked.
5. `python3 scripts/verify.py` runs unconditionally.
6. If the change is in `src/`, `tests/`, or `scripts/`, `pytest` also runs.
7. If the change is in `configs/` or `evals/`, `eval_runner` also runs.

### Overriding defaults
To switch out of plan mode for a session, use `/permissions` inside Claude Code or set a local override in `.claude/settings.local.json`:
```json
{ "permissions": { "defaultMode": "acceptEdits" } }
```

## Kueue integration smoke test

After installing Kueue and applying the demo queue objects, you can run an end-to-end admission test:

```bash
bash scripts/kueue_integration_smoke.sh configs/mission_plans/sample_gpu_cpu_fallback.yaml
```

This script:
1. Compiles a mission plan into a Kueue-compatible Job via `render-kueue`.
2. Submits the Job to the cluster with `kubectl create`.
3. Verifies the Workload is created and admitted by Kueue's ClusterQueue.
4. Cleans up the Job on exit.

## Naming and timeline hardening (2026-04)
- Workflow object names use collision-resistant sanitization: when names exceed Kubernetes limits, a stable hash suffix is appended instead of silent truncation.
- Argo DAG task names are generated from indexed template names to avoid duplicate-task collisions when step labels sanitize to the same value.
- Timeline overlap checking is centralized in `compiler.py` and reused by MCP `check_timeline_conflicts` to avoid drift between CLI/library and MCP behavior.

## Live validation portability hardening (2026-04)
- `scripts/validate_live_cluster.sh` now waits on Argo workflow completion via internal polling with `ARGO_TIMEOUT_SECONDS`, avoiding dependency on GNU `timeout` behavior differences across environments.
- Argo submission uses a dedicated runtime service account (`orbital-workflow-runner`) instead of the namespace `default` service account.
- Kueue admission checks resolve the workload by Job UID label (`kueue.x-k8s.io/job-uid`), following Kueue troubleshooting guidance and avoiding namespace-wide false positives.

## Verification boundaries
These files are scaffolded and syntax-checked, but not all external tools were executed in this environment. The repository should still be treated as a **research-backed local demo scaffold**, not as a finished deployment kit.
