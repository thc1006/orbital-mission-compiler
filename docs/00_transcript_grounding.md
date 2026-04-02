# 00_transcript_grounding

This repository is grounded in the corrected transcript of **“Bringing Cloud-Native PaaS to Space: Onboard Edge Computing for Satellites”**.

## What the transcript clearly supports
- Traditional EO satellite flow is sequential and constrained by limited downlink bandwidth.
- The speakers frame the onboard stack as a **PaaS** and the broader target as **Satellite as a Service**.
- A structured mission plan is the control input.
- AI services are modeled as workflows: preprocessing → AI → post-processing.
- The stack is heterogeneous and hardware-aware.
- The speakers selected MirageOS, Unikraft, urunc, K3s, and Argo-related orchestration.
- They introduced in-house managers and an in-house accelerator mediation layer (`ukAccel`).
- They acknowledged remaining security concerns and a future move toward federated multi-satellite systems.

## What the transcript does not fully specify
- Full control-plane HA / failover design
- OTA update strategy
- Quantitative benchmark details
- Exact boundary between Mission Manager and Workflow Manager
- Exact policy model for preemption, deadlines, and state consistency
- Full scope of Security Manager responsibilities

## Consequence for this repo
This repo does **not** attempt to recreate ORCHIDE. It targets the most actionable gap visible from the transcript:
**mission-plan-to-workflow compilation with policy, priority, admission, and observability as first-class concerns.**
