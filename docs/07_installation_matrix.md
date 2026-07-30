# 07_installation_matrix

## Verified external dependencies included in the scaffold

| Dependency | Package / project name | Official source | Version used in scaffold | Install command / method | Platform limits | Conflict notes |
|---|---|---|---|---|---|---|
| K3s | `k3s` | https://docs.k3s.io/quick-start ; https://github.com/k3s-io/k3s/releases | pin: **v1.34.5+k3s1** | `curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.34.5+k3s1 sh -` | Linux only; root required | Verify cgroup/kernel setup on Ubuntu 22/24 before production use |
| Argo Workflows | `argo-workflows` | https://argo-workflows.readthedocs.io/en/latest/installation/ ; https://github.com/argoproj/argo-workflows/releases | **v4.0.1** | `kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v4.0.1/install.yaml` | Kubernetes required | Check Kubernetes compatibility against chosen K3s minor before production use |
| Argo CLI | `argo` | https://argo-workflows.readthedocs.io/en/latest/cli/argo_lint/ ; https://github.com/argoproj/argo-workflows/releases | **v4.0.1** | download `argo-linux-amd64.gz` from release assets and move to PATH | Linux/macOS | optional for local lint, not required for compiler |
| Kueue | `kueue` | https://kueue.sigs.k8s.io/docs/installation/ ; https://github.com/kubernetes-sigs/kueue/releases | **v0.17.0** | `kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.17.0/manifests.yaml` | Kubernetes required | Kueue queueing is provided as demo manifests; Argo↔Kueue integration remains project glue |
| OPA | `opa` / `openpolicyagent/opa` | https://openpolicyagent.org/docs ; https://github.com/open-policy-agent/opa/releases | **1.15.1** | binary or container; CLI example uses `opa eval --stdin-input --data ...` | none for local CI; cluster optional | CI verifies downloaded binary integrity via official `.sha256` sidecar file |
| PyYAML | `PyYAML` | https://pypi.org/project/PyYAML/6.0.2/ | **6.0.2** | `pip install PyYAML==6.0.2` | Python >=3.8 typical | none known here |
| Pydantic | `pydantic` | https://docs.pydantic.dev/latest/ ; https://github.com/pydantic/pydantic/releases | **2.12.5** | `pip install pydantic==2.12.5` | Python >=3.10 (project pin) | check downstream libs expecting pydantic v1 |
| Hera | `hera-workflows` | https://pypi.org/project/hera-workflows/ | **6.0.0** | `pip install hera-workflows==6.0.0` | Python only | **Removed from default deps** — was unused; re-add when Hera-based rendering is implemented |
| Ruff | `ruff` | https://docs.astral.sh/ruff/ ; https://github.com/astral-sh/ruff/releases | **0.15.8** | `pip install ruff==0.15.8` | Python toolchain | none known here |
| pytest | `pytest` | https://docs.pytest.org/en/stable/announce/release-9.0.2.html | **9.0.2** | `pip install pytest==9.0.2` | Python toolchain | plugin compatibility may vary |
| uv (optional) | `uv` | https://docs.astral.sh/uv/ ; https://github.com/astral-sh/uv/releases | latest stable | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | Linux/macOS/Windows | Fast venv + installer; substitutable with stdlib `python3 -m venv` + `pip install` |
| FastMCP (optional) | `fastmcp` | https://gofastmcp.com/getting-started/installation | **3.2.0** | `pip install fastmcp==3.2.0` | Python only | optional extra; not required for core compiler |
| mypy | `mypy` | https://mypy.readthedocs.io/ ; https://github.com/python/mypy/releases | **1.16.0** | `pip install mypy==1.16.0` | Python toolchain | static type checker; dev dependency only |
| types-PyYAML | `types-PyYAML` | https://pypi.org/project/types-PyYAML/ | **6.0.12.20250915** | `pip install types-PyYAML==6.0.12.20250915` | Python toolchain | type stubs for PyYAML; dev dependency only |
| OTel Collector (optional) | `opentelemetry-collector` | https://opentelemetry.io/docs/collector/install/kubernetes/ ; https://github.com/open-telemetry/opentelemetry-collector/releases | **v0.149.0** | `kubectl apply -f https://raw.githubusercontent.com/open-telemetry/opentelemetry-collector/v0.149.0/examples/k8s/otel-config.yaml` | Kubernetes required | optional, not validated end-to-end here |

## Dependencies discussed but not included in default scaffold
| Dependency | Reason not in default scaffold |
|---|---|
| OpenTelemetry Operator 0.148.0 | requires extra Kubernetes components such as cert-manager; documented as optional extension |
| FastAPI | useful for HTTP API, but CLI + MCP are enough for MVP |
| Ray | useful for distributed AI compute, but too large a dependency jump for compiler-first MVP |
| KServe | strong inference serving option, but this repo is not an inference-serving platform |
| Temporal / Flyte / Dagster | heavier or less transcript-aligned than the selected K3s + Argo path |

