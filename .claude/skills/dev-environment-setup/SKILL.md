---
name: dev-environment-setup
description: Set up and run the satellite-mission-compiler dev environment against the host kubeadm cluster — kubeconfig, the .venv-verify Python venv, argo/opa CLI install, the canonical pytest / live-cluster-validation / ablation / benchmark commands, the one-time Argo+Kueue cluster bootstrap, and the multus "crypto/rsa verification error" CrashLoop fix. Use when setting up the environment, running tests or live-cluster validation, bootstrapping Argo/Kueue, or debugging pod CrashLoops.
---

# Dev environment setup and canonical commands

This repo is developed against a host-resident kubeadm K8s cluster (NOT
kind/minikube/k3s). The cluster runs as a systemd kubelet on the dev box
(`<dev-host>`) and was set up with Cilium CNI, Multus secondary CNI, NVIDIA DRA
driver, and DRA-aware feature gates. Reproduction recipe and known issues are
documented in `docs/local-dev-troubleshooting.md`.

## Standard environment setup

```bash
# 1. kubeconfig — root-owned by default; copy to a user-private path.
#    Note: /tmp is wiped on reboot. For a persistent path use
#    ~/.kube/satellite-mission-compiler-config and update KUBECONFIG accordingly.
sudo install -m 0600 -o "$USER" -g "$USER" \
  /etc/kubernetes/admin.conf /tmp/kubeconfig-host
export KUBECONFIG=/tmp/kubeconfig-host
kubectl get nodes  # expect: <dev-host> Ready, control-plane, v1.35.x

# 2. Python venv (project deps + dev tools + MCP)
#    uv path (faster, optional — see docs/07_installation_matrix.md):
uv venv .venv-verify --python 3.12
uv pip install --python .venv-verify/bin/python -e '.[dev,mcp]'
#    Or pure stdlib + pip equivalent:
#    python3 -m venv .venv-verify
#    .venv-verify/bin/python -m pip install -e '.[dev,mcp]'

# 3. CLI tools (one-time, place in venv bin)
curl -sSL -o .venv-verify/bin/argo.gz \
  https://github.com/argoproj/argo-workflows/releases/download/v4.0.1/argo-linux-amd64.gz
gunzip -f .venv-verify/bin/argo.gz && chmod +x .venv-verify/bin/argo
curl -sSL -o .venv-verify/bin/opa \
  https://github.com/open-policy-agent/opa/releases/download/v1.15.1/opa_linux_amd64_static
chmod +x .venv-verify/bin/opa
```

## Canonical commands

```bash
# Run pytest (expect: ~424 passed, ~51 skipped on fresh env;
# 475 passed, 0 skipped with full local tooling (opa on PATH + live cluster))
.venv-verify/bin/python -m pytest -q

# Live cluster validation against host kubeadm cluster (expect 12/12 PASS)
PATH="$PWD/.venv-verify/bin:$PATH" \
PYTHON_BIN=$PWD/.venv-verify/bin/python \
KUBECONFIG=/tmp/kubeconfig-host \
bash scripts/validate_live_cluster.sh

# Defense-in-depth ablation (requires opa on PATH; produces Patch A data)
PATH="$PWD/.venv-verify/bin:$PATH" \
.venv-verify/bin/python scripts/ablation_study.py

# Phase-wise scaling benchmark (Table IV in paper)
.venv-verify/bin/python scripts/benchmark_scaling.py \
  --sizes 10,100,1000 --iterations 10
```

## One-time host cluster bootstrap (Argo + Kueue + queues)

```bash
# Install Argo Workflows v4.0.1 (note: --server-side mandatory on K8s 1.35+)
kubectl create namespace argo
kubectl apply --server-side -n argo \
  -f https://github.com/argoproj/argo-workflows/releases/download/v4.0.1/install.yaml

# Install Kueue v0.17.0
bash scripts/install_kueue.sh

# Apply queue manifests FIRST (creates orbital-demo namespace), then RBAC
kubectl apply -f manifests/k8s/kueue/
kubectl apply -f manifests/k8s/argo/00-workflow-executor-rbac.yaml
```

## When pods CrashLoop with `crypto/rsa: verification error`

Don't trust the error message — the cause is upstream. See
`docs/local-dev-troubleshooting.md` §A. The fix is usually:

```bash
sudo mkdir -p /var/lib/cni/multus
sudo chmod 755 /var/lib/cni/multus
KUBECONFIG=/tmp/kubeconfig-host kubectl delete pod -n kube-system -l app=multus
```
