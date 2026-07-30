# Unified GPU + CPU DRA (reference set)

Post-submission R&D for arXiv v2 / v0.4.3. **Not** part of the frozen camera-ready
(v0.4.2, DOI 21228150). Extends the §V-E single-class GPU cascade
(`../dra-paper-test/`) to a **unified GPU + CPU** Dynamic Resource Allocation setup,
and demonstrates a **scheduler-level GPU→CPU fallback** that replaces the paper's
§V-D runtime env-var switch.

**Verified environment (2026-07-09):** host kubeadm cluster `thc1006-d630mt`
(Intel i5-7400, 4 cores, 1 NUMA node), K8s v1.36.1, Kueue v0.17.3, NVIDIA DRA
driver + **Quadro K2200**, `kubernetes-sigs/dra-driver-cpu` **v0.2.0** (alpha).

## Two mechanisms, one boundary

DRA gives two ways to express "prefer GPU, else CPU"; they live on opposite sides
of one hard boundary that this set makes explicit.

| | `exactly` claim | `firstAvailable` claim |
|---|---|---|
| Expresses | one specific device class | prefer-A-else-B, scheduler chooses |
| Kueue quota-counted? | **Yes** | **No** (Kueue supports only `exactly` — [Kueue DRA docs](https://kueue.sigs.k8s.io/docs/tasks/run/dra/)) |
| Here | `single-cpu`, `single-gpu` → admission cascade (demo 1) | `accel-first-available` → scheduler fallback (demo 2) |

So "unified quota" means **each device class is independently quota-countable**
(`dra.gpu.nvidia.com` + `dra.cpu`, via 00's `deviceClassMappings`), not that a
single fallback claim is counted. The fallback claim is a scheduler construct.

## 0. Prerequisites — install dra-driver-cpu (with the path-fix)

The dra-driver-cpu v0.2.0 Helm chart hardcodes `/var/lib/kubelet` and has no
override flag; on a cluster with a relocated kubelet root-dir (this host:
`/mnt/fast/k8s/kubelet`) the driver never registers ("context deadline exceeded")
until its `plugin-registry` hostPath is repointed. The install script detects the
root-dir and applies the fix:

```bash
bash install-dra-driver-cpu.sh          # auto-detects kubelet root-dir
# or: KUBELET_ROOT_DIR=/custom/path bash install-dra-driver-cpu.sh
```

Also required: containerd ≥ 2.0 with NRI enabled; kubelet CPUManager policy
`none` (dra-driver-cpu is incompatible with the `static` policy); DRA feature
gates on.

## 1. Apply the Kueue configuration + queue

```bash
kubectl get cm -n kueue-system kueue-manager-config -o yaml > ~/kueue-config-backup.yaml
kubectl apply -f 00-kueue-configuration-patch.yaml
kubectl rollout restart deployment/kueue-controller-manager -n kueue-system
# ensure the deployment args carry BOTH feature gates (NOT the ConfigMap):
#   Kueue v0.17.x (the verified environment above):
#     --feature-gates=DRAExtendedResources=true,DynamicResourceAllocation=true
#   Kueue v0.18:
#     --feature-gates=KueueDRAIntegration=true,KueueDRAIntegrationExtendedResource=true
#   Kueue v0.19: no gate argument
#
# The gates were renamed in v0.18 to avoid colliding with the upstream Kubernetes
# ones, and v0.19 enables the integration without them: verified on this cluster,
# whose controller runs with only --config and --zap-log-level while
# dra.gpu.nvidia.com and dra.cpu are tracked in ClusterQueue status. Use the line
# matching the Kueue you are running, not the one above the results you are
# reading -- the captured results in results-v0.18.3-20260716/ were produced on
# v0.18.3, later than the v0.17.3 environment this README's header records.
kubectl apply -f 01-namespace-and-queue.yaml
kubectl apply -f 02-resourceclaimtemplates.yaml
```

Run the demos **one at a time** (this node has exactly one GPU and one grouped
CPU device, so concurrent demos contend).

## 2. Demo 1 — CPU DRA under Kueue quota (`exactly`, cascade)

```bash
kubectl apply -f 03-jobs-exactly-cpu.yaml
kubectl -n dra-unified get jobs,pods -w
```
`dra.cpu` nominalQuota=1 → one job admitted, one suspended, then cascade-admitted
on completion — the §V-E cascade, proving the `dra.cpu` mapping is quota-counted.

## 3. Demo 2 — scheduler-level GPU→CPU fallback (`firstAvailable`)

```bash
kubectl apply -f 04-firstavailable-pods.yaml
kubectl get resourceclaim -n dra-unified \
  -o 'custom-columns=NAME:.metadata.name,DEVICE:.status.allocation.devices.results[*].device'
```
Two identical Pods, same claim: **demo-1 → `gpu-0` (K2200), demo-2 → `cpudevnuma000`
(dra.cpu)**. Same spec, the scheduler falls back. Verified 2026-07-09.

## 4. Demo 3 — the boundary: `firstAvailable` under a Kueue queue

```bash
kubectl apply -f 05-firstavailable-job-kueue.yaml
kubectl -n dra-unified get workloads -o wide
```
Observed 2026-07-09: Kueue marks the Workload **Inadmissible** — `QuotaReserved=False`,
`FirstAvailable device selection is not supported`; the Job stays Suspended. Kueue
rejects the claim outright (it does not silently admit on cpu/memory). Full transcript
in `docs/experiments/2026-07-09-unified-dra-cpu-integration.md`.

## Compiler integration

The `accel-first-available` template is the same `firstAvailable` request the
compiler emits for a GPU-primary/CPU-fallback step:

```bash
python -m orbital_mission_compiler.cli render-kueue \
  --input configs/mission_plans/demo_gpu_fallback_fixed.yaml \
  --output-dir out/dra-fallback --dra-fallback --namespace dra-unified
```
This writes two files: `*-kueue.yaml` holds the `exactly` GPU claim and the Job
admitted on it, and `*-scheduler-fallback.yaml` holds the `firstAvailable` claim
for the non-Kueue route. Without `--dra-fallback` the compiler keeps the §V-D
runtime env-var switch (portable default); the flag opts into the
scheduler-level DRA claim. See
`DRA_DEVICE_CLASS` in `src/orbital_mission_compiler/compiler.py`.

## Limitations (honest)

- `firstAvailable` is **not** Kueue-quota-counted (Kueue alpha limitation) — the
  fallback is scheduler-level only.
- **No FPGA path**: no FPGA DRA driver exists, so FPGA steps keep the legacy
  static-request path; `DRA_DEVICE_CLASS` deliberately omits FPGA.
- dra-driver-cpu is **alpha (v0.2.0)**; the path-fix is specific to relocated
  kubelet root-dirs.
- Single-node, single-NUMA host: the CPU pool is one grouped device.

## Teardown

```bash
kubectl delete -f 05-firstavailable-job-kueue.yaml --ignore-not-found
kubectl delete -f 04-firstavailable-pods.yaml --ignore-not-found
kubectl delete -f 03-jobs-exactly-cpu.yaml --ignore-not-found
kubectl delete -f 02-resourceclaimtemplates.yaml -f 01-namespace-and-queue.yaml --ignore-not-found
kubectl apply -f ~/kueue-config-backup.yaml   # restore original Kueue config
kubectl rollout restart deployment/kueue-controller-manager -n kueue-system
# optional: helm uninstall dra-driver-cpu -n kube-system
```
