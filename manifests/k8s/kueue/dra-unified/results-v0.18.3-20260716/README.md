# Unified DRA live re-verification on Kueue v0.18.3 (2026-07-16)

Host `thc1006-D630MT`, K8s **v1.36.1**, **Kueue v0.18.3** (upgraded from v0.17.3 this
session), `kubernetes-sigs/dra-driver-cpu` v0.2.0 + NVIDIA DRA driver + Quadro K2200.
Drivers publishing ResourceSlices: `dra.cpu` (device `cpudevnuma000`), `gpu.nvidia.com`
(device `gpu-0`). Raw captures: `00-env.txt`, `01`..`04`.

Purpose: re-run §V-E + the three unified-DRA checks on the CURRENT Kueue (v0.18.3,
`KueueDRAIntegration` Beta/default-on) so the extended paper's numbers are on one
version. Config: `deviceClassMappings` map `gpu.nvidia.com -> dra.gpu.nvidia.com` and
`dra.cpu -> dra.cpu`; `dra-unified-cq` covers both (=1 each) + cpu/memory.

## Results

| # | Check | Result on v0.18.3 |
|---|---|---|
| §V-E | `exactly` gpu.nvidia.com cascade | GPU quota-counted: `dra.gpu.nvidia.com` usage=1; job-2 gated "insufficient unused quota for dra.gpu.nvidia.com ... 1 more needed" |
| 1 | `exactly` dra.cpu cascade (S2) | CPU quota-counted: `dra.cpu` usage=1; job-2 gated "insufficient unused quota for dra.cpu ... 1 more needed" |
| 2 | `firstAvailable` 2 plain Pods, no Kueue (S1) | scheduler cross-driver fallback: `accel-demo-1 -> gpu-0 (gpu.nvidia.com)`, `accel-demo-2 -> cpudevnuma000 (dra.cpu)` |
| 3 | `firstAvailable` under a Kueue queue (S2 boundary) | **REJECTED**: Workload `QuotaReserved=False reason=Inadmissible`, msg "ResourceClaimTemplate accel-first-available: FirstAvailable device selection is not supported"; Job stays Suspended; nothing counted |

## KEY FINDING — Kueue hard-REJECTS firstAvailable (consistent v0.17.3 -> v0.18.3; NOT a version change)

The doc-silent question ("what does Kueue do with a firstAvailable workload?") is
answered by observation: **Kueue v0.18.3 HARD-REJECTS it as `Inadmissible` with an
explicit "FirstAvailable device selection is not supported" message.** The Job stays
Suspended and nothing is quota-counted.

CORRECTION (cross-checked against memory `project_dra_cpu_gpu_postsubmission`): the
**07-09 run on v0.17.3 already observed the SAME Inadmissible rejection**. So this is NOT
a behavior change between versions — rejection is consistent on both v0.17.3 and v0.18.3.
What is actually stale is only the manifest/compiler COMMENTS (`04`, `05`, `00`, and
`compiler.py` render_kueue_job "this Job is admitted on its cpu/memory only") that
PREDICTED a soft "admit-and-ignore-the-accelerator" outcome. That prediction never matched
either run and must be corrected to the observed rejection (version-independent).

Implications:
- Paper S2/S3: the boundary between scheduler-level `firstAvailable` fallback and Kueue
  `exactly` quota is HARD-ENFORCED by Kueue (rejection), not a soft "not counted". State
  this with the captured Inadmissible message; observed consistently on v0.17.3 (07-09) and
  v0.18.3 (07-16).
- Compiler follow-up (DECISION NEEDED, not done here): `render_kueue_job(dra_fallback=True)`
  emits a `firstAvailable` claim; under Kueue v0.18.3 such a Job is Inadmissible. So the
  firstAvailable path should target the SCHEDULER-level route (Argo / plain Pods), and the
  Kueue route should use `exactly` claims. The compiler comment claiming Kueue admits such
  a Job on cpu/memory is stale and the render path may warrant guarding.
- Manifest comments (`00/04/05`) to be updated to the observed v0.18.3 rejection.

Cluster left tidy (all demo Jobs/Pods deleted; Kueue healthy). Pre-upgrade backup at
`scratchpad/live-2026-07-16/backup/` (kueue-manager-config, deployment, queues) for rollback.
