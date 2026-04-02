# 00_transcript_grounding

This repository is grounded in the KubeCon EU 2026 presentation **"Bringing Cloud-Native PaaS to Space: Onboard Edge Computing for Satellites"** by Adele Karam Hankache (Thales Alenia Space) and Sergiu Weisz (Politehnica Bucharest), plus the ORCHIDE project deliverables D2.2 and D3.1.

## Primary sources
- KubeCon EU 2026 slides (36 pages, PDF)
- ORCHIDE D3.1: Overall Solution Architecture and Design (34 pages, July 2024)
- ORCHIDE D2.2: State of the Art (23 pages, May 2024)
- EU CORDIS project page (grant 101135595)

## What the sources clearly support

### Mission plan as control input
- Satellites follow a structured mission plan (slide 9).
- The plan is a table with: DATESZ, ORBIT, EV (ACQ/DOWNLOAD), INST, TYPE_D1-D4 (O=Ocean/L=Land), VISI, WORKFLOW_D1-D4 (MS/FD/CD), PRIORITY_D1-D4.
- AI Services are specified per acquisition event, each with a given priority (slide 9).
- The Mission Planner "determines the appropriate service to be initiated based on the mission plan and the acquired data" (D3.1 Section 3.2.1.1.2).

### Workflow pipeline
- Each AI Service is composed of several applications: Pre-processing -> AI -> Post-processing (slide 10).
- Applications configured to be launched sequentially or in parallel.
- The Workflow Manager implements "a translation from Mission Plan to Argo workflow" (slide 23).

### Technology stack
- Orchestration: K3s (chosen over KubeEdge, K0s, MicroK8s, Oakestra — slide 19).
- Workflow engine: Argo Workflows (slide 15).
- Runtime: containerd + urunc (unikernel OCI runtime) (slide 17-18).
- Unikernel frameworks: MirageOS and Unikraft (slide 16).
- Accelerator mediation: ukAccel (in-house, TCP-based, based on vAccel) (slide 18).
- Storage: EOS distributed filesystem + Zot OCI registry (slide 15, 22).
- Monitoring: Vector (Datadog) on each node -> ground: OpenSearch + Prometheus + Grafana (slide 24).
- Registry: Zot (slide 15).

### Heterogeneous hardware
- Worker nodes: Nvidia Jetson Xavier/Orin (GPU), SOC FPGA Versal/Ultrascale (FPGA), ARM64 LX2160 (CPU), MPPA Kalray v2 (slide 14).
- "Efficient Resource Usage - Enables parallel execution and optimal accelerator assignment" (slide 14).

### Platform services (orchestrator node)
- Mission Planner, Argo Workflows, Mission Manager (slide 20).
- Communication Manager, Security Manager (slide 20).
- Storage Manager (Zot + EOS), Monitor Manager (Vector + API) (slide 20).

### ORCHIDE scope boundaries (D3.1)
- "Out of the three stages, only the Deferred Phase is part of the ORCHIDE scope." (D3.1 p.8)
- Acquisition phase and Transmission phase are explicitly excluded.
- Mission plan is deployed by the Satellite Owner via interface IF SO_MIS_DP (D3.1 Section 3.3.1).
- Mission plan generation, validation, and compilation are NOT in ORCHIDE scope.

### Open source plans
- "The ORCHIDE project will be made available to the community as an open-source project" (slide 35).
- As of April 2026: no public repository yet. Project ends May 2026.

## What the sources do NOT specify
- How mission plans are generated, validated, or compiled before reaching the satellite.
- Any policy-as-code framework (OPA, Rego, Kyverno) for plan validation.
- Any Kueue or formal admission control framework (uses custom priority queue).
- Any MCP or AI agent integration for ground-side tooling.
- Full control-plane HA / failover design.
- OTA update strategy.
- Exact benchmark methodology.
- Exact Security Manager responsibilities beyond encryption/authentication.

## Consequence for this repo
This repo targets the gap that ORCHIDE explicitly leaves open: the ground-side toolchain that generates, validates, and compiles mission plans **before** they are deployed to the satellite. It provides:
- schema validation (which ORCHIDE does not),
- policy guardrails (which ORCHIDE does not),
- Kueue admission semantics (which ORCHIDE does not),
- MCP agent interface (which ORCHIDE does not),
- a standalone CLI tool (ORCHIDE's translation is embedded glue code).
