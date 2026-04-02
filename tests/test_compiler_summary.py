"""Tests for compiler summary logging."""

import logging

from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents


def test_compilation_summary_logged(caplog):
    """Compiler should log a summary: N intents from M events (K skipped)."""
    plan = load_mission_plan("configs/mission_plans/sample_orchide_format.yaml")
    with caplog.at_level(logging.INFO, logger="orbital_mission_compiler.compiler"):
        compile_plan_to_intents(plan)
    summary = [r for r in caplog.records if "compiled" in r.message.lower() and "intents" in r.message.lower()]
    assert len(summary) == 1
    assert "3 intents" in summary[0].message.lower()
    assert "3 events" in summary[0].message.lower()
    assert "1 skipped" in summary[0].message.lower()
