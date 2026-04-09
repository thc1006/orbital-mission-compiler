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
    assert rc == 0, f"OPA eval failed (rc={rc}): {raw}"
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


def test_deny_whitespace_mission_id():
    payload = {
        "mission_id": "   ",
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


# ── Deny rule 5: service priority must not be zero ─────────────────────


def test_deny_zero_priority():
    """Priority 0 is likely a misconfiguration (slide 9: priorities are 1-4)."""
    payload = {
        "mission_id": "test",
        "events": [
            {
                "timestamp": "t",
                "event_type": "acquisition",
                "services": [
                    {
                        "service_id": "svc",
                        "priority": 0,
                        "steps": [{"name": "s", "image": "img", "resource_class": "cpu"}],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("priority" in m.lower() and "zero" in m.lower() for m in result["deny"])


# ── Deny rule 6: needs_acceleration on CPU is contradictory ────────────


def test_deny_acceleration_on_cpu():
    """A step claiming needs_acceleration=true with resource_class=cpu is contradictory."""
    payload = {
        "mission_id": "test",
        "events": [
            {
                "timestamp": "t",
                "event_type": "acquisition",
                "services": [
                    {
                        "service_id": "svc",
                        "priority": 1,
                        "steps": [
                            {
                                "name": "bad-step",
                                "image": "img",
                                "resource_class": "cpu",
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
    assert any("acceleration" in m.lower() for m in result["deny"])


# ── Deny rule 7: download event must not carry services ────────────────


def test_deny_download_with_services():
    """Download events are transmission windows, not processing triggers (slide 9)."""
    payload = {
        "mission_id": "test",
        "events": [
            {
                "timestamp": "t",
                "event_type": "download",
                "services": [
                    {
                        "service_id": "svc",
                        "priority": 1,
                        "steps": [{"name": "s", "image": "img", "resource_class": "cpu"}],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("download" in m.lower() and "service" in m.lower() for m in result["deny"])


# ── Deny rule 8: download must have ground visibility ──────────────────


def test_deny_download_without_visibility():
    """Download requires ground station visibility (slide 9: DOWNLOAD VISI=1)."""
    payload = {
        "mission_id": "test",
        "events": [
            {
                "timestamp": "t",
                "event_type": "download",
                "ground_visibility": False,
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("visibility" in m.lower() for m in result["deny"])


# ── Deny rule 9: service must have at least one step ───────────────────


def test_deny_service_with_no_steps():
    """A service with zero steps cannot produce any workflow."""
    payload = {
        "mission_id": "test",
        "events": [
            {
                "timestamp": "t",
                "event_type": "acquisition",
                "services": [
                    {"service_id": "empty", "priority": 1, "steps": []},
                ],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("step" in m.lower() for m in result["deny"])


# ── Deny rule 10: landscape_type must be a recognized value ────────────


def test_deny_invalid_landscape_type():
    """landscape_type should be ocean or land (slide 9: TYPE = O or L)."""
    payload = {
        "mission_id": "test",
        "events": [
            {
                "timestamp": "t",
                "event_type": "acquisition",
                "services": [
                    {
                        "service_id": "svc",
                        "priority": 1,
                        "landscape_type": "mars",
                        "steps": [{"name": "s", "image": "img", "resource_class": "cpu"}],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("landscape" in m.lower() for m in result["deny"])


def test_allow_valid_landscape_types():
    """ocean and land must be accepted."""
    for lt in ["ocean", "land"]:
        payload = {
            "mission_id": "test",
            "events": [
                {
                    "timestamp": "t",
                    "event_type": "acquisition",
                    "services": [
                        {
                            "service_id": "svc",
                            "priority": 1,
                            "landscape_type": lt,
                            "steps": [{"name": "s", "image": "img", "resource_class": "cpu"}],
                        }
                    ],
                }
            ],
        }
        result = _eval(payload)
        denies_about_landscape = [m for m in result["deny"] if "landscape" in m.lower()]
        assert denies_about_landscape == [], f"landscape_type={lt} should be accepted"


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
