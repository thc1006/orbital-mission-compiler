from __future__ import annotations

import json
from pathlib import Path

from .compiler import load_mission_plan, compile_plan_to_intents


def main() -> int:
    eval_dir = Path("evals/golden")
    mission_file = Path("configs/mission_plans/sample_maritime_surveillance.yaml")
    plan = load_mission_plan(mission_file)
    intents = compile_plan_to_intents(plan)
    actual = [
        {
            "service_id": i.service_id,
            "priority": i.priority,
            "requires_gpu": i.resource_hints["requires_gpu"],
        }
        for i in intents
    ]
    golden_file = eval_dir / "sample_maritime_surveillance.expected.json"
    expected = json.loads(golden_file.read_text(encoding="utf-8"))
    if actual != expected:
        print("EVAL FAILED")
        print("expected:", json.dumps(expected, indent=2))
        print("actual:", json.dumps(actual, indent=2))
        return 1
    print("EVAL PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
