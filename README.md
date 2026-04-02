# Satellite Mission Compiler

> This repository is a ground-side ORCHIDE-aligned mission plan compiler.
> It validates structured mission plans, applies policy guardrails, compiles workflow semantics, and renders admission-ready artifacts before anything reaches an onboard orchestrator.
> Simulation, packaging, and platform services are represented here as interface contracts, not full implementations.

Satellite Mission Compiler fills the gap that onboard platforms like [ORCHIDE](https://orchide-project.eu/) explicitly leave open: ORCHIDE's D3.1 limits scope to the on-satellite "Deferred Phase" and receives mission plans via a deployment interface, but does not generate, validate, or compile them. This project provides the ground-side toolchain for that purpose.

## What it does

- Validates structured satellite mission plans
- Applies policy guardrails before deployment
- Compiles mission plans into workflow-ready artifacts
- Renders Argo/Kubernetes manifests for execution pipelines
- Preserves runtime intent such as CPU/GPU/FPGA preference and fallback semantics
- Supports agent-driven development with AGENTS.md, CLAUDE.md, MCP tools, evals, and scripted verification

## What it is not

This repository is **not** a flight-ready onboard satellite runtime.

It is a **ground-side mission-plan compiler and policy/admission scaffold** for cloud-native satellite operations. It complements onboard platforms (such as ORCHIDE) rather than replacing them.

## Quick start

```bash
python3 scripts/verify.py
make test
make eval
make demo-phase2
```

## Development workflow (TDD)

All changes follow test-first development. See `AGENTS.md` for rules and `docs/06_execution_plan.md` for the phased roadmap.

## Project focus
* Mission plan schema and validation
* Policy-as-code for workflow admission
* Workflow compilation and rendering
* K3s / Argo / Kueue-oriented artifact generation
* Agentic development workflows for long-horizon engineering
