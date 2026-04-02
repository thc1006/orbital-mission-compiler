"""Simulation contracts — interface definitions for mission timeline replay.

This module defines the DATA CONTRACTS only. It does NOT implement a simulator.
A future simulator (or ORCHIDE's Simulation Framework) would consume and produce
data conforming to these interfaces.

ORCHIDE references:
- Slide 7: Ground Level → Simulation Framework
- D3.1 §2.4.1.2: "The Simulation Framework allows to test in a simulated environment"
- D3.1 §2.4.1.2: Supports feasibility analysis during design phase
                   and dynamic configuration during operating phase
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


class AcquisitionReplayEvent(BaseModel):
    """Contract for replaying a satellite acquisition event in simulation.

    Maps to ORCHIDE slide 9: one row where EV=ACQ.
    """

    timestamp: str
    orbit: int
    instrument: str
    duration_seconds: float
    detector_types: List[str] = Field(default_factory=list)
    ground_visibility: bool = False
    region_type: Optional[str] = None


class DownloadWindowEvent(BaseModel):
    """Contract for replaying a transmission window in simulation.

    Maps to ORCHIDE slide 9: one row where EV=DOWNLOAD.
    """

    timestamp: str
    orbit: int = 0
    duration_seconds: float
    ground_station_id: str = ""
    ground_visibility: bool = True


class WorkflowTrigger(BaseModel):
    """Contract for linking an acquisition to its expected workflow invocations.

    Maps to ORCHIDE slide 9: WORKFLOW_D1-D4 columns + slide 10 pipeline.
    """

    acquisition_timestamp: str
    service_id: str
    priority: int
    landscape_type: Optional[str] = None
    expected_phases: List[str] = Field(default_factory=list)


class SimulationTimeline(BaseModel):
    """Contract for a complete mission timeline used in simulation.

    A simulator would consume this to replay mission events in order.
    """

    mission_id: str
    acquisitions: List[AcquisitionReplayEvent] = Field(default_factory=list)
    downloads: List[DownloadWindowEvent] = Field(default_factory=list)
    triggers: List[WorkflowTrigger] = Field(default_factory=list)


class SimulationResult(BaseModel):
    """Contract for what a simulator would return after a timeline replay.

    This is a PLACEHOLDER contract. A real simulator would produce
    richer output (resource utilization, timing analysis, etc.).
    """

    mission_id: str
    total_acquisitions: int = 0
    total_downloads: int = 0
    workflows_triggered: int = 0
    data_volume_estimate_mb: float = 0.0
    notes: str = "Contract only — no simulation executed."
