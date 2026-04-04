# 14 — ORCHIDE Schema Traceability Matrix

> Formal bidirectional traceability mapping for the ground-side mission plan compiler.
> Addresses IEEE SMC-IT/SCC 2026 reviewer feedback: R1 Major #6, R2 Major #5, R3 Major #5.
>
> **Format**: Aligned with ISO/IEC/IEEE 29148:2018 RTM and ECSS-E-ST-40C Rev.1 bidirectional traceability requirements.
>
> **Primary sources**:
> - KubeCon EU 2026 slides: "Bringing Cloud-Native PaaS to Space" (36 pages)
> - ORCHIDE D3.1: Overall Solution Architecture and Design (July 2024)
> - ORCHIDE D2.2: State of the Art (May 2024)
> - See `docs/00_transcript_grounding.md` for full source attribution.

---

## 1. Schema Field Traceability

Each field in the Pydantic schema models is mapped to its ORCHIDE source (or marked as **Author-Imposed** when the field is a ground-side addition not present in ORCHIDE documentation).

### 1.1 MissionPlan

| Field | ORCHIDE Source | Slide / D3.1 Ref | Implementation | Test Case | Author-Imposed? |
|---|---|---|---|---|---|
| `mission_id` | Plan identifier deployed by Satellite Owner | D3.1 §3.3.1 (IF SO_MIS_DP) | `src/orbital_mission_compiler/schemas.py:95` | `test_schema.py`, `test_policy.py` | No |
| `client_id` | — | — | `src/orbital_mission_compiler/schemas.py:97` | `test_schema.py` | **Yes** — ground-side attribution for multi-tenant scenarios |
| `events` | Mission plan table rows | Slide 9 (plan table) | `src/orbital_mission_compiler/schemas.py:98` | `test_schema.py`, `test_schema_negative.py` | No |

### 1.2 MissionEvent

| Field | ORCHIDE Source | Slide / D3.1 Ref | Implementation | Test Case | Author-Imposed? |
|---|---|---|---|---|---|
| `timestamp` | DATESZ column | Slide 9 | `src/orbital_mission_compiler/schemas.py:64` | `test_schema.py` | No |
| `event_type` | EV column (ACQ / DOWNLOAD) | Slide 9 | `src/orbital_mission_compiler/schemas.py:65` | `test_schema.py`, `test_schema_negative.py` | No |
| `orbit` | ORBIT column | Slide 9 | `src/orbital_mission_compiler/schemas.py:66` | `test_schema.py`, `test_ir.py` | No |
| `duration_seconds` | DT_EV column (transmission window) | Slide 9 | `src/orbital_mission_compiler/schemas.py:67` | `test_schema.py`, `test_ir.py` | No |
| `instrument` | INST column | Slide 9 | `src/orbital_mission_compiler/schemas.py:68` | `test_schema.py`, `test_schema_negative.py` | No |
| `sensor` | — | — | `src/orbital_mission_compiler/schemas.py:69` | `test_schema.py` | **Yes** — alias/supplement to instrument for ground-side flexibility |
| `ground_visibility` | VISI column (1 = visible) | Slide 9 | `src/orbital_mission_compiler/schemas.py:70` | `test_schema.py`, `test_policy.py` | No |
| `region_type` | — | — | `src/orbital_mission_compiler/schemas.py:71` | `test_schema.py` | **Yes** — contextual metadata (ocean, land, etc.) for ground-side filtering |
| `services` | WORKFLOW_D1-D4 columns | Slide 9 | `src/orbital_mission_compiler/schemas.py:72` | `test_schema.py`, `test_policy.py` | No |

### 1.3 AIService

