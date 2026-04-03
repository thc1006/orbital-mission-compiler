#!/usr/bin/env python3
"""Scaling benchmark for the satellite mission compiler pipeline.

Generates synthetic mission plans with varying event counts and
measures each pipeline phase separately: parse, policy (OPA),
compile, argo_render, kueue_render.

Usage:
    PYTHONPATH=src:. python3 scripts/benchmark_scaling.py
"""

from __future__ import annotations

import json
import statistics
import time
from typing import Any

from orbital_mission_compiler.benchmark import generate_synthetic_plan
from orbital_mission_compiler.compiler import (
    compile_plan_to_intents,
    render_argo_workflow,
    render_kueue_job,
)
from orbital_mission_compiler.policy import eval_policy, opa_available
from orbital_mission_compiler.schemas import MissionPlan

BUNDLE = "configs/policies"
DECISION = "data.orbitalmission"
PLAN_SIZES = [10, 50, 100, 500, 1000]
ITERATIONS = 10


def _time_parse(plan_dict: dict[str, Any]) -> tuple[MissionPlan, float]:
    """Time Pydantic schema parsing. Returns (plan, elapsed_seconds)."""
    start = time.perf_counter()
    plan = MissionPlan.model_validate(plan_dict)
    elapsed = time.perf_counter() - start
    return plan, elapsed


def _time_policy(policy_input: dict[str, Any]) -> float:
    """Time OPA policy evaluation. Returns elapsed_seconds.

    Args:
        policy_input: A JSON-normalised dict (from MissionPlan.model_dump(mode="json")).
    """
    start = time.perf_counter()
    rc, raw = eval_policy(BUNDLE, policy_input, DECISION)
    elapsed = time.perf_counter() - start
    if rc != 0:
        raise RuntimeError(f"OPA eval failed (rc={rc}): {raw}")
    result = json.loads(raw)
    allowed = result["result"][0]["expressions"][0]["value"]["allow"]
    if not allowed:
        deny = result["result"][0]["expressions"][0]["value"].get("deny", [])
        raise RuntimeError(f"OPA denied plan: {deny}")
    return elapsed


def _time_compile(plan: MissionPlan) -> tuple[list, float]:
    """Time compilation to workflow intents. Returns (intents, elapsed_seconds)."""
    start = time.perf_counter()
    intents = compile_plan_to_intents(plan)
    elapsed = time.perf_counter() - start
    return intents, elapsed


def _time_argo_render(intents: list) -> float:
    """Time Argo workflow rendering for all intents. Returns elapsed_seconds."""
    start = time.perf_counter()
    for intent in intents:
        render_argo_workflow(intent)
    elapsed = time.perf_counter() - start
    return elapsed


def _time_kueue_render(intents: list) -> float:
    """Time Kueue job rendering for all intents. Returns elapsed_seconds."""
    start = time.perf_counter()
    for intent in intents:
        render_kueue_job(intent)
    elapsed = time.perf_counter() - start
    return elapsed


def run_benchmark(
    sizes: list[int] | None = None,
    iterations: int = ITERATIONS,
    skip_policy: bool = False,
) -> list[dict[str, Any]]:
    """Run the scaling benchmark across plan sizes.

    Args:
        sizes: List of event counts to benchmark. Defaults to PLAN_SIZES.
        iterations: Number of iterations per size. Defaults to ITERATIONS.
        skip_policy: If True, skip OPA policy phase (when OPA is unavailable).

    Returns:
        List of result dicts with timing statistics per plan size.
    """
    if sizes is None:
        sizes = list(PLAN_SIZES)

    results = []
    for n in sizes:
        plan_dict = generate_synthetic_plan(n)

        parse_times = []
        policy_times = []
        compile_times = []
        argo_times = []
        kueue_times = []

        for _ in range(iterations):
            plan, t_parse = _time_parse(plan_dict)
            parse_times.append(t_parse)

            if not skip_policy:
                policy_input = plan.model_dump(mode="json")
                t_policy = _time_policy(policy_input)
                policy_times.append(t_policy)

            intents, t_compile = _time_compile(plan)
            compile_times.append(t_compile)

            t_argo = _time_argo_render(intents)
            argo_times.append(t_argo)

            t_kueue = _time_kueue_render(intents)
            kueue_times.append(t_kueue)

        row: dict[str, Any] = {
            "n_events": n,
            "iterations": iterations,
            "parse_mean": statistics.mean(parse_times),
            "parse_std": statistics.stdev(parse_times) if len(parse_times) > 1 else 0.0,
            "compile_mean": statistics.mean(compile_times),
            "compile_std": statistics.stdev(compile_times) if len(compile_times) > 1 else 0.0,
            "argo_mean": statistics.mean(argo_times),
            "argo_std": statistics.stdev(argo_times) if len(argo_times) > 1 else 0.0,
            "kueue_mean": statistics.mean(kueue_times),
            "kueue_std": statistics.stdev(kueue_times) if len(kueue_times) > 1 else 0.0,
        }
        if not skip_policy:
            row["policy_mean"] = statistics.mean(policy_times)
            row["policy_std"] = statistics.stdev(policy_times) if len(policy_times) > 1 else 0.0
        results.append(row)
    return results


def _fmt(val: float) -> str:
    """Format a timing value in milliseconds with 2 decimal places."""
    return f"{val * 1000:.2f}"


def print_results(results: list[dict[str, Any]], has_policy: bool = True) -> None:
    """Print benchmark results as an aligned table to stdout."""
    if has_policy:
        header = (
            f"{'N':>6}  {'parse (ms)':>18}  {'policy (ms)':>18}  "
            f"{'compile (ms)':>18}  {'argo (ms)':>18}  {'kueue (ms)':>18}"
        )
    else:
        header = (
            f"{'N':>6}  {'parse (ms)':>18}  "
            f"{'compile (ms)':>18}  {'argo (ms)':>18}  {'kueue (ms)':>18}"
        )
    print(header)
    print("-" * len(header))

    for row in results:
        parse_col = f"{_fmt(row['parse_mean'])} +/- {_fmt(row['parse_std'])}"
        compile_col = f"{_fmt(row['compile_mean'])} +/- {_fmt(row['compile_std'])}"
        argo_col = f"{_fmt(row['argo_mean'])} +/- {_fmt(row['argo_std'])}"
        kueue_col = f"{_fmt(row['kueue_mean'])} +/- {_fmt(row['kueue_std'])}"

        if has_policy:
            policy_col = f"{_fmt(row['policy_mean'])} +/- {_fmt(row['policy_std'])}"
            print(
                f"{row['n_events']:>6}  {parse_col:>18}  {policy_col:>18}  "
                f"{compile_col:>18}  {argo_col:>18}  {kueue_col:>18}"
            )
        else:
            print(
                f"{row['n_events']:>6}  {parse_col:>18}  "
                f"{compile_col:>18}  {argo_col:>18}  {kueue_col:>18}"
            )


def main() -> None:
    """Entry point for the benchmark script."""
    has_opa = opa_available()
    skip_policy = not has_opa

    if skip_policy:
        print("WARNING: OPA CLI not found; skipping policy evaluation phase.")
        print()

    print(f"Scaling benchmark: sizes={PLAN_SIZES}, iterations={ITERATIONS}")
    print()

    results = run_benchmark(skip_policy=skip_policy)
    print_results(results, has_policy=has_opa)


if __name__ == "__main__":
    main()
