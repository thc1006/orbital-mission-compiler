# 15 — Threat Model and CCSDS Terminology Alignment

> Security threat analysis for the ground-side mission plan compiler.
> Addresses IEEE SMC-IT/SCC 2026 reviewer feedback: add threat model section.
>
> **Methodology**: STRIDE threat classification with trust boundary analysis.
> **Standards**: ECSS-Q-ST-80C (Software Product Assurance), CCSDS 350.1-G-3 (Security Threats Against Space Missions), NIST SP 800-53 (Security Controls).

---

## 1. Trust Boundaries

The compiler operates across four trust boundaries:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Ground Environment                          │
│                                                                    │
│  ┌──────────┐    TB1     ┌──────────────┐   TB2   ┌────────────┐  │
│  │ User     │──────────▶ │  Compiler    │────────▶│ Rendered   │  │
│  │ YAML     │            │  (Pydantic   │         │ Artifacts  │  │
│  │ Input    │            │   + OPA)     │         │ (Argo/     │  │
│  └──────────┘            └──────┬───────┘         │  Kueue)    │  │
│                                 │                 └─────┬──────┘  │
│  ┌──────────┐    TB4     ┌──────┴───────┐               │ TB3    │
│  │ AI Agent │──────────▶ │  MCP Server  │               ▼        │
│  │ (Client) │            │  (6 tools)   │         ┌────────────┐  │
│  └──────────┘            └──────────────┘         │ Deployment │  │
│                                                   │ Interface  │  │
│                                                   │ (ORCHIDE)  │  │
│                                                   └────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

| Boundary | From | To | Data Flow |
|---|---|---|---|
| **TB1** | User YAML input | Compiler (schema + policy) | Untrusted YAML → validated MissionPlan |
| **TB2** | Compiler output | Rendered artifacts | WorkflowIntent → Argo/Kueue YAML |
| **TB3** | Rendered artifacts | ORCHIDE deployment interface | YAML files → satellite uplink |
| **TB4** | AI agent (MCP client) | MCP server (6 tools) | Tool invocations via stdio transport |

---

## 2. STRIDE Threat Analysis

| ID | STRIDE Category | Threat | Attack Vector | Existing Mitigation | Residual Risk |
|---|---|---|---|---|---|
| T1 | **Tampering** | YAML deserialization attack (billion laughs / alias bomb) | Crafted YAML with recursive anchors or entity expansion | `yaml.safe_load` used consistently (CWE-502); Pydantic typed validation post-parse | No explicit document size limit; `safe_load` prevents code execution but large documents may exhaust memory |
| T2 | **Tampering** | OPA policy bypass via crafted input | Input fields engineered to satisfy policy rules while violating semantic intent | Schema + Policy dual-layer validation (12 error categories in ablation study); defense-in-depth on 5 overlapping rules | Novel field combinations outside tested corpus may bypass rules; policy coverage depends on rule completeness |
| T3 | **Tampering** | MCP path traversal | `../../etc/passwd` in plan path argument to MCP tools | CWE-22: multi-layer validation — rejects absolute paths, `..` components, directory components; symlink-safe `resolve()` + `relative_to()` boundary check | Plan paths restricted to `configs/mission_plans/`; bundle paths restricted to `configs/policies/` via repo-root-relative resolution |
| T4 | **Denial of Service** | OPA subprocess hang or resource exhaustion | Pathological Rego evaluation or extremely large input payload | CWE-400: 30-second timeout (`OPA_TIMEOUT_SECONDS`); subprocess killed on expiry | No memory limit on OPA process; no rate limiting on MCP tool invocations |
| T5 | **Information Disclosure** | OPA stderr leaks internal filesystem paths | OPA debug/warning messages exposing server directory structure | CWE-209: stdout prioritized over stderr; stderr returned only as fallback when stdout is empty | Partial leak path remains when OPA produces no stdout (edge case) |
| T6 | **Spoofing** | Rendered artifact substitution between compiler and deployment | Man-in-the-middle replaces output YAML before satellite uplink | None — out of compiler scope | **No artifact signing or integrity hash**; output YAML has no provenance chain; deployment interface (TB3) must verify independently |
| T7 | **Repudiation** | Untraceable compilation decisions | Operator disputes which plan/policy version produced specific artifacts | Python `logging` module; `orbital/*` annotations in rendered YAML carry mission-id, service-id, priority | **No immutable audit trail**; no compilation receipt linking input hash → output hash → policy version |
| T8 | **Elevation of Privilege** | MCP tool used to compile arbitrary plans | AI agent invokes tools with manipulated path arguments | CWE-22 path validation restricts to `configs/mission_plans/` directory | MCP stdio transport has no authentication; any connected client has full tool access; authorization depends on transport layer |
| T9 | **Tampering** | OPA binary supply chain compromise | Attacker replaces `opa` binary on system PATH | `shutil.which("opa")` locates binary; CI pins OPA version (v1.15.1) with HTTPS download | **No runtime checksum verification** of OPA binary; local development relies on system PATH trust |
| T10 | **Tampering** | Kubernetes YAML injection via unsanitized fields | Malicious values in mission plan string fields pass through to Argo/Kueue annotations | `sanitize_k8s_name()` applies RFC 1123 sanitization to names and labels | Annotation values and container args are not fully sanitized; K8s API server provides final validation layer |

