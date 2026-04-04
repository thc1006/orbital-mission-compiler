# 16 — Expanded Comparison Table

> 5 systems × 13 dimensions comparison of this compiler against related systems.
> Addresses IEEE SMC-IT/SCC 2026 reviewer feedback: expand Table I with
> problem layer, artifact granularity, and scheduling scope dimensions.

---

## 1. Systems Compared

| System | Role | Source |
|---|---|---|
| **This compiler** | Ground-side mission plan compiler | This repo |
| **ORCHIDE** | Onboard satellite PaaS (K3s + Argo) | KubeCon EU 2026, D3.1 |
| **EOEPCA+** | ESA EO exploitation platform | eoepca.org (160+ repos) |
| **KubeSpace** | LEO satellite K8s control plane | arXiv:2601.21383, Fudan 2026 |
| **DLR Sentinel+Argo** | Copernicus image processing pipeline | DLR eLib, 2021 |

---

## 2. Multi-Dimensional Comparison

### 2.1 Reviewer-Requested Dimensions

| Dimension | This Compiler | ORCHIDE | EOEPCA+ | KubeSpace | DLR Sentinel+Argo |
|---|---|---|---|---|---|
| **Problem Layer** | Plan validation + compilation (ground) | Workflow execution (onboard) | Data exploitation (ground) | Cluster management (LEO) | Image processing (ground) |
| **Artifact Granularity** | Step-level: individual container specs with phase annotations, resource classes, and fallback | Workflow-level: Argo DAG from priority queue | Service-level: OGC Application Package | Pod-level: scheduling decisions | Workflow-level: CWL → Argo |
| **Scheduling Scope** | Single-workflow admission via Kueue (queue-name, priority, DRA) | Multi-workflow preemption via custom priority queue | No scheduling (user-submitted jobs) | Constellation-wide pod placement across LEO nodes | Single-workflow submission |

### 2.2 Validation & Policy

| Dimension | This Compiler | ORCHIDE | EOEPCA+ | KubeSpace | DLR Sentinel+Argo |
|---|---|---|---|---|---|
| **Validation Approach** | Schema (Pydantic) + Policy-as-code (OPA/Rego), 12 invalid error categories | None documented | OGC schema validation | None (cluster-level only) | None (assumes valid CWL) |
| **Policy Framework** | OPA/Rego: 10 deny rules, ORCHIDE slide-traceable | None | None | None | None |
| **Defense-in-Depth** | 5 rules overlap between schema + policy layers | N/A | N/A | N/A | N/A |

### 2.3 Hardware & Extensibility

| Dimension | This Compiler | ORCHIDE | EOEPCA+ | KubeSpace | DLR Sentinel+Argo |
|---|---|---|---|---|---|
| **Hardware Abstraction** | ResourceClass enum (CPU/GPU/FPGA) + DRA ResourceClaimTemplate + legacy extended resources | Hardware-specific: Jetson, Versal, LX2160, Kalray via ukAccel | Cloud VMs (no accelerator abstraction) | Standard K8s nodes | Cloud VMs |
| **Extensibility Model** | Library + CLI + MCP tools; pip-installable | Embedded glue code in Mission Manager | 160+ microservice repos | Custom kube-apiserver patches | Argo + CWL runner |
| **AI Agent Interface** | MCP server (6 tools: validate_plan, compile_plan, render_argo, explain_policy, diff_plans, check_timeline_conflicts) | None | None | None | None |

### 2.4 Operational Scope

| Dimension | This Compiler | ORCHIDE | EOEPCA+ | KubeSpace | DLR Sentinel+Argo |
|---|---|---|---|---|---|
| **Execution Environment** | Ground-side development/CI | Onboard satellite (ARM64) | Ground cloud (x86/ARM) | LEO satellite constellation | Ground cloud (x86) |
| **ORCHIDE Relationship** | Ground-side complement (pre-deployment) | Self-contained platform | Independent | Independent | Independent |
| **CCSDS Alignment** | Plan Elaboration (522.0-B terminology mapped) | Not documented | Partial (OGC standards) | None | None |
| **Open Source** | Yes (EUPL-1.2) | Announced, pending (ends 2026/05) | Yes (Apache-2.0) | Yes | Yes |

---

## 3. Key Differentiators Summary

This compiler occupies a unique niche as the only system that combines:

1. **Schema + Policy dual-layer validation** — no other compared system has policy-as-code for mission plans
2. **Step-level artifact granularity** — phase annotations, resource class, fallback per container (vs workflow-level in others)
3. **Kueue admission with DRA** — Kubernetes-native queue-based scheduling with `resource.k8s.io/v1` `ResourceClaimTemplate` objects
4. **MCP agent interface** — the only space-related system exposing compilation tools to AI agents
5. **CCSDS 522.0-B alignment** — Plan Elaboration terminology mapped; no other system documents this

---

## 4. Limitations (Honest Assessment)

| Limitation | This Compiler | Systems That Do Better |
|---|---|---|
| No onboard execution | Ground-only; depends on ORCHIDE for satellite runtime | ORCHIDE (full onboard PaaS) |
| Single-satellite scope | No constellation-level scheduling | KubeSpace (LEO constellation) |
| No data exploitation | Produces workflow YAML, not data products | EOEPCA+ (full EO pipeline) |
| Research prototype | TRL ~3 (lab validation) | ORCHIDE (TRL6), EOEPCA+ (production) |
