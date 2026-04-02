# 11_research_log

This document records the official sources used to pin or compare the toolchain.

## Core selected stack
- K3s docs and releases
- Argo Workflows docs and releases
- Kueue docs and releases
- OPA docs and releases
- Pydantic docs and releases
- Hera docs / PyPI
- FastMCP docs / repository
- Ruff releases
- PyYAML PyPI
- pytest docs / PyPI

## Candidate stack also reviewed
- k0s
- MicroK8s
- Talos
- Nomad
- Temporal
- Flyte
- Dagster
- Gatekeeper
- Kyverno
- Ray
- KServe

Whenever a dependency or version changes, add:
1. official URL,
2. exact version,
3. install command,
4. compatibility note,
5. reason for selection or rejection.


## Phase 2 demo sources
- OPA CLI reference for `opa eval --stdin-input --data ...`: https://openpolicyagent.org/docs/cli
- OPA docs front page examples for command-line evaluation: https://openpolicyagent.org/docs
- Argo installation docs: https://argo-workflows.readthedocs.io/en/latest/installation/
- Argo `argo lint` CLI docs: https://argo-workflows.readthedocs.io/en/latest/cli/argo_lint/
- Kueue install docs: https://kueue.sigs.k8s.io/docs/installation/
- Kueue concepts for `ClusterQueue`, `LocalQueue`, `ResourceFlavor`: https://kueue.sigs.k8s.io/docs/concepts/
- Kueue job submission docs for `kueue.x-k8s.io/queue-name`: https://kueue.sigs.k8s.io/docs/tasks/run/jobs/
- OpenTelemetry Collector Kubernetes install example: https://opentelemetry.io/docs/collector/install/kubernetes/
