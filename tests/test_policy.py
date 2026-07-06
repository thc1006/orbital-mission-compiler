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


def test_deny_missing_mission_id():
    payload = {
        "events": [{"timestamp": "t", "event_type": "download"}],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("mission_id must not be empty" in m for m in result["deny"])


def test_deny_null_mission_id():
    payload = {
        "mission_id": None,
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


def test_deny_gpu_no_fallback_without_flag():
    """Regression: a GPU step must declare a fallback even when
    needs_acceleration is omitted (it defaults to false). If Rule 4 gated on
    the flag, a GPU step could silently bypass the fallback requirement."""
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
                                # needs_acceleration intentionally omitted
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


def test_deny_fpga_no_fallback():
    """FPGA is an accelerator class; an FPGA step without a fallback must be
    denied by Rule 4, matching the paper's 'any accelerator-requesting step'."""
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
                                "name": "fpga-step",
                                "image": "example:latest",
                                "resource_class": "fpga",
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


def test_allow_gpu_with_fallback_without_flag():
    """A GPU step that declares a fallback is safe even without the
    needs_acceleration flag: Rule 4 must not fire."""
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
                                "fallback_resource_class": "cpu",
                            }
                        ],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    fallback_denies = [m for m in result["deny"] if "fallback_resource_class" in m]
    assert fallback_denies == [], "GPU step with fallback must not trigger Rule 4"


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


def test_allow_null_landscape_type():
    """An explicit null landscape_type is permitted: the field is optional, and
    Rule 10 must not treat Rego null-truthiness as a present invalid value."""
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
                        "landscape_type": None,
                        "steps": [{"name": "s", "image": "img", "resource_class": "cpu"}],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    landscape_denies = [m for m in result["deny"] if "landscape" in m.lower()]
    assert landscape_denies == [], f"null landscape_type must be permitted: {landscape_denies}"


def test_allow_omitted_landscape_type_via_model_dump():
    """Regression on the real compiler path: an omitted Optional landscape_type
    is Pydantic-normalized to JSON null. Because null is truthy in Rego, a naive
    guard would deny every plan that omits the field (three shipped samples,
    including the paper's Listing 1). Rule 10 must permit it."""
    from orbital_mission_compiler.schemas import MissionPlan

    plan = MissionPlan.model_validate(
        {
            "mission_id": "test",
            "events": [
                {
                    "timestamp": "2026-04-15T10:00:00Z",
                    "event_type": "acquisition",
                    "instrument": "cam",
                    "services": [
                        {
                            "service_id": "svc",
                            "priority": 50,
                            # landscape_type intentionally omitted -> normalized to null
                            "steps": [{"name": "s", "image": "img", "resource_class": "cpu"}],
                        }
                    ],
                }
            ],
        }
    )
    result = _eval(plan.model_dump(mode="json"))
    landscape_denies = [m for m in result["deny"] if "landscape" in m.lower()]
    assert landscape_denies == [], f"omitted landscape_type must be permitted: {landscape_denies}"


def test_deny_non_string_landscape_raw_bypass():
    """Defense-in-depth: on the raw-JSON schema-bypass path, a PRESENT
    non-string landscape_type is also an unrecognized value and must be denied.
    Pydantic rejects non-strings at Stage 1, so this is only reachable when raw
    JSON is fed directly to OPA; the policy layer stays a complete redundant
    checker for landscape validity on that path."""
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
                        "landscape_type": 42,  # non-string, bypasses the schema
                        "steps": [{"name": "s", "image": "img", "resource_class": "cpu"}],
                    }
                ],
            }
        ],
    }
    result = _eval(payload)
    assert result["allow"] is False
    assert any("non-string landscape_type" in m for m in result["deny"])


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
