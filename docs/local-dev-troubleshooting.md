# Local Development Troubleshooting

> **Last verified: 2026-05-09.** Re-verify against current CNI / Argo /
> Kueue / kernel versions before relying on these recipes verbatim.

This file documents real failures encountered while reproducing paper
§V-D's live cluster experiments on a dev host (Ubuntu 24.04, kernel 6.17,
Docker 29.4, hostname referred to throughout as `<dev-host>`) and their
resolutions. Adjust the hostname to match your machine.

## TL;DR — paper §V-D reproducibility recipe

```bash
# 1. Ensure /var/lib/cni/multus exists (Multus scratch dir; see §A)
sudo mkdir -p /var/lib/cni/multus && sudo chmod 755 /var/lib/cni/multus

# 2. Use the existing host kubeadm cluster (NOT kind/k3s; see §B)
sudo install -m 0600 -o "$USER" -g "$USER" \
  /etc/kubernetes/admin.conf /tmp/kubeconfig-host
export KUBECONFIG=/tmp/kubeconfig-host

# 3. Install Argo + Kueue with --server-side (see §C)
kubectl create namespace argo
kubectl apply --server-side -n argo \
  -f https://github.com/argoproj/argo-workflows/releases/download/v4.0.1/install.yaml
kubectl apply --server-side \
  -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.17.0/manifests.yaml

# 4. Apply queue and SA manifests (NOTE: namespace must exist first)
kubectl apply -f manifests/k8s/kueue/        # creates orbital-demo namespace + queues
kubectl apply -f manifests/k8s/argo/00-workflow-executor-rbac.yaml

# 5. Validate
PYTHON_BIN=$PWD/.venv-verify/bin/python \
PATH="$PWD/.venv-verify/bin:$PATH" \
KUBECONFIG=/tmp/kubeconfig-host \
bash scripts/validate_live_cluster.sh
# Expected: PASS: 12  FAIL: 0  RESULT: PASS
```

---

## §A. Pods stuck `ContainerCreating` with `saveScratchNetConf: no such file`

### Symptom

```
FailedCreatePodSandBox: ... Multus: error saving the delegates:
saveScratchNetConf: failed to write container data in the path
"/var/lib/cni/multus/<sandbox>": no such file or directory
```

Often misdiagnosed as TLS issue because controller pod logs cascade into
`tls: failed to verify certificate: x509: certificate signed by unknown
authority (possibly because of "crypto/rsa: verification error" while
trying to verify candidate authority certificate "kubernetes")`.

### Root cause

Multus CNI's scratch directory `/var/lib/cni/multus/` was deleted (by an
update, autoremove, or manual cleanup). The `kube-multus-ds` daemon was
running with a stale handle to the missing dir, so even `mkdir` on the
host doesn't fix it without restarting the daemon.

### Fix

```bash
sudo mkdir -p /var/lib/cni/multus
sudo chmod 755 /var/lib/cni/multus
KUBECONFIG=/tmp/kubeconfig-host kubectl delete pod -n kube-system -l app=multus
# Wait ~30s for replacement multus pod, then retry the failing pods.
```

### Verification

```bash
openssl verify -CAfile /etc/kubernetes/pki/ca.crt \
  /etc/kubernetes/pki/apiserver.crt
# If "OK", certs are fine — the Go x509 error is downstream of CNI failure.
```

---

## §B. Don't install kind or k3s — host already runs kubeadm K8s

### Symptom

```bash
sudo bash scripts/install_k3s.sh
# fails: listen tcp :6443: bind: address already in use
```

Or kind clusters spin up but pods immediately CrashLoop with the §A
symptom because Multus shim is configured for the host network
namespace, not Docker's.

### Root cause

The host `<dev-host>` runs a full **kubeadm K8s v1.35.4 control plane
as a systemd service** (`kubelet.service`). This is the cluster used for
paper §V-D's RTX 5080 experiments. It owns port 6443 and configures
Multus globally on the host.

### Fix

Use the existing host cluster. Don't install kind/k3s/minikube on the
same host.

