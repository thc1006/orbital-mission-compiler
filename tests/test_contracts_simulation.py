"""Tests for simulation contracts (Phase 5.1).

These tests verify the INTERFACE definitions only — no simulation logic.
The contracts define what a future simulator would consume and produce.
References: ORCHIDE slide 7 (Ground Level: Simulation Framework),
            D3.1 §2.4.1.2 (Simulation Framework).
"""

import pytest
from pydantic import ValidationError


# ── Contract models must be importable ────────────────────────────────


def test_simulation_contracts_importable():
    """All simulation contract models must be importable from contracts.simulation."""
    from contracts.simulation import (
        AcquisitionReplayEvent,
        DownloadWindowEvent,
        WorkflowTrigger,
        SimulationTimeline,
        SimulationResult,
    )
    assert AcquisitionReplayEvent is not None
    assert DownloadWindowEvent is not None
    assert WorkflowTrigger is not None
    assert SimulationTimeline is not None
    assert SimulationResult is not None


# ── AcquisitionReplayEvent ────────────────────────────────────────────


def test_acquisition_replay_event():
    """AcquisitionReplayEvent carries event context for timeline replay."""
    from contracts.simulation import AcquisitionReplayEvent

    event = AcquisitionReplayEvent(
        timestamp="2029-10-06T00:23:00Z",
        orbit=1,
        instrument="INST_1",
        duration_seconds=4.0,
        detector_types=["ocean", "ocean", "land", "land"],
    )
    assert event.orbit == 1
    assert len(event.detector_types) == 4


def test_acquisition_replay_requires_instrument():
    """AcquisitionReplayEvent must have instrument."""
    from contracts.simulation import AcquisitionReplayEvent

    with pytest.raises(ValidationError):
        AcquisitionReplayEvent(
            timestamp="t",
            orbit=1,
            instrument=None,
            duration_seconds=4.0,
            detector_types=[],
        )


# ── DownloadWindowEvent ───────────────────────────────────────────────


def test_download_window_event():
    """DownloadWindowEvent represents a transmission opportunity."""
    from contracts.simulation import DownloadWindowEvent

    event = DownloadWindowEvent(
        timestamp="2029-10-06T01:58:00Z",
        orbit=2,
        duration_seconds=268.0,
        ground_station_id="GS-1",
    )
    assert event.duration_seconds == 268.0
    assert event.ground_station_id == "GS-1"


# ── WorkflowTrigger ──────────────────────────────────────────────────


def test_workflow_trigger():
    """WorkflowTrigger links an acquisition to the workflows it should produce."""
    from contracts.simulation import WorkflowTrigger

    trigger = WorkflowTrigger(
        acquisition_timestamp="2029-10-06T00:23:00Z",
        service_id="maritime-surveillance",
        priority=1,
        landscape_type="ocean",
        expected_phases=["preprocessing", "ai", "postprocessing"],
    )
    assert trigger.priority == 1
    assert len(trigger.expected_phases) == 3


# ── SimulationTimeline ────────────────────────────────────────────────


def test_simulation_timeline():
    """SimulationTimeline is a sequence of replay events and triggers."""
    from contracts.simulation import (
        AcquisitionReplayEvent,
        DownloadWindowEvent,
        WorkflowTrigger,
        SimulationTimeline,
    )

    timeline = SimulationTimeline(
        mission_id="sim-test",
        acquisitions=[
            AcquisitionReplayEvent(
                timestamp="t1", orbit=1, instrument="I1",
                duration_seconds=4.0, detector_types=["ocean"],
            ),
        ],
        downloads=[
            DownloadWindowEvent(
                timestamp="t2", orbit=2, duration_seconds=268.0,
                ground_station_id="GS-1",
            ),
        ],
        triggers=[
            WorkflowTrigger(
                acquisition_timestamp="t1", service_id="svc",
                priority=1, landscape_type="ocean",
                expected_phases=["preprocessing", "ai", "postprocessing"],
            ),
        ],
    )
    assert timeline.mission_id == "sim-test"
    assert len(timeline.acquisitions) == 1
    assert len(timeline.downloads) == 1
    assert len(timeline.triggers) == 1


# ── SimulationResult ─────────────────────────────────────────────────


def test_simulation_result():
    """SimulationResult is the contract for what a simulator would return."""
    from contracts.simulation import SimulationResult

    result = SimulationResult(
        mission_id="sim-test",
        total_acquisitions=5,
        total_downloads=2,
        workflows_triggered=8,
        data_volume_estimate_mb=1024.0,
        notes="Contract only — no simulation executed.",
    )
    assert result.workflows_triggered == 8
    assert "Contract" in result.notes