## Upstream currency and forward compatibility (checked 2026-07-30)

The "Version used in scaffold" column above is the **validated** record — the
versions this repo was actually exercised against (host kubeadm cluster K8s
**v1.36.1**; Kueue **v0.18.3**; Argo Workflows **v4.0.1**). It is intentionally
*not* bumped to the newest upstream tag, because doing so would claim a
validation that has not been run. This section instead tracks the **current
upstream** and the repo's **forward compatibility**, so the two concerns stay
separate and honest.

| Concern | Validated against (scaffold) | Current upstream (2026-07-30) | Notes |
|---|---|---|---|
| Kubernetes | host kubeadm **v1.36.1** / K3s pin v1.34.5+k3s1 | latest stable **v1.36.3** (2026-07-23); supported minors **1.34–1.36**; **no v1.37 GA yet** (GA ~2026-08-26) — a `v1.37.0-beta.0` **pre-release** exists and is installable for early testing only (not for production, feature/API surface may still change) | sources: https://kubernetes.io/releases/ ; https://github.com/kubernetes/kubernetes/releases/tag/v1.37.0-beta.0 |
| Kueue | live cluster **v0.18.3** / scaffold pin v0.17.0 | **v0.19.0** (latest tag) | source: https://github.com/kubernetes-sigs/kueue/releases ; API `kueue.x-k8s.io/v1beta2` is served+storage across v0.17–v0.19 |
| Argo Workflows | **v4.0.1** | v4.0.1 | CRD group `argoproj.io/v1alpha1` unchanged |

### Emitted API versions (still current on the latest stable stack)

The compiler's rendered manifests use only GA / current API versions, so the
output is forward-compatible with the supported Kubernetes minors above without
a code change:

| Manifest | Emitted `apiVersion` | Stability |
|---|---|---|
| Argo Workflow | `argoproj.io/v1alpha1` | current Argo Workflows CRD version (v4.x) |
| DRA ResourceClaimTemplate / ResourceClaim | `resource.k8s.io/v1` | **GA** since Kubernetes v1.34; current through v1.36 |
| Kueue WorkloadPriorityClass | `kueue.x-k8s.io/v1beta2` | served + storage in Kueue v0.17–v0.19 |
| Kueue-managed Job | `batch/v1` | stable |

### Kubernetes v1.37 DRA landscape (forward-compat, not an install target)

v1.37 has no GA yet (only the `v1.37.0-beta.0` pre-release above), so it is
documented here only as a forward-looking compatibility target, verified from
the release's enhancement tracking
(https://github.com/kubernetes/sig-release/tree/master/releases/release-1.37 and
the linked KEPs in kubernetes/enhancements, checked 2026-07-30):

| KEP | Feature | v1.37 stage | Relevance to this repo |
|---|---|---|---|
| 5004 | DRA extended resources | **Stable (GA)** | no change; the compiler does not depend on it |
| 5729 | DRA consumable-capacity / workload claims | **Beta** | no change; not used by the emitted claims |
| 4816 | DRA prioritized list (`firstAvailable`) | **Stable** (as of v1.36) | already used by the opt-in `--dra-fallback` renderer |
| 6080 | DRA derived attributes | **Alpha** (feasibility) | future work; would enrich device selection, no manifest change today |
| 5963 | DRA device compatibility groups | **Alpha** (feasibility) | future work; an additional scheduling predicate, independent of quota math |
| 5517 | DRA node-allocatable | **Alpha** | intentionally **not** adopted — DRA CPU adds to PodSpec but does not drive QoS/cgroup, so the baseline CPU path is kept |

**Kueue DRA quota caveat (unchanged at v0.19.0):** Kueue's DRA quota counting
still supports only `exactly` device requests; `firstAvailable` and `all` remain
unsupported. This is why `--dra-fallback` (a `firstAvailable` claim) is a
**scheduler-level** fallback that is *not* Kueue-quota-counted, while the unified
quota path uses `exactly` claims of each device class. See
`manifests/k8s/kueue/dra-unified/README.md`.

## GPU note
This scaffold does **not** force-install CUDA or PyTorch. GPU support is modeled as a **resource class**, optional scheduling preference, and optional execution path, because:
- the transcript mentions heterogeneous accelerators configurable per application,
- but exact onboard accelerator interfaces are not public here,
- and CUDA / driver / kernel compatibility must be validated per target node.

Use CPU-first development, then layer GPU execution into specific workflow steps after node-level validation.