| Field | ORCHIDE Source | Slide / D3.1 Ref | Implementation | Test Case | Author-Imposed? |
|---|---|---|---|---|---|
| `service_id` | Detector/service identifier (MS, FD, CD) | Slide 9, Slide 10 | `src/orbital_mission_compiler/schemas.py:52` | `test_schema.py`, `test_ir.py` | No |
| `priority` | PRIORITY_D1-D4 columns | Slide 9 | `src/orbital_mission_compiler/schemas.py:53-57` | `test_schema.py`, `test_policy.py` | No (scale divergence: ORCHIDE 1-4 vs schema 0-100; rendering layer converts) |
| `landscape_type` | TYPE_D1-D4 columns (O=ocean, L=land) | Slide 9 | `src/orbital_mission_compiler/schemas.py:58` | `test_schema.py`, `test_ir.py`, `test_policy.py` | No |
| `execution_mode` | "sequential or in parallel" | Slide 10 | `src/orbital_mission_compiler/schemas.py:59` | `test_schema.py`, `test_ir.py`, `test_parallel_rendering.py` | No |
| `steps` | AI service pipeline stages | Slide 10 | `src/orbital_mission_compiler/schemas.py:60` | `test_schema.py`, `test_rendering.py` | No |

### 1.4 WorkflowStep

| Field | ORCHIDE Source | Slide / D3.1 Ref | Implementation | Test Case | Author-Imposed? |
|---|---|---|---|---|---|
| `name` | Pipeline stage name | Slide 10 | `src/orbital_mission_compiler/schemas.py:31` | `test_schema.py`, `test_rendering.py` | No |
| `image` | OCI container image | Slide 10, D3.1 §5.1 | `src/orbital_mission_compiler/schemas.py:32` | `test_schema.py`, `test_rendering.py` | No |
| `phase` | Pre-processing / AI / Post-processing | Slide 10 | `src/orbital_mission_compiler/schemas.py:33` | `test_rendering.py` | No |
| `resource_class` | Hardware target (CPU/GPU/FPGA) | Slide 14 | `src/orbital_mission_compiler/schemas.py:34` | `test_schema.py`, `test_kueue.py` | No |
| `fallback_resource_class` | — | — | `src/orbital_mission_compiler/schemas.py:35` | `test_policy.py` | **Yes** — ground-side reliability for local demo when primary hardware unavailable |
| `needs_acceleration` | ukAccel accelerator mediation | Slide 18 | `src/orbital_mission_compiler/schemas.py:36` | `test_policy.py` | No |
| `command` | Application entry point | D3.1 §5.1 | `src/orbital_mission_compiler/schemas.py:37` | `test_schema.py` | No |
| `args` | Command arguments | D3.1 §5.1 | `src/orbital_mission_compiler/schemas.py:38` | `test_schema.py` | No |
| `metadata` | — | — | `src/orbital_mission_compiler/schemas.py:39` | `test_schema.py` | **Yes** — free-form annotations for ground-side tooling |
| `preferred_node_selector` | — | — | `src/orbital_mission_compiler/schemas.py:40` | `test_schema.py` | **Yes** — Kubernetes node affinity labels for ground-side scheduling |

### 1.5 Enums

| Enum | Values | ORCHIDE Source | Slide / D3.1 Ref |
|---|---|---|---|
| `ResourceClass` | `cpu`, `gpu`, `fpga` | Heterogeneous hardware classes | Slide 14 (ARM64 LX2160, Jetson Xavier/Orin, Versal/Ultrascale) |
| `MissionEventType` | `acquisition`, `download` | EV column categories | Slide 9 (ACQ, DOWNLOAD) |
| `StepPhase` | `preprocessing`, `ai`, `postprocessing` | 3-stage AI pipeline | Slide 10 (Pre-processing → AI → Post-processing) |
| `ExecutionMode` | `sequential`, `parallel` | Application launch mode | Slide 10 ("sequentially or in parallel") |

---

## 2. OPA Policy Rule Traceability

Each deny rule in `configs/policies/mission_plan.rego` is mapped to its ORCHIDE source or marked as Author-Imposed. Rules are numbered 1–10 matching the Rego file order.

