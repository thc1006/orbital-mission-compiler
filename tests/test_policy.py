"""Tests for OPA policy evaluation against mission_plan.rego deny rules."""

import json
import pytest

from orbital_mission_compiler.policy import opa_available, eval_policy

BUNDLE = "configs/policies"
DECISION = "data.orbitalmission"

pytestmark = pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")


def _eval(payload: dict) -> dict:
    """Run OPA eval and return the policy result value."""
    rc, raw = eval_policy(BUNDLE, payload, DECISION)
    parsed = json.loads(raw)
    return parsed["result"][0]["expressions"][0]["value"]


# ── Deny rule 1: mission_id must not be empty ──────────────────────────


def test_deny_empty_mission_id():
    payload = {
        "mission_id": "",
        "events": [{"timestamp": "t", "event_type": "download"}],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("mission_id must not be empty" in m for m in result["deny"])


# ── Deny rule 2: must contain at least one event ───────────────────────


def test_deny_zero_events():
    payload = {
        "mission_id": "test-mission",
        "events": [],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("at least one event" in m for m in result["deny"])


# ── Deny rule 3: acquisition event must have at least one service ──────


def test_deny_acquisition_no_services():
    payload = {
        "mission_id": "test-mission",
        "events": [
            {
                "timestamp": "2026-04-15T10:00:00Z",
                "event_type": "acquisition",
                "services": [],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("must declare at least one service" in m for m in result["deny"])


# ── Deny rule 4: GPU+acceleration step must declare fallback ───────────


def test_deny_gpu_no_fallback():
    payload = {
        "mission_id": "test-mission",
        "events": [
            {
                "timestamp": "2026-04-15T10:00:00Z",
                "event_type": "acquisition",
                "services": [
                    {
                        "service_id": "test-svc",
                        "priority": 50,
                        "steps": [
                            {
                                "name": "gpu-step",
                                "image": "example:latest",
                                "resource_class": "gpu",
                                "needs_acceleration": True,
                            }
                        ],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("fallback_resource_class" in m for m in result["deny"])


# ── Positive case: valid plan must be allowed ──────────────────────────


def test_allow_valid_plan():
    payload = {
        "mission_id": "valid-mission",
        "events": [
            {
                "timestamp": "2026-04-15T10:00:00Z",
                "event_type": "acquisition",
                "services": [
                    {
                        "service_id": "valid-svc",
                        "priority": 80,
                        "steps": [
                            {
                                "name": "preprocess",
                                "image": "example:latest",
                                "resource_class": "cpu",
                            },
                            {
                                "name": "detect",
                                "image": "example:latest",
                                "resource_class": "gpu",
                                "needs_acceleration": True,
                                "fallback_resource_class": "cpu",
                            },
                        ],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is True
    assert result["deny"] == []
