# Phase-wise compilation scaling — backing data for Table V (§V-B)

**Date:** 2026-07-07
**Host:** Intel Core i5-7400 @ 3.00 GHz (single core), Ubuntu 24.04, Python 3.12.3, OPA 1.15.1
**Reproduce:** `python3 scripts/run_experiments.py --only scaling`. The filed
transcript is [`results/scaling.txt`](results/scaling.txt), which records the commit,
the harness digest, the interpreter, the copy of the compiler that ran and the CPU it
measured on -- the header above is a hand-written claim about the same things, and a
reader cannot tell whether the two agree without it.

**Iterations:** 30 per plan size.
**Note on the host:** this box also runs the single-node kubeadm cluster used in
§V-D/§V-E, so the sub-100 ms `compile`/`render` phases carry background-load
jitter (large relative std); the heavy `parse`/`total` figures average it out.
This supersedes the older 10-iteration `paper/experiment-benchmark.txt` (April,
pre-YAML-parse-fix), which is not comparable: `benchmark_scaling.py::_time_parse`
now measures the real `yaml.safe_load` + `model_validate` path (see that file).

## Exact measurement (reproduces Table V)

`Render` = argo + kueue rendering combined; `Total` = parse + OPA + compile + render,
summed per iteration (so Total's std is the std of the per-iteration sum).

```python
import time, yaml, statistics
from orbital_mission_compiler.benchmark import generate_synthetic_plan
from orbital_mission_compiler.schemas import MissionPlan
from orbital_mission_compiler.compiler import (
    compile_plan_to_intents, render_argo_workflow, render_kueue_job)
from orbital_mission_compiler.policy import eval_policy
B, D = "configs/policies", "data.orbitalmission"
for n in [10, 50, 100, 500, 1000]:
    ys = yaml.safe_dump(generate_synthetic_plan(n), sort_keys=False)
    P = PO = C = R = T = None
    P, PO, C, R, T = [], [], [], [], []
    for _ in range(30):
        s = time.perf_counter(); plan = MissionPlan.model_validate(yaml.safe_load(ys)); tp = time.perf_counter() - s
        pi = plan.model_dump(mode="json")
        s = time.perf_counter(); eval_policy(B, pi, D); tpol = time.perf_counter() - s
        s = time.perf_counter(); intents = compile_plan_to_intents(plan); tc = time.perf_counter() - s
        s = time.perf_counter(); [render_argo_workflow(i) for i in intents]; ta = time.perf_counter() - s
        s = time.perf_counter(); [render_kueue_job(i) for i in intents]; tk = time.perf_counter() - s
        tr = ta + tk; tot = tp + tpol + tc + tr
        for lst, v in ((P, tp), (PO, tpol), (C, tc), (R, tr), (T, tot)):
            lst.append(v * 1000)
    f = lambda x: f"{statistics.mean(x):.1f}+/-{statistics.stdev(x):.1f}"
    print(n, f(P), f(PO), f(C), f(R), f(T),
          f"parse_share={statistics.mean(P)/statistics.mean(T)*100:.1f}%")
```

Run with `PATH="$PWD/.venv-verify/bin:$PATH" .venv-verify/bin/python <this-snippet>`
(requires the opa CLI on PATH).

## Result (Table V, ms, mean ± std over 30 iterations)

| N events | Parse | OPA | Compile | Render | Total | parse share |
|---:|---:|---:|---:|---:|---:|---:|
| 10   | 14.1 ± 3.9   | 18.8 ± 3.2 | 0.2 ± 0.0  | 0.5 ± 0.3  | 33.7 ± 6.4   | 41.8% |
| 50   | 64.6 ± 10.8  | 21.5 ± 3.9 | 0.9 ± 0.1  | 2.4 ± 1.3  | 89.4 ± 13.7  | 72.3% |
| 100  | 127 ± 7      | 27.7 ± 4.0 | 1.8 ± 0.4  | 5.2 ± 2.0  | 162 ± 8      | 78.4% |
| 500  | 641 ± 16     | 68.4 ± 6.1 | 11.2 ± 6.5 | 28.4 ± 7.7 | 749 ± 19     | 85.6% |
| 1000 | 1323 ± 36    | 115 ± 5    | 20.9 ± 9.2 | 62.7 ± 14.5| 1522 ± 44    | 86.9% |

## Reading of the data (matches §V-B)

- **Parse and total scale near-linearly**; parse (pure-Python YAML load + Pydantic)
  dominates at scale (share 41.8% → 86.9%). A C YAML loader would cut parse
  several-fold and change this balance.
- **OPA is sub-linear** (18.8 → 115 ms): a fixed subprocess-startup floor dominates.
- **compile/render** are order-of-magnitude costs only — their 20–45% relative std
  is host background-load jitter, not intrinsic to the fixed-work phases.


## What commit these numbers measured, and a re-measurement

This table records the host, the iteration count and the exact snippet, and not
the commit. Every phase in it is a function this repository has changed since, so
a reader re-running the snippet cannot tell a regression from a different
codebase. That gap is closed going forward rather than backwards:
`scripts/benchmark_scaling.py` now prints the commit, the working-tree state, its
own checksum, the interpreter, the copy of the compiler it imported and the CPU it
read from the machine, and `scripts/run_experiments.py` files its transcript only
when all of those are present. The result lives at
[`results/scaling.txt`](results/scaling.txt).

Reading the current transcript against the frozen table above (same host, same 30
iterations; `Render` above is `argo + kueue`, reported separately in the transcript):

- **Parse is unchanged** -- 1305 ms against 1323 at N=1000, 123 against 127 at N=100.
  That is the question that prompted the re-measurement: the schema now runs a model
  validator on every compiled intent, and it does not show. So the added validation is
  below this host's jitter.
- **The render phases got measurably more expensive.** Kueue rendering at N=1000 has
  roughly doubled across this stack, and Argo and compile rose with it. This is the
  same trade recorded in [the OPA-vs-baseline note](2026-07-07-opa-vs-baseline.md):
  the structured-violation work allocates and formats per occurrence where the earlier
  code appended a string, and the Kueue renderer now derives its claim templates from
  the steps rather than from a hint. Both are deliberate, and both are still a rounding
  error beside the 1.3-second parse that dominates every row.
- **OPA moves with the host, not with the code.** It has read 115, 174 and 155 ms at
  N=1000 across three measurements of a phase none of these changes touch. This box
  runs the single-node cluster used in SV-D/SV-E throughout, and the note above already
  records that its sub-100 ms phases carry background-load jitter. Attributing that
  spread would need a quiet host and a bisect, and neither has been done -- so it is
  reported and not explained.
- The paper's Table V is frozen with the camera-ready and none of this touches it. The
  numbers here are for a future arXiv version, and the point of recording the commit is
  that the next comparison can be attributed rather than guessed at.
