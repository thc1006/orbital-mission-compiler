# Unified GPU + CPU DRA and scheduler-level fallback — 2026-07-09

Post-submission R&D on `thc1006-d630mt` (host kubeadm K8s v1.36.1, Kueue v0.17.3,
NVIDIA DRA driver + **Quadro K2200**, `kubernetes-sigs/dra-driver-cpu` **v0.2.0**).
Feeds **arXiv v2 / v0.4.3**. It does **not** modify the frozen camera-ready
(v0.4.2, DOI 21228150) or its claims.

Reproducibility set: `manifests/k8s/kueue/dra-unified/` (+ `install-dra-driver-cpu.sh`).

## 1. The gap this closes

The compiler models "run on GPU, fall back to CPU" per step
(`WorkflowStep.fallback_resource_class`), but §V-D renders that fallback as a
**runtime env-var switch** (`ORBITAL_FALLBACK_RESOURCE_CLASS`): the container
decides at run time. That needs cooperating container logic and is invisible to
the scheduler. DRA v1's `firstAvailable` request expresses the same intent as a
**scheduler-level** decision. This note records making the CPU DRA path actually
work on the cluster, wiring `firstAvailable` into the compiler as an opt-in, and
mapping the honest boundary against Kueue admission.

## 2. dra-driver-cpu was not incompatible — it was a kubelet-root-dir path bug

An earlier session concluded dra-driver-cpu v0.2.0 was incompatible with kubelet
1.36 (it crash-looped with `driver failed to start: context deadline exceeded`).
That conclusion was **wrong**. The `DRAResourceHealth Unimplemented` error loop
from the GPU driver was a red herring. Root cause:

- This cluster relocated the kubelet root-dir to `/mnt/fast/k8s/kubelet`
  (`--root-dir` in `kubeadm-flags.env`), so the kubelet's plugin-watcher watches
  `/mnt/fast/k8s/kubelet/plugins_registry/`.
- The dra-driver-cpu v0.2.0 Helm chart **hardcodes** `/var/lib/kubelet` for its
  `plugin-registry` hostPath and exposes **no** override flag (`dracpu --help`
  has no kubelet-path option). Its registrar socket landed in
  `/var/lib/kubelet/plugins_registry/` — a directory the kubelet never watches —
  so registration never happened and the driver timed out after 30s. The NVIDIA
  GPU driver works because it is configured (`KUBELET_REGISTRAR_DIRECTORY_PATH`)
  for the real root-dir.

**Fix:** repoint only the `plugin-registry` hostPath at
`/mnt/fast/k8s/kubelet/plugins_registry`. The DRA endpoint socket the driver
advertises (`/var/lib/kubelet/plugins/dra.cpu/dra.sock`) is left unchanged because
the kubelet dials that advertised path directly. After the patch the driver
registered, published a `dra.cpu` ResourceSlice (one grouped per-NUMA device,
`numCPUs=4`), and NRI pinned a test container: `NodePrepareResources` →
`assigned=0-3` → NRI `CreateContainer` → container `Cpus_allowed_list: 0-3`.

## 3. Empirical results (all from `manifests/k8s/kueue/dra-unified/`)

**GPU DRA cascade reproduced on K2200** (the §V-E experiment on current hardware):
job-1 admitted, job-2 suspended on quota, cascade-admitted on completion; both
`Admitted=True Finished=True`; cascade gap ≈ 5 s, matching the historical GT 1030.

**Demo 1 — CPU DRA is Kueue-quota-counted (`exactly`, cascade).** Two Jobs each
claim one `dra.cpu` device (`single-cpu` template); `dra.cpu` nominalQuota = 1:

- job-1 `Admitted=True`, quota usage `{cpu: 100m, dra.cpu: 1, memory: 64Mi}`.
- job-2 Pending: `insufficient unused quota for dra.cpu in flavor
  dra-unified-flavor, 1 more needed` → after job-1 finished, `QuotaReserved` →
  `Admitted`. Both `Complete 1/1`.

So the new `dra.cpu` `deviceClassMappings` entry makes CPU DRA quota-countable —
the "unified quota" is real, per-class.

**Demo 2 — scheduler-level GPU→CPU fallback (`firstAvailable`, plain Pods).** Two
identical Pods, same `accel-first-available` claim:

- `accel-demo-1` → `gpu-0` (gpu.nvidia.com, K2200).
- `accel-demo-2` → `cpudevnuma000` (dra.cpu).

Same spec; the scheduler falls back when the GPU is taken. This is the declarative
replacement for the §V-D runtime env-var switch.

**Demo 3 — the boundary: `firstAvailable` under a Kueue queue is rejected.** The
same claim as a Kueue Job is marked **Inadmissible**:

```
QuotaReserved=False  reason=Inadmissible
  spec.podSets[0].template.spec.resourceClaims[0].devices.requests[0]:
  Invalid value: null: ResourceClaimTemplate accel-first-available:
  FirstAvailable device selection is not supported
```

This confirms empirically what the Kueue docs state: quota counting supports only
`exactly` requests. `firstAvailable` is a scheduler-level construct, not
admission-aware.

## 4. Compiler integration (opt-in, render-layer only)

`render-kueue --dra-fallback` (`cli.py`) makes `render_resource_claim_templates`
emit a `firstAvailable` request for any step whose `resource_class` and
`fallback_resource_class` are both driver-backed (`DRA_DEVICE_CLASS` = {GPU →
gpu.nvidia.com, CPU → dra.cpu}). That claim goes to its own
`<name>-scheduler-fallback.yaml`, not into the `<name>-kueue.yaml` bundle: Kueue
admits the Job on the `exactly` claim and never references the `firstAvailable`
one, so shipping both in one file reads as though the admitted Job falls back.
Each rendered template carries `orbital/dra-route` (`scheduler` or `kueue`), so
the applied object states which route may reference it. Default off preserves the §V-D env-var path
(portable). No schema or policy change: Rego Rule 4 already requires accelerator
steps to declare a fallback. FPGA is deliberately excluded (no FPGA DRA driver),
so FPGA steps keep the legacy static-request path. Guarded by `TestFirstAvailable`
in `tests/test_kueue_dra.py`.

## 5. Design recommendation and limitations

Route GPU and CPU through DRA as a **unifying abstraction, but keep it opt-in**;
standard CPU `requests` stay the portable default. The elegant win is that
`fallback_resource_class` becomes a scheduler-level `firstAvailable` decision
rather than a runtime env-var hack. Honest limits:

- `firstAvailable` is **not** Kueue-quota-counted (Demo 3) — the fallback is
  scheduler-level only; unified admission for a fallback claim is future work,
  pending Kueue support.
- **No FPGA DRA** (no driver).
- dra-driver-cpu is **alpha (v0.2.0)**; the path-fix is specific to relocated
  kubelet root-dirs; single-node, single-NUMA host (one grouped CPU device).

Positioning is unchanged: this is a ground-side compiler emitting artifacts that
cloud-native satellite runtimes consume — not an onboard or flight-ready claim.
