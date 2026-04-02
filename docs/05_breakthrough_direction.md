# 05_breakthrough_direction

## Main recommendation
**Build a Mission Plan Compiler with policy, priority, and admission semantics as first-class artifacts.**

### Why this is the best “breakthrough but buildable” direction
It is breakthrough enough because it turns the transcript's implicit glue layer into an explicit product:
- a machine-checkable mission plan schema,
- a policy-driven compiler,
- deterministic workflow emission,
- Kueue-friendly admission semantics,
- an MCP surface for AI coding agents.

It is buildable because:
- it can be developed entirely on the ground,
- it does not require flight hardware,
- it reuses mature open-source components,
- it supports CPU-first development with optional GPU enhancement.

## Backup directions

### Backup A — Accelerator Broker Lab
Build a ukAccel-inspired broker simulator for GPU/FPGA resource classes.
- Pro: closer to accelerator mediation theme
- Con: narrower and less complete than mission-plan compilation

### Backup B — Constellation Federation Simulator
Model inter-satellite resource exchange and delayed workflow admission.
- Pro: ambitious roadmap alignment
- Con: too many unknowns from the transcript; high modeling risk

### Backup C — Secure Image Provenance / Policy Platform
Focus on signatures, SBOMs, and policy enforcement for onboard workloads.
- Pro: valuable and security-relevant
- Con: transcript does not define the real security boundary in enough detail

## MVP vs end-state
### MVP
- schema validation
- policy pack
- workflow intent IR
- Argo renderer
- sample K3s/Argo/Kueue scripts
- MCP tools

### End-state
- richer admission bridge
- plan diffs and versioned policy bundles
- richer observability export
- optional accelerator broker integration
- simulated delayed downlink / mission window constraints
