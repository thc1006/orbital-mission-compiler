#!/usr/bin/env python3
"""Time the OPA subprocess against the in-process baseline validator.

This produces the table in `docs/experiments/2026-07-07-opa-vs-baseline.md`, which
is the paper's SV-B backing data for "we keep OPA for governance, not for speed".

It is written because that table had no producing code. The doc's own "Reproduce"
section runs `pytest tests/test_baseline_validator.py`, which establishes that the
two engines return the SAME decision -- a different claim entirely, and not one that
could ever yield a millisecond figure. So the numbers were reproducible only by
whoever first typed them, and a reader could not tell a regression from a different
machine, a different OPA build or a different policy pack.

The measurement follows the doc's stated method: both engines see the same
`model_dump(mode="json")` payload, which is the only shape the pipeline ever feeds
to OPA, for synthetic plans of 10 to 1000 events.

Usage:
    PYTHONPATH=src:. python3 scripts/benchmark_policy_engines.py
    PYTHONPATH=src:. python3 scripts/benchmark_policy_engines.py --sizes 10,50 --iterations 5
"""

from __future__ import annotations

import argparse
import shutil
import statistics
import subprocess
import time
from pathlib import Path
from typing import Any

from orbital_mission_compiler.ablation import POLICY_BUNDLE, POLICY_DECISION
from orbital_mission_compiler.baseline_validator import evaluate as baseline_evaluate
from orbital_mission_compiler.benchmark import generate_synthetic_plan
from orbital_mission_compiler.policy import eval_policy, opa_available
from orbital_mission_compiler.provenance import emit
from orbital_mission_compiler.schemas import MissionPlan

REPO = Path(__file__).resolve().parent.parent


def opa_version() -> str:
    """The OPA build one of the two columns is a property of."""
    binary = shutil.which("opa")
    if binary is None:
        return "not on PATH"
    try:
        proc = subprocess.run(
            [binary, "version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unknown ({exc})"
    if proc.returncode != 0:
        return f"unknown (opa version exited {proc.returncode})"
    for line in proc.stdout.splitlines():
        if line.lower().startswith("version:"):
            return f"{line.split(':', 1)[1].strip()} ({binary})"
    return f"unknown (unrecognised output) ({binary})"


def _time(fn: Any, iterations: int) -> tuple[float, float]:
    """Mean and population stdev in milliseconds.

    perf_counter, not time(): the baseline runs in tens of microseconds at N=10,
    which is below the resolution `time()` is guaranteed to offer.
    """
    samples = []
    for _ in range(iterations):
        start = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - start) * 1000.0)
    mean = statistics.fmean(samples)
    stdev = statistics.pstdev(samples) if len(samples) > 1 else 0.0
    return mean, stdev


def measure(sizes: list[int], iterations: int) -> list[dict[str, Any]]:
    rows = []
    for n in sizes:
        # Through the schema first, deliberately. The doc's equivalence claim holds
        # on schema-validated input and explicitly does NOT hold on arbitrary
        # dicts, so timing the two engines on a raw dict would compare them on
        # input the pipeline never produces.
        plan = MissionPlan.model_validate(generate_synthetic_plan(n))
        payload = plan.model_dump(mode="json")

        base_mean, base_sd = _time(lambda: baseline_evaluate(payload), iterations)
        opa_mean, opa_sd = _time(
            lambda: eval_policy(REPO / POLICY_BUNDLE, payload, POLICY_DECISION),
            iterations,
        )
        rows.append(
            {
                "n": n,
                "baseline_ms": base_mean,
                "baseline_sd": base_sd,
                "opa_ms": opa_mean,
                "opa_sd": opa_sd,
                # Reported rather than left to the reader, because it is the
                # number the paper's sentence is about.
                "ratio": (opa_mean / base_mean) if base_mean > 0 else float("inf"),
            }
        )
    return rows


def print_table(rows: list[dict[str, Any]]) -> None:
    print("| N events | Baseline (ms) | OPA subprocess (ms) | OPA / baseline |")
    print("|---:|---:|---:|---:|")
    for r in rows:
        print(
            f"| {r['n']} | {r['baseline_ms']:.3f} ± {r['baseline_sd']:.3f} "
            f"| {r['opa_ms']:.1f} ± {r['opa_sd']:.1f} | {r['ratio']:.0f}× |"
        )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sizes", default="10,50,100,500,1000")
    ap.add_argument("--iterations", type=int, default=30)
    args = ap.parse_args(argv)

    if not opa_available():
        # Refuse rather than print a table with one real column. A run without OPA
        # measures the baseline against nothing, and the ratio -- which is the
        # whole claim -- would be meaningless.
        print("ERROR: OPA CLI not found; this benchmark compares against it.")
        return 1

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    emit(
        Path(__file__),
        repo=REPO,
        inputs=tuple(sorted((REPO / POLICY_BUNDLE).glob("*.rego"))),
        environment=(("opa", opa_version()),),
    )
    print(f"Policy-engine benchmark: sizes={sizes}, iterations={args.iterations}\n")
    rows = measure(sizes, args.iterations)
    print_table(rows)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
