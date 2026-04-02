# Satellite Mission Compiler

**Mission plan–to–workflow orchestration for cloud-native space operations.**

Satellite Mission Compiler is a ground-side framework for turning structured satellite mission plans into validated, policy-aware workflow artifacts for Argo and Kubernetes.

It is designed for cloud-native space operations where mission plans, workflow priorities, observability, and heterogeneous runtime hints must be modeled explicitly before deployment.

## What it does

- Validates structured satellite mission plans
- Applies policy guardrails before deployment
- Compiles mission plans into workflow-ready artifacts
- Renders Argo/Kubernetes manifests for execution pipelines
- Preserves runtime intent such as CPU/GPU/FPGA preference and fallback semantics
- Supports agent-driven development with AGENTS.md, CLAUDE.md, MCP tools, evals, and scripted verification

## What it is not

This repository is **not** a flight-ready onboard satellite runtime.

It is a **ground-side mission-plan compiler and policy/admission scaffold** for cloud-native satellite operations.

## Quick start

```bash
python3 scripts/verify.py
make test
make eval
make demo-phase2
```

## Project focus
* Mission plan schema and validation
* Policy-as-code for workflow admission
* Workflow compilation and rendering
* K3s / Argo / Kueue-oriented artifact generation
* Agentic development workflows for long-horizon engineering
