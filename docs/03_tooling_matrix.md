# 03_tooling_matrix

## A. Workflow / control candidates

| Candidate | Official source | Latest stable version (verified) | Install style | Project fit | Why not selected / where used |
|---|---|---|---|---|---|
| Argo Workflows | https://argo-workflows.readthedocs.io/ ; https://github.com/argoproj/argo-workflows/releases | 4.0.1 | Kubernetes manifest | **Strong**: transcript-aligned mission workflow backend | **Selected** |
| Kueue | https://kueue.sigs.k8s.io/ ; https://github.com/kubernetes-sigs/kueue/releases | 0.17.0 | Kubernetes manifest | **Strong** for admission / quota / preemption gap | **Selected** |
| Temporal | https://docs.temporal.io/ ; https://github.com/temporalio/temporal/releases | 1.30.3 | self-hosted binary / helm / cloud | Great reliability semantics, but heavier than transcript-aligned K8s path | not selected |
| Flyte | https://docs-legacy.flyte.org/ ; https://github.com/flyteorg/flyte/releases | 1.16.5 | Helm / K8s deployment | Rich ML/data workflows, but operationally heavier | not selected |
| Dagster | https://docs.dagster.io/ ; https://github.com/dagster-io/dagster/releases | 1.12.21 | pip / k8s / hybrid | Good developer UX, weaker fit for mission-plan→Argo path | not selected |

## B. Cluster substrate candidates

| Candidate | Official source | Latest stable version (verified) | Install style | Project fit | Why not selected / where used |
|---|---|---|---|---|---|
| K3s | https://docs.k3s.io/ ; https://github.com/k3s-io/k3s/releases | 1.35.3+k3s1 latest visible; baseline pin here: **1.34.5+k3s1** | install script | Edge-friendly, transcript-aligned, low overhead | **Selected** |
| k0s | https://docs.k0sproject.io/ ; https://github.com/k0sproject/k0s/releases | 1.35.2+k0s.0 | binary / k0sctl | compelling minimal distro, but less transcript-aligned than K3s | not selected |
| MicroK8s | https://microk8s.io/docs ; https://snapcraft.io/microk8s | 1.35/stable channel | snap | simple for Ubuntu, but snap dependency is less desirable for portable scripting | not selected |
| Talos Linux | https://www.talos.dev/ ; https://github.com/siderolabs/talos/releases | 1.12.6 | dedicated OS | strong immutable ops story, but too opinionated for this scaffold | not selected |
| Nomad | https://developer.hashicorp.com/nomad ; https://github.com/hashicorp/nomad/releases | 1.11.3 | binary | interesting edge scheduler, but diverges from transcript K8s path | not selected |

## C. Policy candidates

| Candidate | Official source | Latest stable version (verified) | Install style | Project fit | Why not selected / where used |
|---|---|---|---|---|---|
| OPA | https://www.openpolicyagent.org/docs/ ; https://github.com/open-policy-agent/opa/releases | 1.15.1 | binary / container | works both in CI and cluster; ideal for pre-K8s mission-plan validation | **Selected** |
| Gatekeeper | https://open-policy-agent.github.io/gatekeeper/ ; https://github.com/open-policy-agent/gatekeeper/releases | 3.22.0 | k8s manifests / helm | good admission control, but cluster-centric | not selected |
| Kyverno | https://kyverno.io/ ; https://github.com/kyverno/kyverno/releases | 1.17.x stream | k8s manifests / helm | excellent YAML-native policy UX, but less suitable for standalone compiler validation | not selected |

## D. Python / agent-facing candidates

| Candidate | Official source | Latest stable version (verified) | Install style | Project fit | Why not selected / where used |
|---|---|---|---|---|---|
| Pydantic | https://docs.pydantic.dev/ ; https://github.com/pydantic/pydantic/releases | 2.12.5 | pip | schema-first mission plan validation | **Selected** |
| Hera Workflows | https://hera.readthedocs.io/ ; https://pypi.org/project/hera-workflows/ | 6.0.0 | pip | Argo-endorsed Python-side workflow generation path | **Removed from default deps** — re-add when Hera-based rendering is implemented |
| FastMCP | https://gofastmcp.com/ ; https://github.com/jlowin/fastmcp | 3.2.0 | pip | agent / MCP bridge for long-running dev workflows | **Selected (optional)** |
| FastAPI | https://fastapi.tiangolo.com/ ; https://github.com/fastapi/fastapi/releases | 0.135.3 | pip | good for service API, but MCP + CLI are higher priority for MVP | not selected |
| Ray | https://docs.ray.io/ ; https://github.com/ray-project/ray/releases | 2.54.1 | pip / cluster | useful for distributed AI compute, but outside MVP scope | not selected |

## Selection summary
Final scaffold selection (ORCHIDE-aligned where applicable):
- K3s (ORCHIDE-aligned: slide 15, 19)
- Argo Workflows (ORCHIDE-aligned: slide 15, 23)
- Kueue (ground-side addition — not in ORCHIDE)
- OPA (ground-side addition — not in ORCHIDE)
- Pydantic
- FastMCP (optional)
- OpenTelemetry Collector (design target; ORCHIDE uses Vector instead)
