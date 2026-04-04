# 07_installation_matrix

## Verified external dependencies included in the scaffold

| Dependency | Package / project name | Official source | Version used in scaffold | Install command / method | Platform limits | Conflict notes |
|---|---|---|---|---|---|---|
| K3s | `k3s` | https://docs.k3s.io/quick-start ; https://github.com/k3s-io/k3s/releases | pin: **v1.34.5+k3s1** | `curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.34.5+k3s1 sh -` | Linux only; root required | Verify cgroup/kernel setup on Ubuntu 22/24 before production use |
| Argo Workflows | `argo-workflows` | https://argo-workflows.readthedocs.io/en/latest/installation/ ; https://github.com/argoproj/argo-workflows/releases | **v4.0.1** | `kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v4.0.1/install.yaml` | Kubernetes required | Check Kubernetes compatibility against chosen K3s minor before production use |
| Argo CLI | `argo` | https://argo-workflows.readthedocs.io/en/latest/cli/argo_lint/ ; https://github.com/argoproj/argo-workflows/releases | **v4.0.1** | download `argo-linux-amd64.gz` from release assets and move to PATH | Linux/macOS | optional for local lint, not required for compiler |
| Kueue | `kueue` | https://kueue.sigs.k8s.io/docs/installation/ ; https://github.com/kubernetes-sigs/kueue/releases | **v0.17.0** | `kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.17.0/manifests.yaml` | Kubernetes required | Kueue queueing is provided as demo manifests; Argo↔Kueue integration remains project glue |
| OPA | `opa` / `openpolicyagent/opa` | https://openpolicyagent.org/docs ; https://github.com/open-policy-agent/opa/releases | **1.15.1** | binary or container; CLI example uses `opa eval --stdin-input --data ...` | none for local CI; cluster optional | No GPU constraints |
| PyYAML | `PyYAML` | https://pypi.org/project/PyYAML/6.0.2/ | **6.0.2** | `pip install PyYAML==6.0.2` | Python >=3.8 typical | none known here |
| Pydantic | `pydantic` | https://docs.pydantic.dev/latest/ ; https://github.com/pydantic/pydantic/releases | **2.12.5** | `pip install pydantic==2.12.5` | Python >=3.10 (project pin) | check downstream libs expecting pydantic v1 |
| Hera | `hera-workflows` | https://pypi.org/project/hera-workflows/ | **6.0.0** | `pip install hera-workflows==6.0.0` | Python only | **Removed from default deps** — was unused; re-add when Hera-based rendering is implemented |
| Ruff | `ruff` | https://docs.astral.sh/ruff/ ; https://github.com/astral-sh/ruff/releases | **0.15.8** | `pip install ruff==0.15.8` | Python toolchain | none known here |
| pytest | `pytest` | https://docs.pytest.org/en/stable/announce/release-9.0.2.html | **9.0.2** | `pip install pytest==9.0.2` | Python toolchain | plugin compatibility may vary |
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

## GPU note
This scaffold does **not** force-install CUDA or PyTorch. GPU support is modeled as a **resource class**, optional scheduling preference, and optional execution path, because:
- the transcript mentions heterogeneous accelerators configurable per application,
- but exact onboard accelerator interfaces are not public here,
- and CUDA / driver / kernel compatibility must be validated per target node.

Use CPU-first development, then layer GPU execution into specific workflow steps after node-level validation.
