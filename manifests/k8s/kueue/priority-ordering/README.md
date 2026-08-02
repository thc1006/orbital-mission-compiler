# Kueue priority-ordering experiment

This proves that a mission plan's priority actually drives **Kueue admission
order**, and that the effect comes from *priority*, not from *submission order*.

## Why this exists

A rendered Kueue Job carries an `orbital/priority` annotation and a plain
`priority` label. Neither is read by Kueue. Kueue sorts on the single `spec.priority`
it writes onto the Workload, and it fills that from the `WorkloadPriorityClass` named
by the `kueue.x-k8s.io/priority-class` label; with no such label it falls back to the
pod template's own Kubernetes `PriorityClass`, then to a cluster default, then to 0.
So `render-kueue --priority-class` sets that label (mission priority -> ORCHIDE tier
-> class), and `--emit-priority-classes` writes the four cluster-scoped classes:

| Mission priority | ORCHIDE tier | WorkloadPriorityClass | value |
|---|---|---|---|
| 76-100 | 1 | `orbital-mission-critical` | 400 |
| 51-75  | 2 | `orbital-mission-high`     | 300 |
| 26-50  | 3 | `orbital-mission-normal`   | 200 |
| 1-25   | 4 | `orbital-mission-low`      | 100 |

A `WorkloadPriorityClass` is cluster-scoped, which is why the default names carry an
`orbital-` prefix rather than being plain: `mission-critical` is a name another
installation, or an operator, can reasonably have created already, and applying ours
over it would rewrite theirs. `--priority-class-prefix` sets a different prefix, and
this experiment uses it to give each run its own.

## What the original case study did and did not show

The paper's case study submits two CPU Jobs (priority 90 and 50); the first is
admitted, the second waits. On its own that only shows **quota gating**: the Job
that arrives while quota is free runs, the other waits. It does not, by itself,
isolate priority from arrival order.

## How this experiment isolates priority (reverse submission order)

The ClusterQueue's CPU `nominalQuota` is **1**, so exactly one `cpu=1` Job is
admissible at a time, and **no preemption** is configured.

1. A blocker Job holds the single CPU slot.
2. Submit the **LOW** Job (priority 50 -> `...mission-normal`, value 200) **first**.
3. Wait, then submit the **HIGH** Job (priority 90 -> `...mission-critical`, value 400) **second**.
4. Both are PENDING (quota held). Delete the blocker.
5. Kueue admits the highest-priority **pending** workload first.

If Kueue used arrival order it would admit LOW (submitted first). It admits HIGH,
so priority decided the order. Both Jobs are produced by the compiler
(`render-kueue --priority-class`), so this validates the compiler's output.

## Run it

```bash
bash scripts/validate_kueue_priority.sh
```

Every object the run creates carries that run's identifier in its name and an
`orbital.test/run-id` label, and teardown selects on the label rather than replaying a
manifest, so a namespace, queue or class that was already on the cluster is neither
adopted nor removed. The run refuses to start if any of its names is already taken.
Set `RUN_ID` to reproduce a specific run's names.

## Result (live, this cluster)

Verified on Kubernetes v1.36.3 + Kueue v0.19.0. `results/` holds the captured run,
including the compiler commit it was taken from; re-run it after any change to the
compiler or the harness rather than citing an older capture.

```
LOW  workload priority = 200 (...mission-normal)   submitted first
HIGH workload priority = 400 (...mission-critical) submitted last
both PENDING under full quota
-> after freeing quota, HIGH admitted before LOW
[PASS] priority drove ordering, not creation order
```

The `...mission-critical`/`...mission-normal` values landed on the Kueue **Workloads**
(400 and 200), confirming the `kueue.x-k8s.io/priority-class` label propagated to
Kueue's own priority field, which is what sorts the queue. The run also reads back the
reference's group and kind, so the value is known to have come from the emitted
`WorkloadPriorityClass` rather than from the pod-template fallback above. Preemption
and cohort borrowing use the same priority; this experiment demonstrates the
queue-sorting half. The script tears down the namespace, queue, and classes on
completion.
