# Kueue priority-ordering experiment

This proves that a mission plan's priority actually drives **Kueue admission
order**, and that the effect comes from *priority*, not from *submission order*.

## Why this exists

A rendered Kueue Job carries an `orbital/priority` annotation and a plain
`priority` label. Neither is read by Kueue. Kueue orders workloads only by a
`WorkloadPriorityClass` (or a Kubernetes `PriorityClass`), referenced through the
`kueue.x-k8s.io/priority-class` label. So `render-kueue --priority-class` sets that
label (mission priority -> ORCHIDE tier -> class), and `--emit-priority-classes`
writes the four cluster-scoped classes:

| Mission priority | ORCHIDE tier | WorkloadPriorityClass | value |
|---|---|---|---|
| 76-100 | 1 | `mission-critical` | 400 |
| 51-75  | 2 | `mission-high`     | 300 |
| 26-50  | 3 | `mission-normal`   | 200 |
| 1-25   | 4 | `mission-low`      | 100 |

## What the original case study did and did not show

The paper's case study submits two CPU Jobs (priority 90 and 50); the first is
admitted, the second waits. On its own that only shows **quota gating**: the Job
that arrives while quota is free runs, the other waits. It does not, by itself,
isolate priority from arrival order.

## How this experiment isolates priority (reverse submission order)

The ClusterQueue's CPU `nominalQuota` is **1**, so exactly one `cpu=1` Job is
admissible at a time, and **no preemption** is configured.

1. A blocker Job holds the single CPU slot.
2. Submit the **LOW** Job (priority 50 -> `mission-normal`, value 200) **first**.
3. Wait, then submit the **HIGH** Job (priority 90 -> `mission-critical`, value 400) **second**.
4. Both are PENDING (quota held). Delete the blocker.
5. Kueue admits the highest-priority **pending** workload first.

If Kueue used arrival order it would admit LOW (submitted first). It admits HIGH,
so priority decided the order. Both Jobs are produced by the compiler
(`render-kueue --priority-class`), so this validates the compiler's output.

## Run it

```bash
bash scripts/validate_kueue_priority.sh
```

## Result (live, this cluster)

Verified on Kubernetes v1.36.3 + Kueue v0.19.0, reproduced twice:

```
LOW  workload priority = 200 (mission-normal)   submitted first
HIGH workload priority = 400 (mission-critical) submitted last
both PENDING under full quota
-> after freeing quota, HIGH admitted before LOW
[PASS] priority drove ordering, not creation order
```

The `mission-critical`/`mission-normal` values landed on the Kueue **Workloads**
(200 and 400), confirming the `kueue.x-k8s.io/priority-class` label propagated to
Kueue's own priority field, which is what sorts the queue. Preemption and cohort
borrowing use the same priority; this experiment demonstrates the queue-sorting
half. The script tears down the namespace, queue, and classes on completion.
