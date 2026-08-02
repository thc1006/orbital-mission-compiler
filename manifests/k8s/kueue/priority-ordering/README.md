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

On its own that is still one cell, and in it "higher priority" and "submitted
second" are the same Job — so any mechanism that favours the later arrival predicts
the identical result. The run therefore also races a **control arm**: the same two
plans, the same order, rendered without `--priority-class`. No class label means
Kueue resolves no `WorkloadPriorityClass`, both Workloads take priority 0, the sort
falls through to the creation timestamp, and the prediction inverts to the first
submitted winning. Observed: it does. The apparatus can see arrival order, and the
priority arm is what turns it around.

Each arm races `REPS` times (5 by default) and the run reports the tally, because a
single race cannot separate a mechanism from a coin toss.

Both arms are produced by the compiler (`render-kueue`, with and without
`--priority-class`), so the difference between them is one compiler flag and nothing
else about the Jobs.

### What this does and does not establish

That Kueue admits the higher `spec.priority` first is documented Kueue behaviour,
not a finding. What the run establishes is the **path**: a mission plan's
`priority: 90` becomes an ORCHIDE tier, becomes a class name, becomes a
`WorkloadPriorityClass` whose value is 400, becomes the `spec.priority` Kueue
actually sorts on — with the reference's group read back to show the value came
from that class rather than from the pod-template fallback. The control arm is what
attributes the change to the compiler's flag rather than to anything else in the
rendered Job.

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
priority arm  LOW=200 submitted first, HIGH=400 submitted last -> HIGH admitted first
control arm   no priority class, same order                    -> LOW  admitted first
```

The `...mission-critical`/`...mission-normal` values landed on the Kueue **Workloads**
(400 and 200), confirming the `kueue.x-k8s.io/priority-class` label propagated to
Kueue's own priority field, which is what sorts the queue. The run also reads back the
reference's group and kind on both Workloads, so the values are known to have come
from the emitted `WorkloadPriorityClass` rather than from the pod-template fallback
above. After HIGH is admitted the run waits for LOW and requires it to be admitted
too: beating a workload that could never have run is not evidence, and every earlier
step reads "not admitted yet" and "never admissible" the same way.

The script tears down the namespace, queue, and classes on completion.

### Boundaries

- **Two of the four tiers are raced.** All four classes are applied and all four
  values and mapping labels are read back, but only 400 against 200 is put through an
  admission race. Adjacent tiers (400 against 300) and the bucket edges (25/26,
  50/51, 75/76) are unit-test territory.
- **Two pending workloads, one gap, one direction.** Ordering among k>2, and
  starvation of a low tier under a stream of high ones, are neither shown nor bounded.
- **Queue sorting only.** Preemption, cohort borrowing, admission checks and fair
  sharing use the same priority field and are not exercised. In this configuration a
  a mission-critical plan does *not* evict a running lower-priority one — the blocker
  holds its quota at priority 0 throughout and is never preempted.
- **One trigger.** Quota is freed by deleting the blocker; quota increases, queue
  creation and normal completion are other admission triggers and are not covered.
- **One shape.** CPU-only single-container Jobs, one flavor, one namespace, one node,
  Kubernetes v1.36.3, Kueue v0.19.0, the v1beta2 `priorityClassRef` form. No DRA or
  GPU workload takes part.
- **`--policy-engine baseline`.** The Rego path is not exercised by this run.
