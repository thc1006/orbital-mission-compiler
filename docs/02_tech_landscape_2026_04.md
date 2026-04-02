# 02_tech_landscape_2026_04

This document summarizes the 2026-04 official-tool landscape relevant to the scaffold.

## Workflow / orchestration
- **Argo Workflows 4.0.1** — Kubernetes-native workflow engine.
- **Kueue 0.17.0** — quota / admission / preemption layer for batch-style workloads.
- **Temporal 1.30.3** — durable workflow platform, strong reliability semantics, heavier control plane.
- **Flyte 1.16.5** — data / ML workflow platform with stronger ecosystem expectations.
- **Dagster 1.12.21** — strong developer UX, weaker alignment with K8s-native batch admission.

## Cluster substrate
- **K3s 1.34.5+k3s1** (selected baseline pin)
- **k0s 1.35.2+k0s.0**
- **MicroK8s 1.35/stable**
- **Talos Linux 1.12.6**
- **Nomad 1.11.3** (not Kubernetes)

## Policy
- **OPA 1.15.1**
- **Gatekeeper 3.22.0**
- **Kyverno 1.17.x stream** (exact patch not pinned here)

## Observability
- **OpenTelemetry Collector 0.149.0 / contrib 0.149.0**
- **OpenTelemetry Operator 0.148.0** (optional; requires cert-manager)
- **Prometheus Operator / Grafana** remain good deployment targets, but are not required for this scaffold MVP.

## ORCHIDE onboard stack (for reference — not used in this repo)
- **Zot Registry** — OCI image registry
- **EOS** — distributed storage (POSIX FS)
- **Vector (Datadog)** — log/metric aggregation on each node
- **urunc** — unikernel OCI runtime (containerd shim)
- **ukAccel** — in-house accelerator mediation layer (TCP, based on vAccel)
- **QEMU/KVM** — hypervisor for unikernels
- **MirageOS / Unikraft** — unikernel frameworks

## Python / agent tooling
- **uv 0.11.1**
- **Pydantic 2.12.5**
- **FastMCP 3.2.0**
- **FastAPI 0.135.3** (candidate, not selected for MVP)
- **Ruff 0.15.8**