| Rule # | Deny Message (exact Rego `msg`) | ORCHIDE Source | Slide / D3.1 Ref | Test Case | Author-Imposed? |
|---|---|---|---|---|---|
| 1 | `mission_id must not be empty` | Structural requirement for plan identity | D3.1 §3.3.1 | `test_policy.py::test_deny_empty_mission_id` | **Yes** — ORCHIDE does not specify validation rules |
| 2 | `mission plan must contain at least one event` | Structural requirement | — | `test_policy.py::test_deny_zero_events` | **Yes** — structural guard |
| 3 | `acquisition event %v must declare at least one service` | ACQ rows have WORKFLOW columns | Slide 9 | `test_policy.py::test_deny_acquisition_no_services` | No — derived from slide 9 table structure |
| 4 | `GPU step %q should declare fallback_resource_class for local demo reliability` | — | — | `test_policy.py::test_deny_gpu_no_fallback` | **Yes** — ground-side reliability; rule requires `resource_class == "gpu"` AND `needs_acceleration == true` AND no `fallback_resource_class` |
| 5 | `service %q has zero priority, which is likely a misconfiguration` | Priorities are 1-4 in ORCHIDE; 0 is misconfiguration | Slide 9 (PRIORITY columns) | `test_policy.py::test_deny_zero_priority` | No — derived from slide 9 priority semantics |
| 6 | `step %q claims needs_acceleration but uses cpu resource class` | ukAccel mediates GPU/FPGA only; CPU is host | Slide 18 | `test_policy.py::test_deny_acceleration_on_cpu` | No — derived from slide 18 ukAccel scope |
| 7 | `download event %v must not declare services (transmission only)` | DOWNLOAD rows have no WORKFLOW columns | Slide 9 | `test_policy.py::test_deny_download_with_services` | No — derived from slide 9 table structure |
| 8 | `download event %v requires ground_visibility (station must be visible for transmission)` | DOWNLOAD requires VISI=1 | Slide 9 | `test_policy.py::test_deny_download_without_visibility` | No — derived from slide 9 VISI column |
| 9 | `service %q has no steps and cannot produce a workflow` | Pipeline requires ≥1 stage | Slide 10 | `test_policy.py` (implicit via schema min_length=1) | No — derived from slide 10 pipeline model |
| 10 | `service %q has unrecognized landscape_type %q (expected: ocean, land)` | TYPE = O (ocean) or L (land) | Slide 9 (TYPE_D1-D4) | `test_policy.py` | No — derived from slide 9 TYPE column |

### Policy Layering Note

Rules 3, 7, 8, and 9 intentionally overlap with Pydantic schema validators for defense-in-depth. Schema catches structural errors at parse time; OPA catches semantic errors when data bypasses schema validation (e.g., raw JSON sent directly to OPA). See `docs/04_architecture.md` for the full validation layering table.

---

## 3. Resource Hints Traceability

Each key in the `resource_hints` dictionary (built in `src/orbital_mission_compiler/compiler.py:compile_plan_to_intents`) is mapped to its derivation source.

| Hint Key | Derivation | Source Field | Slide / D3.1 Ref | Author-Imposed? |
|---|---|---|---|---|
| `event_timestamp` | Direct passthrough | `MissionEvent.timestamp` | Slide 9 (DATESZ) | No |
| `ground_visibility` | Direct passthrough | `MissionEvent.ground_visibility` | Slide 9 (VISI) | No |
| `region_type` | Direct passthrough | `MissionEvent.region_type` | — | **Yes** — contextual metadata |
| `orbit` | Direct passthrough | `MissionEvent.orbit` | Slide 9 (ORBIT) | No |
| `duration_seconds` | Direct passthrough | `MissionEvent.duration_seconds` | Slide 9 (DT_EV) | No |
| `landscape_type` | Direct passthrough | `AIService.landscape_type` | Slide 9 (TYPE_D1-D4) | No |
| `execution_mode` | Enum `.value` passthrough | `AIService.execution_mode` | Slide 10 | No |
| `requires_gpu` | Derived: `bool(steps where resource_class == GPU)` | `WorkflowStep.resource_class` | Slide 14 | **Yes** — derived boolean for downstream schedulers |
| `requires_fpga` | Derived: `bool(steps where resource_class == FPGA)` | `WorkflowStep.resource_class` | Slide 14 | **Yes** — derived boolean for downstream schedulers |
| `fallback_enabled` | Derived: `bool(steps where fallback_resource_class != None)` | `WorkflowStep.fallback_resource_class` | — | **Yes** — derived boolean for fallback-aware renderers |

---

## 4. Ground-Side Additions Rationale (Author-Imposed)

The following features are explicitly added by this project to fill gaps that ORCHIDE leaves open (see `docs/00_transcript_grounding.md`, section "What the sources do NOT specify"):

