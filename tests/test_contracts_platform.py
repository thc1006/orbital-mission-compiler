"""Tests for platform service contracts (Phase 5.3-5.6).

These tests verify INTERFACE DEFINITIONS only — no real EOS, Vector, Zot,
OpenSearch, or Prometheus adapters. Each contract defines what an
ORCHIDE-compatible platform service would expose.

References:
- Storage Manager: ORCHIDE slide 20, 22; D3.1 §3.2.1.2
- Monitor Manager: ORCHIDE slide 20, 24; D3.1 §3.2.1.5
- Communication Manager: ORCHIDE slide 20; D3.1 §3.2.1.1.3
- Security Manager: ORCHIDE slide 20; D3.1 §3.2.1.4
"""

import pytest
from pydantic import ValidationError


# ── Storage Manager (D3.1 §3.2.1.2) ─────────────────────────────────


def test_storage_contracts_importable():
    from contracts.storage import (
        FileRegistration,
        FileQuery,
        FileRecord,
    )
    assert FileRegistration is not None
    assert FileQuery is not None
    assert FileRecord is not None


def test_file_registration():
    from contracts.storage import FileRegistration

    reg = FileRegistration(
        filename="scene_001.tiff",
        media_type="image/tiff",
        source="camera-acquisition",
        size_bytes=10_485_760,
    )
    assert reg.size_bytes == 10_485_760


def test_file_query():
    from contracts.storage import FileQuery

    q = FileQuery(source="camera-acquisition", media_type="image/tiff")
    assert q.source == "camera-acquisition"


def test_file_record():
    from contracts.storage import FileRecord

    rec = FileRecord(
        filename="scene_001.tiff",
        media_type="image/tiff",
        source="camera-acquisition",
        size_bytes=10_485_760,
        path="/data/raw/scene_001.tiff",
        registered_at="2029-10-06T00:23:05Z",
    )
    assert rec.path.startswith("/data/")


# ── Monitor Manager (D3.1 §3.2.1.5) ─────────────────────────────────


def test_monitor_contracts_importable():
    from contracts.monitor import (
        MetricPoint,
        LogEntry,
        HealthStatus,
    )
    assert MetricPoint is not None
    assert LogEntry is not None
    assert HealthStatus is not None


def test_metric_point():
    from contracts.monitor import MetricPoint

    m = MetricPoint(
        name="workflow_duration_seconds",
        value=12.5,
        labels={"service_id": "maritime-surveillance", "phase": "ai"},
        timestamp="2029-10-06T00:23:10Z",
    )
    assert m.value == 12.5


def test_log_entry():
    from contracts.monitor import LogEntry

    log = LogEntry(
        level="info",
        message="Workflow step completed",
        service_id="fire-detection",
        step_name="detect-fire",
        timestamp="2029-10-06T00:25:00Z",
    )
    assert log.level == "info"


def test_health_status():
    from contracts.monitor import HealthStatus

    status = HealthStatus(
        component="storage-manager",
        healthy=True,
        detail="EOS filesystem mounted",
    )
    assert status.healthy is True


# ── Communication Manager (D3.1 §3.2.1.1.3) ─────────────────────────


def test_communication_contracts_importable():
    from contracts.communication import (
        DownlinkRequest,
        UplinkAck,
    )
    assert DownlinkRequest is not None
    assert UplinkAck is not None


def test_downlink_request():
    from contracts.communication import DownlinkRequest

    req = DownlinkRequest(
        filename="results_001.json",
        priority=1,
        ground_station_id="GS-1",
        estimated_size_bytes=1024,
    )
    assert req.priority == 1


def test_uplink_ack():
    from contracts.communication import UplinkAck

    ack = UplinkAck(
        mission_plan_id="mission-orchide-demo",
        received_at="2029-10-06T00:00:00Z",
        status="accepted",
    )
    assert ack.status == "accepted"


def test_uplink_ack_rejects_invalid_status():
    from contracts.communication import UplinkAck

    with pytest.raises(ValidationError):
        UplinkAck(
            mission_plan_id="test",
            received_at="t",
            status="maybe",
        )


# ── Security Manager (D3.1 §3.2.1.4) ────────────────────────────────


def test_security_contracts_importable():
    from contracts.security import (
        AuthToken,
        IntegrityCheck,
    )
    assert AuthToken is not None
    assert IntegrityCheck is not None


def test_auth_token():
    from contracts.security import AuthToken

    token = AuthToken(
        subject="satellite-owner",
        scope="mission-plan-deploy",
        issued_at="2029-10-06T00:00:00Z",
        expires_at="2029-10-06T01:00:00Z",
    )
    assert token.scope == "mission-plan-deploy"


def test_integrity_check():
    from contracts.security import IntegrityCheck

    check = IntegrityCheck(
        artifact="ghcr.io/example/fire-detector:1.0.0",
        algorithm="sha256",
        digest="abc123def456",
        verified=True,
    )
    assert check.verified is True
