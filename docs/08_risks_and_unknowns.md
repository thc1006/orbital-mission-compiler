# 08_risks_and_unknowns

## Transcript-derived unknowns
- exact control-plane HA strategy
- OTA update path
- exact benchmark methodology
- exact Security Manager responsibilities
- exact Kueue-like admission semantics used by ORCHIDE
- exact split between Mission Manager and Workflow Manager

## Engineering risks
1. **Argo ↔ Kueue gap**
   Kueue is great for admission and quota, but project-side glue is still required to align workflow semantics.

2. **GPU path ambiguity**
   The transcript clearly values accelerators, but actual hardware/software integration remains highly target-specific.

3. **Overfitting to Kubernetes**
   The transcript uses K3s, but future constellation-scale systems may require control loops outside vanilla K8s semantics.

4. **Policy overreach**
   It is easy to encode policy that blocks experimentation; keep policy packs modular and testable.

5. **False confidence**
   A local lab passing tests is not evidence of flight readiness.
