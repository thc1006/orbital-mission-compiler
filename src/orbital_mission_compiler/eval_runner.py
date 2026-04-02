from __future__ import annotations

import json
from pathlib import Path

from .compiler import load_mission_plan, compile_plan_to_intents

PLANS_DIR = Path("configs/mission_plans")
GOLDEN_DIR = Path("evals/golden")


def _discover_cases() -> list[tuple[Path, Path]]:
    """Auto-discover eval cases: for each golden .expected.json, find matching plan."""
    cases = []
    for golden in sorted(GOLDEN_DIR.glob("*.expected.json")):
        stem = golden.name.replace(".expected.json", "")
        plan = PLANS_DIR / f"{stem}.yaml"
        if plan.exists():
            cases.append((plan, golden))
    return cases


def _run_case(mission_file: Path, golden_file: Path) -> tuple[bool, str]:
    plan = load_mission_plan(mission_file)
    intents = compile_plan_to_intents(plan)
    actual = [
        {
            "service_id": i.service_id,
            "priority": i.priority,
            "workflow_name": i.workflow_name,
            "steps": [
                {"name": s.name, "resource_class": s.resource_class.value}
                for s in i.steps
            ],
            "resource_hints": i.resource_hints,
        }
        for i in intents
    ]
    expected = json.loads(golden_file.read_text(encoding="utf-8"))
    if actual != expected:
        return False, json.dumps({"expected": expected, "actual": actual}, indent=2)
    return True, mission_file.name


def main() -> int:
    cases = _discover_cases()
    if not cases:
        print("EVAL WARNING: no eval cases discovered")
        return 1
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
