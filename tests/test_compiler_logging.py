"""Tests for compiler logging and skip reporting.

Issue #8: compile_plan_to_intents() silently skips non-acquisition events.
"""

import logging

from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents


def test_download_event_logged_as_skipped(caplog):
    """Skipped DOWNLOAD events must be logged at INFO level."""
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    with caplog.at_level(logging.INFO, logger="orbital_mission_compiler.compiler"):
        compile_plan_to_intents(plan)
    assert any("download" in r.message.lower() and "skip" in r.message.lower() for r in caplog.records), \
        "Expected a log message about skipping download event"


def test_all_acquisition_events_not_logged_as_skipped(caplog):
    """Plans with only ACQ events should produce no skip logs."""
    plan = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    with caplog.at_level(logging.INFO, logger="orbital_mission_compiler.compiler"):
        compile_plan_to_intents(plan)
    skip_msgs = [r for r in caplog.records if "skipping" in r.message.lower()]
    assert skip_msgs == [], "No skip messages expected for ACQ-only plan"


def test_orchide_plan_logs_one_skip(caplog):
    """ORCHIDE plan has 3 events (2 ACQ + 1 DOWNLOAD), should log 1 skip."""
    plan = load_mission_plan("configs/mission_plans/sample_orchide_format.yaml")
    with caplog.at_level(logging.INFO, logger="orbital_mission_compiler.compiler"):
        compile_plan_to_intents(plan)
    skip_msgs = [r for r in caplog.records if "skipping" in r.message.lower()]
    assert len(skip_msgs) == 1