---

## 3. Existing CWE Mitigations

The compiler implements hardening for the following CWEs. Test coverage is summarized below, and selected security hardening changes are documented in CHANGELOG v0.2.0:

| CWE | Name | Mitigation | Location | Tests |
|---|---|---|---|---|
| CWE-22 | Path Traversal | Multi-layer validation: no `..`, no absolute, bare filenames, symlink-safe resolve | `mcp/server.py:33-59` | `test_mcp_security.py` (6 tests) |
| CWE-209 | Error Message Info Disclosure | stdout prioritized over stderr for OPA output | `policy.py:39-42` | `test_policy_security.py` (1 test) |
| CWE-250 | Unnecessary Privileges | Non-root `USER appuser` in Dockerfile | `Dockerfile:19` | CI runs as non-root |
| CWE-377 | Insecure Temporary File | `mktemp` + `trap` cleanup; Python `tempfile.TemporaryDirectory` | `opa_smoke.sh:12-13`, `server.py` | Scripts + context managers |
| CWE-400 | Uncontrolled Resource Consumption | 30-second OPA subprocess timeout | `policy.py:14,35` | `test_policy_security.py` (2 tests) |
| CWE-502 | Deserialization of Untrusted Data | `yaml.safe_load` used consistently; Pydantic typed validation | `compiler.py:45` | Schema + negative tests |

---

## 4. Residual Risk Assessment

### High residual risks (require future mitigation)

| Risk | Impact | Recommended Mitigation |
|---|---|---|
| **T6: No artifact signing** | Rendered YAML can be tampered before deployment | Add SHA-256 digest in compilation receipt; sign with ed25519 key |
| **T7: No audit trail** | Cannot prove which input + policy produced specific output | Emit structured compilation receipt (input_hash, policy_hash, output_hash, timestamp) |
| **T9: No OPA checksum** | Compromised OPA binary would silently pass all policies | Pin OPA binary hash in CI; verify at runtime via `hashlib` check |

### Accepted risks (mitigated by external systems)

| Risk | Rationale |
|---|---|
| **T3: Bundle path breadth** | Repo root boundary is acceptable; Kubernetes RBAC provides additional access control |
| **T8: MCP no auth** | MCP stdio transport is local-only; authentication is a transport-layer concern per MCP spec |
| **T10: Annotation injection** | K8s API server validates all resources before admission; compiler is not the final trust boundary |

---

## 5. CCSDS Terminology Alignment

This compiler's functions map to CCSDS 522.0-B (Mission Planning and Scheduling) terminology. The alignment strengthens interoperability claims with European space mission operations.

| This Compiler | CCSDS 522.0-B Term | Description |
|---|---|---|
| Mission plan (YAML input) | **Planning Request / Activity Plan** | Structured request for satellite activities |
| Event (acquisition / download) | **Activity** | Schedulable unit of work with type classification |
| Service (AI workflow) | **Procedure / Activity Group** | Sequence of processing steps for an activity |
| Priority (0-100, `scale_priority_orchide`) | **Activity Priority** | Scheduling priority; mapped to ORCHIDE 1-4 scale |
| Policy guardrail (OPA/Rego) | **Planning Constraint** | Rule restricting valid plan configurations |
| `compile_plan_to_intents()` | **Plan Elaboration** | Expanding abstract requests into executable workflows |
| `render_kueue_job()` | **Resource Allocation** | Assigning compute resources to elaborated activities |
| `detect_timeline_conflicts()` | **Conflict Resolution** | Identifying overlapping activity windows |
| Compiled Argo Workflow YAML | **Activity Plan** (serialized) | Executable output ready for deployment |
| `execution_mode` (sequential / parallel) | **Execution Directive** | Activity ordering constraint |

### Standards References

- **CCSDS 522.0-B**: Mission Planning and Scheduling — plan elaboration, activity plans, scheduling constraints
- **CCSDS 350.1-G-3**: Security Threats Against Space Missions — identifies ground segment as primary attack surface; recommends input validation, command authentication, and audit trails
- **ECSS-Q-ST-80C Rev.1**: Software Product Assurance — requires threat analysis as part of software safety/dependability analysis (Section 5.3)
- **ECSS-E-ST-40C Rev.1**: Software Engineering — bidirectional traceability requirements (see `docs/14_traceability_matrix.md`)
- **NIST SP 800-53**: Security controls SA-11 (Developer Testing), SI-10 (Input Validation), AU-2 (Audit Events), SC-28 (Information at Rest)

---

## 6. Relationship to ORCHIDE Security

ORCHIDE D3.1 §3.2.1.4 defines a Security Manager responsible for encryption and authentication on the satellite. This compiler operates **before** the ORCHIDE deployment interface (TB3) and does not implement:

- Encryption of rendered artifacts (ORCHIDE Security Manager responsibility)
- Authentication of the deployment uplink (transport-layer concern)
- On-satellite integrity verification (ORCHIDE scope)

The compiler's security scope is limited to **input validation, policy enforcement, and safe rendering** within the ground environment. Security at TB3 (deployment) and beyond is delegated to ORCHIDE's Security Manager.
