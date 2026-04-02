# orbital-mission-compiler

A ground-first development scaffold for **mission-plan-aware onboard orchestration** inspired by the ORCHIDE KubeCon Europe 2026 session.

This repository does **not** claim to reproduce ORCHIDE. It focuses on the gaps that were visible in the corrected transcript:
- turning a mission plan into an executable workflow,
- validating mission plans and workflow requests with machine-checkable policy,
- adding explicit priority / admission / preemption semantics,
- keeping the system observable and agent-friendly,
- staying buildable on Ubuntu 22.04 / 24.04 with optional K3s and optional GPU nodes.

## What this scaffold is for

This repo is a **developer lab** for building a “Mission Plan Compiler”:
1. parse structured mission plans,
2. validate them against policy,
3. compile them into workflow intent / Argo Workflow manifests,
4. produce resource hints for CPU / GPU / FPGA-like classes,
5. expose the compiler through CLI and optional MCP,
6. run reproducible evals on mission-plan → workflow translation.

## What this scaffold is not

- It is **not** a flight-qualified onboard system.
- It is **not** a complete satellite software stack.
- It is **not** a proof that control-plane HA, OTA updates, radiation tolerance, or full security posture are solved.

## Quick start

### Python-only local verification
```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev]"
make verify
```

### Optional local K3s + Argo + Kueue
```bash
bash scripts/install_k3s.sh
bash scripts/install_argo.sh
bash scripts/install_kueue.sh
```

### Compile a sample mission plan
```bash
python -m orbital_mission_compiler.cli compile   --input configs/mission_plans/sample_maritime_surveillance.yaml   --output /tmp/sample_workflow.yaml
```

## Key docs
- `docs/00_transcript_grounding.md`
- `docs/04_architecture.md`
- `docs/05_breakthrough_direction.md`
- `docs/07_installation_matrix.md`
- `docs/09_validation_checklist.md`

## Status

The repository skeleton, scripts, and Python code have been generated and syntax-checked locally. External tool installation, Kubernetes bootstrap, and GPU execution were **not** executed end-to-end in this environment. Treat this repo as a **research-backed scaffold**, not as an already-proven production deployment.
