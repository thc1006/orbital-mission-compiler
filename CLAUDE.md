# CLAUDE.md

Start here:
1. `README.md`
2. `docs/00_transcript_grounding.md`
3. `docs/13_market_positioning.md`
4. `docs/04_architecture.md`
5. `docs/07_installation_matrix.md`

## Mission statement
Build the ground-side ORCHIDE-aligned mission plan compiler: schema validation → policy guardrails → workflow compilation → admission semantics, with interface contracts for simulation, packaging, and platform service integration.

## Repo intent
This repo is a **ground-side mission plan compiler** that complements onboard platforms like ORCHIDE. ORCHIDE's D3.1 states that it only covers the "Deferred Phase" (on-satellite workflow execution) and receives mission plans via a deployment interface — but does not generate, validate, or compile those plans. This repo fills that gap.

Core mainline (implement):
1. mission plan schema (aligned with ORCHIDE slide 9 format),
2. policy guardrails (OPA/Rego — not present in ORCHIDE),
3. custom translation layer: mission plan → workflow intent IR → Argo artifacts,
4. workflow / admission rendering (Argo YAML + Kueue Job YAML).

Extended (define contracts only, not implementations):
- simulation, packaging, platform service contracts (Storage, Monitor, Communication, Security Manager).

Optional (serve the mainline, do not lead it):
- MCP interface, Claude Code hooks/skills/subagents, structured logging.

It intentionally does **not** build:
- a full developer platform or SDK,
- a full simulation framework,
- real EOS / Zot / Vector / OpenSearch / Prometheus integration,
- onboard orchestration,
- radiation hardening, full HA, OTA guarantees, or flight-ready claims.

## Working preferences
- Prefer small, reviewable changes.
- Keep code generation deterministic.
- Prefer explicit schemas and golden tests over vague prompts.
- Use official docs before proposing dependency or CLI changes.
- Keep GPU paths optional with CPU fallback.

## Hard constraints
- Do not edit pinned versions in scripts without updating `docs/07_installation_matrix.md`.
- Do not add dependencies unless the package name and install command are verified from official sources.
- Do not remove transcript-grounding notes.
- Do not write architecture claims that exceed what the transcript and docs support.
- Do not claim to replace ORCHIDE; position as ground-side complement.
- Refer to `docs/13_market_positioning.md` for competitive landscape context.

## Key implementation notes
- Core logic lives in `src/orbital_mission_compiler/`.
- Sample plans live in `configs/mission_plans/`.
- Golden evals live in `evals/golden/`.
- Bootstrap and install flows live in `scripts/`.
- MCP entry point is `src/orbital_mission_compiler/mcp/server.py`.
- Live cluster RBAC for Argo executor is in `manifests/k8s/argo/00-workflow-executor-rbac.yaml`.
- `scripts/validate_live_cluster.sh` submits Argo workflows with dedicated SA (`orbital-workflow-runner`) and resolves Kueue workloads via `kueue.x-k8s.io/job-uid`.

## Preferred workflow
- inspect docs
- inspect schemas
- run tests/evals
- make smallest coherent change
- rerun `make verify`

For live validation changes:
- keep script logic portable (avoid GNU-specific assumptions),
- prefer least-privilege service accounts over namespace `default`,
- treat `make k8s-smoke` as environment-coupled validation, not deterministic CI.

## Local development environment

This repo is developed against a host-resident kubeadm K8s cluster
(NOT kind/minikube/k3s). The cluster runs as a systemd kubelet on the
dev box (`<dev-host>`) and was set up with Cilium CNI, Multus
secondary CNI, NVIDIA DRA driver, and DRA-aware feature gates.
Reproduction recipe and known issues are documented in
`docs/local-dev-troubleshooting.md`.

### Standard environment setup

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

### Canonical commands

```bash
# Run pytest (expect: ~424 passed, ~51 skipped on fresh env;
# 475 passed, 0 skipped with full local tooling (opa on PATH + live cluster))
.venv-verify/bin/python -m pytest -q

# Live cluster validation against host kubeadm cluster (expect 13/13 PASS)
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

### One-time host cluster bootstrap (Argo + Kueue + queues)

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

### When pods CrashLoop with `crypto/rsa: verification error`

Don't trust the error message — the cause is upstream. See
`docs/local-dev-troubleshooting.md` §A. The fix is usually:

```bash
sudo mkdir -p /var/lib/cni/multus
sudo chmod 755 /var/lib/cni/multus
KUBECONFIG=/tmp/kubeconfig-host kubectl delete pod -n kube-system -l app=multus
```

### Operator constraints

- **If the operator is remoting into this box via Tailscale**: never run
  `sudo tailscale down` or `systemctl stop tailscaled` — that severs
  the SSH session and may require physical/console access to recover.
  For DNS-only experiments use `sudo tailscale set --accept-dns=false`
  (revertable with `--accept-dns=true`); for iptables-only experiments
  use `--netfilter-mode=off` (revertable to `=on`). The reason these
  matter on this host: the operator's incoming SSH path **is** the
  Tailscale tunnel, so any change that drops the tunnel drops access.
- Do NOT install kind, k3s, or minikube on this host. Port 6443 is
  already owned by the host kubeadm cluster, and Multus shim is
  configured for the host network namespace; sibling installs cause
  cross-CNI conflicts.

## If asked to extend the system
Prefer one of these directions:
1. richer mission plan schema
2. stronger policy pack
3. Kueue admission integration
4. richer Argo rendering
5. telemetry export
6. MCP tools for plan validation / compilation
