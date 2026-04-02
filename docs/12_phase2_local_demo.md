# 12_phase2_local_demo

This document defines the **second-stage local demo surface** for the repository.

## Scope
The demo adds four concrete surfaces:
1. minimal **OPA** execution against a mission plan,
2. **Argo manifest smoke test** against rendered workflow YAML,
3. **Kueue queue examples** with `ResourceFlavor`, `ClusterQueue`, `LocalQueue`, and sample Jobs,
4. a **GPU/CPU fallback workflow sample** that prefers GPU-labelled nodes but keeps a CPU-compatible execution path.

## Why this stage exists
The corrected transcript makes three points especially actionable for a ground-side developer lab:
- mission plans are the control entry point,
- Argo/K3s are execution backends reached through an in-house translation layer,
- applications can be configured for CPU, FPGA, or GPU resources.

This repo therefore demonstrates the translation and validation surfaces first, without pretending to reproduce the onboard runtime itself.

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
- `scripts/opa_smoke.sh`
- `scripts/argo_smoke.sh`
- `scripts/kueue_demo_apply.sh`
- `scripts/demo_phase2.sh`

## Verification boundaries
These files are scaffolded and syntax-checked, but not all external tools were executed in this environment. The repository should still be treated as a **research-backed local demo scaffold**, not as a finished deployment kit.
