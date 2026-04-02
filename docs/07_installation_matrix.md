# 07_installation_matrix

## Verified external dependencies included in the scaffold

| Dependency | Package / project name | Official source | Version used in scaffold | Install command / method | Platform limits | Conflict notes |
|---|---|---|---|---|---|---|
| K3s | `k3s` | https://docs.k3s.io/installation/configuration ; https://github.com/k3s-io/k3s/releases | pin: **v1.34.5+k3s1** | `curl -sfL https://get.k3s.io | INSTALL_K3S_VERSION=v1.34.5+k3s1 sh -` | Linux only; root required | Verify cluster add-ons and cgroup config on Ubuntu 22/24 |
| Argo Workflows | `argo-workflows` | https://argo-workflows.readthedocs.io/ ; release manifests | **v4.0.1** | `kubectl apply -n argo -f https://github.com/argoproj/argo-workflows/releases/download/v4.0.1/install.yaml` | Kubernetes required | Check Kubernetes compatibility against chosen K3s minor before production use |
| Kueue | `kueue` | https://kueue.sigs.k8s.io/ ; release manifests | **v0.17.0** | `kubectl apply --server-side -f https://github.com/kubernetes-sigs/kueue/releases/download/v0.17.0/manifests.yaml` | Kubernetes required | Argo ↔ Kueue integration semantics still need project-side glue |
| OPA | `opa` / `openpolicyagent/opa` | https://www.openpolicyagent.org/docs/latest/ ; https://github.com/open-policy-agent/opa/releases | **1.15.1** | binary or container; docker-compose uses `openpolicyagent/opa:1.15.1-static` | none for local CI; cluster optional | No GPU constraints |
| PyYAML | `PyYAML` | https://pypi.org/project/PyYAML/6.0.2/ | **6.0.2** | `pip install PyYAML==6.0.2` | Python >=3.8 typical | none known here |
| Pydantic | `pydantic` | https://docs.pydantic.dev/ ; https://github.com/pydantic/pydantic/releases | **2.12.5** | `pip install pydantic==2.12.5` | Python >=3.9 | check downstream libs expecting pydantic v1 |
| Hera | `hera-workflows` | https://hera.readthedocs.io/ ; https://pypi.org/project/hera-workflows/ | **6.0.0** | `pip install hera-workflows==6.0.0` | Python only | keep aligned with Argo API expectations |
| Ruff | `ruff` | https://docs.astral.sh/ruff/ ; https://github.com/astral-sh/ruff/releases | **0.15.8** | `pip install ruff==0.15.8` | Python toolchain | none known here |
| pytest | `pytest` | https://docs.pytest.org/ ; https://pypi.org/project/pytest/ | **9.0.2** | `pip install pytest==9.0.2` | Python toolchain | plugin compatibility may vary |
| FastMCP (optional) | `fastmcp` | https://gofastmcp.com/ ; https://github.com/jlowin/fastmcp | **3.2.0** | `pip install fastmcp==3.2.0` | Python only | optional extra; not required for core compiler |

## Dependencies discussed but not included in default scaffold
| Dependency | Reason not in default scaffold |
|---|---|
| OpenTelemetry Operator 0.148.0 | requires extra Kubernetes components such as cert-manager; documented as optional extension |
| FastAPI 0.135.3 | useful for HTTP API, but CLI + MCP are enough for MVP |
| Ray 2.54.1 | useful for distributed AI compute, but too large a dependency jump for compiler-first MVP |
| KServe 0.17.0 | strong inference serving option, but this repo is not an inference-serving platform |
| Temporal 1.30.3 / Flyte 1.16.5 / Dagster 1.12.21 | heavier or less transcript-aligned than the selected K3s + Argo path |

## GPU note
This scaffold does **not** force-install CUDA or PyTorch. GPU support is modeled as a **resource class** and optional execution path, because:
- the transcript mentions heterogeneous accelerators,
- but exact onboard accelerator interfaces are not public here,
- and CUDA / driver / kernel compatibility must be validated per target node.

Use CPU-first development, then layer GPU execution into specific workflow steps after node-level validation.
