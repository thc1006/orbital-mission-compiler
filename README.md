# Satellite Mission Compiler

A ground-side, cloud-native mission plan compiler for satellite operations. Validates structured mission plans, applies OPA/Rego policy guardrails, and renders admission-ready Argo Workflow and Kueue Job artifacts before anything reaches an onboard orchestrator.

[![CI](https://github.com/thc1006/satellite-mission-compiler/actions/workflows/ci.yml/badge.svg)](https://github.com/thc1006/satellite-mission-compiler/actions/workflows/ci.yml)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.19389694.svg)](https://doi.org/10.5281/zenodo.19389694)
![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)
[![License: EUPL-1.2](https://img.shields.io/badge/license-EUPL--1.2-blue)](LICENSE)

---

## Why this exists

The [ORCHIDE](https://orchide-project.eu/) project (EU Horizon, ending May 2026) builds an onboard platform for satellite edge computing. Its D3.1 architecture document scopes the on-satellite orchestrator to the "Deferred Phase" -- it executes mission plans but does not itself generate, validate, or compile them.

This project fills that gap on the open-source side: it provides a ground-side toolchain that produces validated, policy-checked, admission-ready workflow artifacts from structured satellite mission plans -- an open-source complement to the consortium's own (closed-source) ground SDK and simulator, which publish no mission-plan schema or policy layer.

## What it does

- Parses and validates mission plans aligned with ORCHIDE KubeCon EU 2026 slide 9 format
- Enforces 10 OPA/Rego policy guardrails (priority, resource class, visibility, landscape type)
- Compiles mission plans through a typed IR (WorkflowIntent) with resource hints
- Renders Argo Workflow DAGs (sequential and parallel execution modes)
- Renders Kueue-compatible Jobs with GPU/FPGA admission metadata
- Exposes 6 MCP tools for AI agent integration (validate, compile, render, explain, diff, timeline conflicts)
- Defines 21 Pydantic interface contracts for simulation, packaging, and platform services

## What it is not

This is not a flight-ready onboard satellite runtime. It does not implement radiation hardening, full HA, OTA update guarantees, or real storage/monitoring integrations. It complements onboard platforms such as ORCHIDE rather than replacing them.

## Quick start

```bash
git clone https://github.com/thc1006/satellite-mission-compiler.git
cd satellite-mission-compiler
pip install -e ".[dev]"
make test        # run the test suite
make eval        # run golden translation checks
make opa-smoke   # OPA policy evaluation (requires opa CLI)
make argo-smoke  # Argo manifest lint (requires argo CLI)
```

## Live cluster validation (optional)

For end-to-end validation against a real cluster:

```bash
bash scripts/install_argo.sh
bash scripts/install_kueue.sh
bash scripts/kueue_demo_apply.sh
make k8s-smoke
```

`k8s-smoke` uses a dedicated Argo runtime service account (`orbital-workflow-runner`) and checks Kueue admission via workload labels bound to the submitted Job UID.
`NAMESPACE` override requires equivalent runtime RBAC (including `orbital-workflow-runner` ServiceAccount + RoleBinding for `workflowtaskresults`) applied in that same namespace.

Useful runtime overrides:

```bash
NAMESPACE=orbital-demo \
QUEUE=orbital-demo-local \
ARGO_SERVICE_ACCOUNT=orbital-workflow-runner \
ARGO_TIMEOUT_SECONDS=120 \
KUEUE_ADMISSION_TIMEOUT_SECONDS=60 \
KUEUE_COMPLETION_TIMEOUT_SECONDS=120 \
make k8s-smoke
```

Note: live-cluster checks are environment-coupled and can fail on shared or CPU-constrained single-node clusters even when compiler logic is correct.

## Local development with Docker Compose

```bash
docker compose up    # Starts OPA server + runs compiler
```

See `docker-compose.yml` for service definitions. The OPA server provides policy evaluation; the compiler service runs a sample compilation.

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

### Fail-closed admission gate

The policy layer runs on **every** plan before any artifact is produced. The CLI `compile` / `render-argo` / `render-kueue` commands and the MCP `compile_plan` / `render_argo` tools are **fail-closed by default**: a plan that violates a policy rule yields no artifact and a non-zero exit (CLI) or a `{"status": "denied", ...}` result (MCP), with the typed violations (`rule`/`rule_id`/`severity`/`provenance`/`path`/`message`) surfaced for triage.

Two interchangeable policy engines back the gate, selected with `--policy-engine`:

- **`opa`** (default for the CLI artifact commands) executes the versioned, independently-auditable Rego bundle — the same policy-as-code artifact an external reviewer runs with `opa eval`, honouring `--bundle` / `--decision`. It **fails closed** if `opa` is unavailable or returns no decision (a distinct non-zero exit); it never silently downgrades.
- **`baseline`** is the proven-equivalent in-process mirror (no subprocess), used for offline/CI use and as the library default. The two engines are asserted to produce identical typed violations on well-formed inputs and identical accept/reject decisions on all inputs.

The four stages remain independent modules callable in isolation (schema, policy, IR, renderer); an explicit `--unsafe-skip-policy` flag (CLI) / `unsafe_skip_policy=True` argument (MCP, honoured only when the server sets `ORBITAL_MCP_ALLOW_POLICY_BYPASS=1`, since the calling agent is untrusted) bypasses the gate for development and forfeits the pre-uplink guarantee. The standalone `policy` subcommand and `opa_smoke.sh` also gate on the decision (non-zero exit on any deny), so they are usable in CI.

On denial the compiler writes **no** new artifact; a file that already exists at the output path is left untouched (it is not deleted, to avoid destroying a prior valid artifact). Consumers should key on the exit code / `denied` status, not on file existence alone.

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
make test        # Unit tests
make eval        # Golden translation evals
make lint        # Ruff linter
```

## Citation

If you use this project in academic work, please cite:

```bibtex
@software{satellite_mission_compiler,
  title     = {Satellite Mission Compiler},
  doi       = {10.5281/zenodo.19389694},
  url       = {https://github.com/thc1006/satellite-mission-compiler},
  publisher = {Zenodo},
  year      = {2026}
}
```

## License

Licensed under the [European Union Public Licence v1.2 (EUPL-1.2)](LICENSE).
