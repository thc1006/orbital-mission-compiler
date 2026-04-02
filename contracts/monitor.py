"""Monitor Manager contracts — interface definitions for metrics and logs.

This module defines DATA CONTRACTS only. It does NOT implement Vector,
OpenSearch, Prometheus, or Grafana. A real Monitor Manager would produce
and consume data conforming to these interfaces.

ORCHIDE references:
- Slide 20: Monitor Manager (Vector + API) on orchestrator node
- Slide 24: ORCHIDE Monitoring Setup (Vector → ground: OpenSearch + Prometheus)
- D3.1 §3.2.1.5: "Monitor Manager aggregates and stores monitoring files"
"""

from __future__ import annotations

from typing import Dict, Optional
from pydantic import BaseModel, Field


class MetricPoint(BaseModel):
    """Contract for a single metric data point."""

    name: str
    value: float
    labels: Dict[str, str] = Field(default_factory=dict)
    timestamp: str = ""


class LogEntry(BaseModel):
    """Contract for a structured log entry."""

    level: str = "info"
    message: str = ""
    service_id: Optional[str] = None
    step_name: Optional[str] = None
    timestamp: str = ""


class HealthStatus(BaseModel):
    """Contract for a component health check result."""

    component: str
    healthy: bool = True
    detail: str = ""
