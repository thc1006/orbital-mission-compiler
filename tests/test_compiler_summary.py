"""Tests for compiler summary logging."""

import logging

from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents


def test_compilation_summary_logged(caplog):
    """Compiler should log a summary with correct counts derived at runtime."""
    plan = load_mission_plan("configs/mission_plans/sample_orchide_format.yaml")
    with caplog.at_level(logging.INFO, logger="orbital_mission_compiler.compiler"):
        intents = compile_plan_to_intents(plan)

    expected_total = len(plan.events)
    expected_skipped = sum(1 for e in plan.events if e.event_type.value != "acquisition")
    expected_intents = len(intents)

    summary = [r for r in caplog.records if "compiled" in r.message.lower() and "intents" in r.message.lower()]
    assert len(summary) == 1
    msg = summary[0].message.lower()
    assert f"{expected_intents} intents" in msg
    assert f"{expected_total} events" in msg
    assert f"{expected_skipped} skipped" in msg
