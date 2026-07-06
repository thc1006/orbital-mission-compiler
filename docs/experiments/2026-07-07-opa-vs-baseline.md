# OPA subprocess vs. in-process Python baseline (§V-B)

**Date:** 2026-07-07
**Host:** Intel Core i5-7400 @ 3.00 GHz (single core), Ubuntu 24.04, Python 3.12.3, OPA 1.15.1
**Purpose:** Quantify the runtime cost of the OPA subprocess model against an
equivalent in-process validator, to substantiate the governance-not-expressiveness
rationale for choosing OPA (§II-B, §V-A).

## Method

- **Baseline:** `src/orbital_mission_compiler/baseline_validator.py` re-implements
  the ten deny rules of `configs/policies/mission_plan.rego` in pure Python,
  collecting all violations (no short-circuit) exactly as OPA returns its `deny` set.
- **Equivalence proof:** `tests/test_baseline_validator.py` asserts that the
  baseline and OPA return the **same accept/reject decision** on every plan in the
  ablation mutation corpus (14 categories: valid, schema-only, policy-only, and
  both-layer errors). All 14 corpus cases + 3 unit cases pass. Equivalence holds on
  **schema-validated (`model_dump`) inputs** -- the only inputs the pipeline feeds to
  OPA. On raw, non-schema dicts the two can diverge on Rego null/truthiness edge cases
  (e.g. `ground_visibility: null`, non-list collections), all of which the Pydantic
  schema rejects before OPA is invoked; the baseline is faithful on the reachable input
  space, not on arbitrary JSON.
- **Timing:** each validator evaluated the same `model_dump(mode="json")` payload
  for synthetic plans of 10–1000 events, mean of 30 iterations.

## Results (mean ± std)

| N events | Baseline (ms) | OPA subprocess (ms) | OPA / baseline |
|---:|---:|---:|---:|
| 10   | 0.020 ± 0.004 | 17.1 ± 2.9  | 873× |
| 50   | 0.073 ± 0.089 | 20.2 ± 2.0  | 277× |
| 100  | 0.125 ± 0.063 | 27.2 ± 4.5  | 218× |
| 500  | 0.569 ± 0.202 | 69.4 ± 5.1  | 122× |
| 1000 | 1.000 ± 0.072 | 119.8 ± 8.2 | 120× |

## Interpretation

- The in-process validator is **120–870× faster**; the gap is dominated by OPA's
  per-invocation subprocess spawn (a ~17 ms fixed floor visible at N=10).
- In absolute terms the OPA overhead is **120 ms at 1000 events**, negligible
  beside the ~1.3 s YAML+Pydantic parse of the same plan (see Table V).
- We nonetheless keep OPA: policy-as-code can be version-controlled, reviewed, and
  audited by a party who never executes the compiler — governance properties the
  in-process validator cannot provide. The baseline exists only as a performance
  reference and a second equivalence oracle for the policy on schema-validated inputs.

## Reproduce

```bash
PATH="$PWD/.venv-verify/bin:$PATH" .venv-verify/bin/python -m pytest tests/test_baseline_validator.py -q
```
