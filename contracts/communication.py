"""Communication Manager contracts — interface definitions for data transfer.

This module defines DATA CONTRACTS only. It does NOT implement satellite-to-ground
communication protocols. The transmission mechanism is external to ORCHIDE
(D3.1 §2.4.1: "this transmission mechanism is external to the ORCHIDE solution").

ORCHIDE references:
- Slide 20: Communication Manager on orchestrator node
- D3.1 §3.2.1.1.3: Communication Manager
- D3.1 §2.4.1: Transmission mechanism is external to ORCHIDE
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel


class UplinkStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PENDING = "pending"


class DownlinkRequest(BaseModel):
    """Contract for requesting a file to be transmitted to ground."""

    filename: str
    priority: int = 1
    ground_station_id: str = ""
    estimated_size_bytes: int = 0


class UplinkAck(BaseModel):
    """Contract for acknowledging receipt of an uplinked mission plan."""

    mission_plan_id: str
    received_at: str = ""
    status: UplinkStatus = UplinkStatus.PENDING
