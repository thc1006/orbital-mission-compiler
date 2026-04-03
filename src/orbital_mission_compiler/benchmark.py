"""Benchmark utilities for the satellite mission compiler.

Provides synthetic mission plan generation used by the scaling
benchmark script and its tests.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

_BASE_TIME = datetime(2026, 4, 15, tzinfo=timezone.utc)


def generate_synthetic_plan(n_events: int) -> dict[str, Any]:
    """Generate a synthetic mission plan with n_events acquisition events.

    Each event has 1 service with 3 steps (preprocess/detect/postprocess),
    CPU-only resource class, busybox:1.36 image. All events use
    landscape_type=ocean and priority=50 to pass OPA policy.

    Args:
        n_events: Number of acquisition events to generate.

    Returns:
        A dict suitable for MissionPlan.model_validate().
    """
    events = []
    for i in range(n_events):
        timestamp = (_BASE_TIME + timedelta(seconds=i)).strftime("%Y-%m-%dT%H:%M:%SZ")
        events.append(
            {
                "timestamp": timestamp,
                "event_type": "acquisition",
                "orbit": i + 1,
                "instrument": f"sensor-{i}",
                "services": [
                    {
                        "service_id": f"svc-{i}",
                        "priority": 50,
                        "landscape_type": "ocean",
                        "steps": [
                            {
                                "name": "preprocess",
                                "image": "busybox:1.36",
                                "resource_class": "cpu",
                            },
                            {
                                "name": "detect",
                                "image": "busybox:1.36",
                                "resource_class": "cpu",
                            },
                            {
                                "name": "postprocess",
                                "image": "busybox:1.36",
                                "resource_class": "cpu",
                            },
                        ],
                    }
                ],
            }
        )
    return {
        "mission_id": f"bench-{n_events}",
        "client_id": "benchmark",
        "events": events,
    }
