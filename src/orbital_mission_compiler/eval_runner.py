from __future__ import annotations

import json
from pathlib import Path

from .compiler import load_mission_plan, compile_plan_to_intents


def _run_case(mission_file: Path, golden_file: Path) -> tuple[bool, str]:
    plan = load_mission_plan(mission_file)
    intents = compile_plan_to_intents(plan)
    actual = [
        {
            "service_id": i.service_id,
            "priority": i.priority,
            "requires_gpu": i.resource_hints["requires_gpu"],
            "fallback_enabled": i.resource_hints["fallback_enabled"],
        }
        for i in intents
    ]
    expected = json.loads(golden_file.read_text(encoding="utf-8"))
    if actual != expected:
        return False, json.dumps({"expected": expected, "actual": actual}, indent=2)
    return True, mission_file.name


def main() -> int:
    cases = [
        (
            Path("configs/mission_plans/sample_maritime_surveillance.yaml"),
            Path("evals/golden/sample_maritime_surveillance.expected.json"),
        ),
        (
            Path("configs/mission_plans/sample_gpu_cpu_fallback.yaml"),
            Path("evals/golden/sample_gpu_cpu_fallback.expected.json"),
        ),
    ]
    failed = []
    for mission, golden in cases:
        ok, msg = _run_case(mission, golden)
        if ok:
            print(f"EVAL PASSED: {msg}")
        else:
            failed.append((mission.name, msg))
    if failed:
        print("EVAL FAILED")
        for name, msg in failed:
            print(name)
            print(msg)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
