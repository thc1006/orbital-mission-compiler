"""Tests for the benchmark scaling script.

Verifies that synthetic mission plan generation produces valid plans
that pass both Pydantic schema validation and OPA policy evaluation.
"""

import json
import pytest

from orbital_mission_compiler.schemas import MissionPlan
from orbital_mission_compiler.policy import opa_available, eval_policy

from orbital_mission_compiler.benchmark import generate_synthetic_plan

BUNDLE = "configs/policies"
DECISION = "data.orbitalmission"


class TestSyntheticPlanGeneration:
    """Test that generate_synthetic_plan produces valid mission plans."""

    def test_generates_plan_with_correct_event_count(self):
        """A synthetic plan with N=10 should have exactly 10 events."""
        plan_dict = generate_synthetic_plan(10)
        assert len(plan_dict["events"]) == 10

    def test_generated_plan_passes_schema_validation(self):
        """The generated plan dict must be valid under MissionPlan schema."""
        plan_dict = generate_synthetic_plan(10)
        plan = MissionPlan.model_validate(plan_dict)
        assert plan.mission_id == "bench-10"
        assert len(plan.events) == 10

    def test_each_event_has_expected_structure(self):
        """Each event should have 1 service with 3 steps, correct fields."""
        plan_dict = generate_synthetic_plan(10)
        for i, event in enumerate(plan_dict["events"]):
            assert event["event_type"] == "acquisition"
            assert event["instrument"] is not None
            assert "timestamp" in event
            assert "orbit" in event
            assert len(event["services"]) == 1
            svc = event["services"][0]
            assert svc["landscape_type"] == "ocean"
            assert svc["priority"] == 50
            assert len(svc["steps"]) == 3
            step_names = [s["name"] for s in svc["steps"]]
            assert step_names == ["preprocess", "detect", "postprocess"]
            for step in svc["steps"]:
                assert step["image"] == "busybox:1.36"
                assert step["resource_class"] == "cpu"

    def test_events_have_unique_timestamps(self):
        """All events must have unique timestamps."""
        plan_dict = generate_synthetic_plan(50)
        timestamps = [e["timestamp"] for e in plan_dict["events"]]
        assert len(timestamps) == len(set(timestamps))

    @pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
    def test_generated_plan_passes_opa_policy(self):
        """The generated plan must pass all 10 OPA policy rules."""
        plan_dict = generate_synthetic_plan(10)
        rc, raw = eval_policy(BUNDLE, plan_dict, DECISION)
        assert rc == 0, f"OPA eval failed (rc={rc}): {raw}"
        parsed = json.loads(raw)
        result = parsed["result"][0]["expressions"][0]["value"]
        assert result["allow"] is True, f"OPA denied: {result.get('deny', [])}"