```bash
# kubeadm admin kubeconfig (root-owned by default)
sudo install -m 0600 -o "$USER" -g "$USER" \
  /etc/kubernetes/admin.conf /tmp/kubeconfig-host
export KUBECONFIG=/tmp/kubeconfig-host
kubectl get nodes  # expect: <dev-host> Ready, control-plane, v1.35.x
kubectl get deviceclasses  # gpu.nvidia.com, mig.nvidia.com (DRA enabled)
```

The host cluster has Cilium CNI, Multus secondary CNI, hubble UI, and
NVIDIA DRA driver pre-installed.

---

## §C. `install_argo.sh` failure on K8s 1.35: 262144-byte annotation limit

### Symptom

```
CustomResourceDefinition.apiextensions.k8s.io "workflows.argoproj.io"
is invalid: metadata.annotations: Too long: may not be more than 262144
bytes
```

### Root cause

Argo Workflows v4.0.x install.yaml's CRD validation schema exceeds the
client-side `kubectl apply` annotation budget (262144 bytes for the
`kubectl.kubernetes.io/last-applied-configuration` annotation).

### Fix

Use server-side apply. The repo's `scripts/install_argo.sh` was patched
on 2026-05-09 (commit `328046a`). For external usage:

```bash
kubectl apply --server-side -n argo \
  -f https://github.com/argoproj/argo-workflows/releases/download/v4.0.1/install.yaml
```

The sibling `scripts/install_kueue.sh` already uses `--server-side`.

---

## §D. Argo Workflow runs immediately fail: ServiceAccount not found

### Symptom

```
pods "...-step-0-preprocess-..." is forbidden: error looking up service
account orbital-demo/orbital-workflow-runner: serviceaccount
"orbital-workflow-runner" not found
```

### Root cause

`manifests/k8s/argo/00-workflow-executor-rbac.yaml` requires the
`orbital-demo` namespace to exist. If applied before
`manifests/k8s/kueue/00-namespace.yaml`, it errors with `namespaces
"orbital-demo" not found`.

### Fix

Apply queue manifests **first** (they create the namespace), then apply
the RBAC manifest:

```bash
kubectl apply -f manifests/k8s/kueue/      # creates orbital-demo + queues
kubectl apply -f manifests/k8s/argo/00-workflow-executor-rbac.yaml
```

Or run the full validation script which handles ordering:

```bash
KUBECONFIG=/tmp/kubeconfig-host bash scripts/validate_live_cluster.sh
```

---

## §E. Tailscale considerations (not actually a problem, FYI)

If the host runs Tailscale, two prefs may show up in pod environments
without causing the §A symptom:

- `CorpDNS: true` injects `tail*.ts.net` search domain into pod
  `/etc/resolv.conf`. Harmless; does not cause TLS failures.
- `NetfilterMode: 2` adds Tailscale-managed iptables chains
  (`ts-input`, `ts-forward`). Does not interfere with kubeadm cluster
  pod-to-API-server traffic.

If you need to debug whether Tailscale is interfering with anything:

```bash
sudo tailscale set --accept-dns=false   # disable DNS injection only
# verify behavior; revert with:
sudo tailscale set --accept-dns=true
```

**Operator caution**: if you reach the dev host **through** Tailscale
(SSH over the tailnet), running `sudo tailscale down` or
`systemctl stop tailscaled` cuts your own session and may require
physical/console access to recover. Prefer the per-pref toggles above
for any diagnostic that touches Tailscale.

---

## §F. Verified live reproduction outcome (2026-08-02)

`scripts/validate_live_cluster.sh` against the host kubeadm cluster:

```
PASS: 12  FAIL: 0
RESULT: PASS
```

Specifically:
- kubectl + argo CLI available
- Argo workflow-controller running
- Kueue controller-manager running
- Mission plan compiled (Pydantic schema)
- Argo Workflow rendered and lint passed
- Argo Workflow submitted, ran, **Succeeded**
- Kueue Job rendered, submitted, **admitted**, **completed**

The count was 13 when this section was first written on 2026-05-09. Rendering and
linting are one step now that the render command carries the gate, so they report
once instead of twice; nothing was dropped. A fourteenth check exists for applying
a `ResourceClaimTemplate` and does not fire here, because the plan this script uses
renders a Job and nothing else.

This independently validates paper §V-D claim "Rendered Argo Workflow
YAML is validated by argo lint" and "live cluster validation."
