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

**Reproduce:** `python3 scripts/run_experiments.py --only policy-engines`. The filed
transcript is [`results/policy-engines.txt`](results/policy-engines.txt), which records
the commit, the harness and Rego-pack digests, the interpreter, the CPU and the OPA
build. Until that harness was written this table had no producing code at all: the
"Reproduce" section at the foot of this file runs the *equivalence* test, which cannot
yield a millisecond figure.

| N events | Baseline (ms) | OPA subprocess (ms) | OPA / baseline |
|---:|---:|---:|---:|
| 10 | 0.022 ± 0.003 | 19.1 ± 0.9 | 875× |
| 50 | 0.111 ± 0.013 | 24.6 ± 0.9 | 222× |
| 100 | 0.221 ± 0.021 | 31.3 ± 1.0 | 142× |
| 500 | 1.108 ± 0.051 | 84.9 ± 2.8 | 77× |
| 1000 | 2.232 ± 0.142 | 153.3 ± 7.3 | 69× |

### These numbers replace an earlier table, and the baseline got slower

The first measurement of this table, taken 2026-07-07, read 0.020 / 0.073 / 0.125 /
0.569 / 1.000 ms for the baseline and 873× / 277× / 218× / 122× / 120× for the ratio.
The baseline column is now roughly twice as large at the top end, and the ratio at
N=1000 fell from 120× to 69×.

That is this branch's own doing, and it was checked rather than assumed: running the
same harness against `origin/main`'s `baseline_validator.py` gives 0.972 ms at N=1000,
which is the old figure. The cost is the structured-violation work — stable rule ids,
severity tier and provenance on every violation, and occurrence-level reporting instead
of one entry per rule. Each violation now allocates a dict and formats a path, where
the earlier version appended a string.

It is a deliberate trade and not a defect: 2.2 ms at 1000 events is still negligible
next to the ~1.3 s YAML+Pydantic parse of the same plan, and the structure is what the
CLI and MCP surfaces now report. But the paper's phrasing has to follow the numbers.
The frozen camera-ready (v0.4.2) describes the code as it was and stays as it is; any
later version citing this table must use the figures above and say **69–875×**, not
**120–870×**.

## Interpretation

- The in-process validator is **69–875× faster**; the gap is dominated by OPA's
  per-invocation subprocess spawn (a ~19 ms fixed floor visible at N=10). The ratio
  narrows with N because the baseline now does per-occurrence structured work while
  OPA's cost stays dominated by the fixed spawn.
- In absolute terms the OPA overhead is **153 ms at 1000 events**, negligible
  beside the ~1.3 s YAML+Pydantic parse of the same plan (see Table V).
- We nonetheless keep OPA: policy-as-code can be version-controlled, reviewed, and
  audited by a party who never executes the compiler — governance properties the
  in-process validator cannot provide. The baseline exists only as a performance
  reference and a second equivalence oracle for the policy on schema-validated inputs.

## Reproduce the equivalence claim

This checks that the two engines agree on the DECISION. It is not what produces the
table above -- see the Reproduce line in Results for that.

```bash
PATH="$PWD/.venv-verify/bin:$PATH" .venv-verify/bin/python -m pytest tests/test_baseline_validator.py -q
```
