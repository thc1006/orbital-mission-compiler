# 08_risks_and_unknowns

## Transcript-derived unknowns
- exact control-plane HA strategy
- OTA update path
- exact benchmark methodology
- exact Security Manager responsibilities (D3.1 mentions encryption/authentication only)
- exact Kueue-like admission semantics used by ORCHIDE (uses custom priority queue, not Kueue)
- exact split between Mission Manager and Workflow Manager (clarified in KubeCon slides: Mission Planner schedules, Workflow Manager translates to Argo)

## ORCHIDE-related risks
1. **ORCHIDE open-source release (May 2026)**
   ORCHIDE's KubeCon EU 2026 final slide announces plans to open-source. When released, the onboard Mission Manager may include reusable mission plan translation code. Mitigation: this repo's value is in policy/admission/MCP/standalone tooling, not in translation alone.

2. **ORCHIDE scope expansion**
   Future ORCHIDE work may add ground-side validation or policy features. Mitigation: monitor ORCHIDE releases and differentiate on OPA/Kueue/MCP.

3. **Schema divergence**
   ORCHIDE's mission plan format (per-detector workflows, numeric priorities 1-4) is more detailed than this repo's current schema. Mitigation: align schema incrementally (see docs/06_execution_plan.md).

## Engineering risks
1. **Argo <-> Kueue gap**
   Kueue is great for admission and quota, but project-side glue is still required to align workflow semantics.

2. **GPU path ambiguity**
   ORCHIDE clearly values accelerators (Jetson Xavier/Orin, Versal FPGA, Kalray MPPA), but actual hardware/software integration remains highly target-specific.

3. **Overfitting to Kubernetes**
   ORCHIDE uses K3s, but future constellation-scale systems may require control loops outside vanilla K8s semantics. ORCHIDE's conclusion slide mentions "federated multi-satellite systems" as future vision.

4. **Policy overreach**
   It is easy to encode policy that blocks experimentation; keep policy packs modular and testable.
   Current policy pack: 10 deny rules covering mission_id (including whitespace-only values), events, services, GPU fallback, priority, acceleration/resource coherence, download constraints, step completeness, and landscape type.

5. **False confidence**
   A local lab passing tests is not evidence of flight readiness.

6. **Monitoring stack divergence**
   ORCHIDE uses Vector + OpenSearch + Prometheus + Grafana. This repo targets OpenTelemetry. Both are valid but different choices; document the rationale.

7. **Live-cluster validation sensitivity**
   `make k8s-smoke` can fail on shared single-node clusters due to unrelated CPU pressure or pending workloads, even when compiler/rendering logic is correct.
   Mitigation: treat `k8s-smoke` as environment-coupled validation; keep `make verify && make test && make eval` as deterministic core gates.
