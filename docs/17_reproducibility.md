# Reproducibility: DRA experiments (v0.5.0)

Binds the DRA experiments in the IEEE SMC-IT/SCC 2026 paper and its extended arXiv
version to the exact artifacts, versions, and commit that produced them, so a reader
can check them out and re-run.

## Version / commit matrix

| Component | Version | Notes |
|---|---|---|
| This repo | tag **v0.5.0** | schema/policy/IR/renderer + the `dra-unified` set |
| Kubernetes | **v1.36.1** (kubeadm) | host `thc1006-D630MT` (Intel i5-7400, Quadro K2200) |
| containerd | 2.2.1 | NRI enabled (required by dra-driver-cpu) |
| Kueue | **v0.18.3** | upgraded from v0.17.3; `KueueDRAIntegration` Beta/default-on |
| NVIDIA DRA driver | publishes `gpu.nvidia.com` DeviceClass | K2200 as the DRA-allocatable GPU |
| kubernetes-sigs/dra-driver-cpu | **v0.2.0** | publishes `dra.cpu` DeviceClass; see kubelet-root-dir note |
| Argo Workflows | v4.0.1 | static lint |
| OPA | v1.15.1 | policy evaluation |

Captured environment: `manifests/k8s/kueue/dra-unified/results-v0.18.3-20260716/00-env.txt`.

## Paper claim -> artifact -> captured output

| Paper claim | Manifests | Captured output (`results-v0.18.3-20260716/`) |
|---|---|---|
| GPU admission cascade (`exactly` gpu.nvidia.com) | `dra-paper-test/00-03` | `04-vE-gpu-cascade.txt` |
| Unified CPU quota cascade (`exactly` dra.cpu) | `dra-unified/00,01,03` | `01-check1-exactly-cpu.txt` |
| Scheduler-level `firstAvailable` fallback (2 plain Pods) | `dra-unified/02,04` | `02-check2-firstavailable-fallback.txt` |
| Boundary: `firstAvailable` under Kueue = Inadmissible | `dra-unified/05` | `03-check3-firstavailable-under-kueue.txt` |
| Compiler `--dra-fallback` output is Kueue-admitted | rendered from `configs/mission_plans/sample_gpu_cpu_fallback.yaml` | `05-phaseA-compiler-output-admitted.txt` |

## Reproduce

1. Install dra-driver-cpu with the kubelet-root-dir fix:
   `bash manifests/k8s/kueue/dra-unified/install-dra-driver-cpu.sh`
   (auto-detects a relocated kubelet `--root-dir`).
2. Upgrade Kueue to v0.18.3 and apply the unified Configuration
   `dra-unified/00-kueue-configuration-patch.yaml` (`deviceClassMappings` for both
   `gpu.nvidia.com` and `dra.cpu`); restart the controller.
3. Apply `01-namespace-and-queue` + `02-resourceclaimtemplates`, then run `03`
   (CPU cascade), `04` (firstAvailable Pods), and `05` (firstAvailable under Kueue)
   one at a time; compare against the captured outputs above.
4. Render the compiler path:
   `python -m orbital_mission_compiler.cli render-kueue --input
   configs/mission_plans/sample_gpu_cpu_fallback.yaml --output-dir /tmp/out
   --namespace dra-unified --queue dra-unified-lq --dra-fallback`
   -> the Kueue Job references the `exactly` GPU RCT (never `firstAvailable`).

## Honest notes

- **dra-driver-cpu kubelet-root-dir**: the v0.2.0 Helm chart hardcodes
  `/var/lib/kubelet`; on a relocated `--root-dir` the registrar socket lands where
  the kubelet does not watch. The install script applies a documented local
  workaround (repoint the `plugin-registry` hostPath). Upstream fix tracked at
  kubernetes-sigs/dra-driver-cpu#231 (open as of 2026-07).
- **firstAvailable + Kueue boundary**: Kueue quota-counts only `exactly` device
  requests; a `firstAvailable` claim submitted as a Kueue Job is rejected
  Inadmissible ("FirstAvailable device selection is not supported"), observed
  identically on Kueue v0.17.3, v0.18.3, and v0.19.0/main. The scheduler-level
  fallback (firstAvailable, plain Pod / Argo route) and Kueue quota (exactly) are
  therefore disjoint capabilities today; the compiler renders the `exactly` claim
  for the Kueue route.
