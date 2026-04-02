# Changelog

## v0.1.0 (2026-04-02)

First release of the ground-side ORCHIDE-aligned mission plan compiler.

### Core
- **Mission plan schema** aligned with ORCHIDE KubeCon EU 2026 slide 9: orbit, duration_seconds, landscape_type, StepPhase (preprocessing/ai/postprocessing), ExecutionMode (sequential/parallel).
- **Policy guardrails**: 10 OPA/Rego deny rules covering mission_id, events, services, GPU fallback, zero priority, acceleration coherence, download constraints, empty steps, landscape type.
- **Custom translation layer**: `compile_plan_to_intents()` produces `WorkflowIntent` IR with computed resource_hints (9 fields including execution_mode).
- **Argo Workflow renderer**: DAG-based workflows with phase annotations, priority metadata, resource hints, RFC 1123 name sanitization. Passes `argo lint` v4.0.1.
- **Kueue Job renderer**: optional admission mapping with GPU resource requests, nodeSelector, tolerations. Cluster admission confirmed via integration smoke test.

### Contracts (interface definitions only — no runtime)
- `contracts/simulation.py`: 5 models (AcquisitionReplayEvent, DownloadWindowEvent, WorkflowTrigger, SimulationTimeline, SimulationResult)
- `contracts/packaging.py`: 6 models (ApplicationIdentity, ApplicationInput/Output, RuntimePreference, PolicyHints, PackageManifest)
- `contracts/storage.py`: 3 models (FileRegistration, FileQuery, FileRecord)
- `contracts/monitor.py`: 3 models (MetricPoint, LogEntry, HealthStatus)
- `contracts/communication.py`: 2 models + 1 enum (DownlinkRequest, UplinkAck, UplinkStatus)
- `contracts/security.py`: 2 models (AuthToken, IntegrityCheck)

### Agent tooling
- Claude Code settings.json (defaultMode: plan, PostToolUse hook)
- 12 agents, 10 commands, 8 skills (includes wshobson/agents selection)
- Market positioning document with cross-validated competitive analysis

### Documentation
- 28 .md files aligned with ORCHIDE-complementary mission statement
- Source-to-ORCHIDE-slide mapping table in docs/04_architecture.md
- Validation layering table (schema vs policy defense-in-depth)

### Testing
- 98 tests across 8 test files
- 2 golden eval cases
- OPA smoke, Argo lint, Kueue integration smoke all passing
