# Satellite Mission Compiler

A ground-side, cloud-native mission plan compiler for satellite operations. Validates structured mission plans, applies OPA/Rego policy guardrails, and renders admission-ready Argo Workflow and Kueue Job artifacts before anything reaches an onboard orchestrator.

[![CI](https://github.com/thc1006/satellite-mission-compiler/actions/workflows/ci.yml/badge.svg)](https://github.com/thc1006/satellite-mission-compiler/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19391965.svg)](https://doi.org/10.5281/zenodo.19391965)
![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)
![License](https://img.shields.io/badge/license-TBD-lightgrey)

---

## Why this exists

The [ORCHIDE](https://orchide-project.eu/) project (EU Horizon, ending May 2026) builds an onboard platform for satellite edge computing. Its D3.1 architecture document explicitly limits scope to the on-satellite "Deferred Phase" -- it receives and executes mission plans but does not generate, validate, or compile them.

This project fills that gap. It provides the ground-side toolchain that produces validated, policy-checked, admission-ready workflow artifacts from structured satellite mission plans.

## What it does

- Parses and validates mission plans aligned with ORCHIDE KubeCon EU 2026 slide 9 format
- Enforces 10 OPA/Rego policy guardrails (priority, resource class, visibility, landscape type)
- Compiles mission plans through a typed IR (WorkflowIntent) with resource hints
- Renders Argo Workflow DAGs (sequential and parallel execution modes)
- Renders Kueue-compatible Jobs with GPU/FPGA admission metadata
- Exposes 4 MCP tools for AI agent integration (validate, compile, render, explain)
- Defines 21 Pydantic interface contracts for simulation, packaging, and platform services

## What it is not

This is not a flight-ready onboard satellite runtime. It does not implement radiation hardening, full HA, OTA update guarantees, or real storage/monitoring integrations. It complements onboard platforms such as ORCHIDE rather than replacing them.

## Quick start

```bash
git clone https://github.com/thc1006/satellite-mission-compiler.git
cd satellite-mission-compiler
pip install -e ".[dev]"
make test        # 145 tests
make eval        # 3 golden translation checks
make opa-smoke   # OPA policy evaluation (requires opa CLI)
make argo-smoke  # Argo manifest lint (requires argo CLI)
```

## Architecture

```
Mission Plan YAML
  --> Schema Validation (Pydantic)
  --> Policy Guard (OPA/Rego)
  --> Workflow Intent IR
  --> Argo Workflow YAML    (sequential or parallel DAG)
  --> Kueue Job YAML        (optional admission mapping)
  --> MCP Tools             (optional, for AI agents)
```

This repo produces rendered YAML artifacts. It does not deploy to or control a live cluster. See [docs/04_architecture.md](docs/04_architecture.md) for the full source-to-ORCHIDE-slide mapping.

## Project structure

```
src/orbital_mission_compiler/   Core: schemas, compiler, policy, CLI, MCP
configs/mission_plans/          Sample YAML mission plans
configs/policies/               OPA/Rego policy rules
contracts/                      Interface contracts (simulation, packaging, platform services)
evals/golden/                   Golden translation test fixtures
tests/                          Unit and integration test suite
scripts/                        Smoke tests, install helpers, demo scripts
.claude/                        Agent configs, hooks, skills, commands
docs/                           Architecture and research documents
```

## ORCHIDE alignment

This project is grounded in the KubeCon EU 2026 presentation "Bringing Cloud-Native PaaS to Space" and ORCHIDE deliverables D2.2/D3.1. Every schema field, policy rule, and rendering decision traces back to a specific slide or document section. See [docs/00_transcript_grounding.md](docs/00_transcript_grounding.md) and [docs/13_market_positioning.md](docs/13_market_positioning.md).

| This project (ground-side) | ORCHIDE (onboard) |
|---|---|
| Mission plan schema validation | Receives plan via IF SO_MIS_DP |
| OPA/Rego policy guardrails | No policy-as-code |
| Argo Workflow + Kueue rendering | Custom Translation Layer (embedded) |
| MCP agent interface | No agent interface |

## Development

All changes follow test-first development. See [AGENTS.md](AGENTS.md) for TDD rules, [docs/06_execution_plan.md](docs/06_execution_plan.md) for the phased roadmap, and [CHANGELOG.md](CHANGELOG.md) for version history.

```bash
make verify      # File structure + syntax check
make test        # Unit tests with coverage
make eval        # Golden translation evals
make lint        # Ruff linter
```

## Citation

If you use this project in academic work, please cite:

```bibtex
@software{satellite_mission_compiler,
  title     = {Satellite Mission Compiler},
  doi       = {10.5281/zenodo.19391965},
  url       = {https://github.com/thc1006/satellite-mission-compiler},
  publisher = {Zenodo},
  year      = {2026}
}
```

## License

TBD