| Addition | Location | Rationale |
|---|---|---|
| Pydantic schema validation | `src/orbital_mission_compiler/schemas.py` | ORCHIDE does not specify how mission plans are validated before reaching the satellite |
| OPA/Rego policy framework | `configs/policies/mission_plan.rego`, `src/orbital_mission_compiler/policy.py` | ORCHIDE has no policy-as-code; this adds 10 deny rules for semantic validation |
| Kueue admission control | `src/orbital_mission_compiler/compiler.py:render_kueue_job` | ORCHIDE uses a custom priority queue; this adds Kubernetes-native admission via Kueue |
| DRA ResourceClaimTemplate rendering | `src/orbital_mission_compiler/compiler.py:render_resource_claim_templates` | ORCHIDE does not use DRA; this adds `resource.k8s.io/v1` ResourceClaimTemplate for GPU scheduling via Kueue v0.17+ |
| CLI tool | `src/orbital_mission_compiler/cli.py` | ORCHIDE's translation layer is embedded glue code; this extracts a standalone CLI |
| MCP server | `src/orbital_mission_compiler/mcp/server.py` | ORCHIDE has no AI agent interface; this adds 6 MCP tools for ground-side agents |
| Fallback resource class | `src/orbital_mission_compiler/schemas.py:fallback_resource_class` | ORCHIDE has no fallback strategy; ground-side demo reliability |
| Timeline conflict detection | `src/orbital_mission_compiler/compiler.py:detect_timeline_conflicts` | ORCHIDE has no timeline feasibility check; ground-side planning tool |
| Resource hints enrichment | `src/orbital_mission_compiler/compiler.py` (resource_hints dict) | ORCHIDE does not carry extended event metadata through IR; enriched for downstream schedulers |
| Golden eval runner | `src/orbital_mission_compiler/eval_runner.py`, `evals/golden/` | ORCHIDE has no ground-side evaluation framework; deterministic translation tests |

---

## 5. Coverage Summary

| Dimension | Total Items | ORCHIDE-Derived | Author-Imposed | Coverage |
|---|---|---|---|---|
| Schema fields (4 mission-plan models) | 27 | 21 | 6 | 100% traced |
| Enum values | 11 | 11 | 0 | 100% traced |
| OPA deny rules | 10 | 7 | 3 | 100% traced |
| Resource hints keys | 10 | 7 | 3 | 100% traced |
| **Total** | **58** | **46 (79%)** | **12 (21%)** | **100% traced** |

Note: this summary counts the four mission-plan schema models (`MissionPlan`, `MissionEvent`, `AIService`, `WorkflowStep`) and excludes the internal `WorkflowIntent` compiler IR model.

---

## 6. ORCHIDE Slide / D3.1 Cross-Reference Index

For quick lookup, the following ORCHIDE slides and D3.1 sections are referenced in this traceability matrix:

| Source | Content | Referenced By |
|---|---|---|
| Slide 9 | Mission plan table format (DATESZ, ORBIT, EV, INST, TYPE, VISI, WORKFLOW, PRIORITY) | MissionEvent fields, AIService fields, OPA rules 3/5/7/8/10 |
| Slide 10 | AI service pipeline (Pre-processing → AI → Post-processing, sequential/parallel) | StepPhase, ExecutionMode, AIService.steps, OPA rule 9 |
| Slide 14 | Heterogeneous hardware (Jetson, Versal, LX2160, Kalray) | ResourceClass, resource_hints requires_gpu/requires_fpga |
| Slide 18 | ukAccel accelerator mediation (TCP-based, vAccel-derived) | needs_acceleration, OPA rule 6 |
| Slide 23 | Custom Translation Layer (Mission Plan → Argo workflow) | WorkflowIntent, compile_plan_to_intents, render_argo_workflow |
| D3.1 §3.2.1.1 | Mission Manager receives and processes mission plan | load_mission_plan |
| D3.1 §3.2.1.1.2 | Mission Planner determines appropriate service | compile_plan_to_intents (ACQ event filtering) |
| D3.1 §3.3.1 | Interface IF SO_MIS_DP (Satellite Owner deploys plan) | mission_id identity |
| D3.1 §5.1 | Application Builder / OCI image deployment | WorkflowStep.image, command, args |
