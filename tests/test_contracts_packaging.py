"""Tests for packaging contracts (Phase 5.2).

These tests verify INTERFACE DEFINITIONS only — no OCI build or deployment.
The contracts describe what a ground-side packaging tool would consume.
References: ORCHIDE D3.1 §2.4.1.1 (SDK), §5.1 (Application Builder).
"""

import pytest
from pydantic import ValidationError


def test_packaging_contracts_importable():
    """All packaging contract models must be importable."""
    from contracts.packaging import (
        ApplicationIdentity,
        ApplicationInput,
        ApplicationOutput,
        RuntimePreference,
        PolicyHints,
        PackageManifest,
    )


# ── ApplicationIdentity ──────────────────────────────────────────────


def test_application_identity():
    """ApplicationIdentity carries service/version/image metadata."""
    from contracts.packaging import ApplicationIdentity

    ident = ApplicationIdentity(
        service_id="maritime-surveillance",
        version="0.1.0",
        image="ghcr.io/example/ship-detector:0.1.0",
    )
    assert ident.service_id == "maritime-surveillance"
    assert ident.version == "0.1.0"


def test_application_identity_requires_service_id():
    from contracts.packaging import ApplicationIdentity

    with pytest.raises(ValidationError):
        ApplicationIdentity(service_id="", version="0.1.0", image="img")


# ── ApplicationInput / Output ────────────────────────────────────────


def test_application_input():
    """ApplicationInput describes a named data dependency."""
    from contracts.packaging import ApplicationInput

    inp = ApplicationInput(
        name="raw-image",
        media_type="image/tiff",
        source_path="/data/raw",
    )
    assert inp.media_type == "image/tiff"


def test_application_output():
    """ApplicationOutput describes a named result artifact."""
    from contracts.packaging import ApplicationOutput

    out = ApplicationOutput(
        name="detection-result",
        media_type="application/json",
        destination_path="/data/results",
    )
    assert out.destination_path == "/data/results"


# ── RuntimePreference ─────────────────────────────────────────────────


def test_runtime_preference():
    """RuntimePreference declares resource class and acceleration intent."""
    from contracts.packaging import RuntimePreference

    pref = RuntimePreference(
        resource_class="gpu",
        fallback_resource_class="cpu",
        needs_acceleration=True,
        min_memory_mb=512,
        min_cpu_millicores=1000,
    )
    assert pref.resource_class == "gpu"
    assert pref.fallback_resource_class == "cpu"


def test_runtime_preference_defaults():
    """RuntimePreference has sensible defaults."""
    from contracts.packaging import RuntimePreference

    pref = RuntimePreference()
    assert pref.resource_class == "cpu"
    assert pref.needs_acceleration is False


# ── PolicyHints ───────────────────────────────────────────────────────


def test_policy_hints():
    """PolicyHints declare constraints the policy engine should check."""
    from contracts.packaging import PolicyHints

    hints = PolicyHints(
        max_execution_seconds=300,
        requires_ground_visibility=False,
        allowed_landscape_types=["ocean", "land"],
    )
    assert hints.max_execution_seconds == 300
    assert "ocean" in hints.allowed_landscape_types


# ── PackageManifest (full assembly) ──────────────────────────────────


def test_package_manifest():
    """PackageManifest assembles all packaging contract pieces."""
    from contracts.packaging import (
        PackageManifest,
        ApplicationIdentity,
        ApplicationInput,
        ApplicationOutput,
        RuntimePreference,
        PolicyHints,
    )

    manifest = PackageManifest(
        identity=ApplicationIdentity(
            service_id="fire-detection",
            version="1.0.0",
            image="ghcr.io/example/fire-detector:1.0.0",
        ),
        phase="ai",
        inputs=[
            ApplicationInput(name="preprocessed", media_type="image/tiff", source_path="/data/prepared"),
        ],
        outputs=[
            ApplicationOutput(name="detections", media_type="application/json", destination_path="/data/results"),
        ],
        runtime=RuntimePreference(resource_class="gpu", needs_acceleration=True),
        policy=PolicyHints(max_execution_seconds=120, allowed_landscape_types=["land"]),
    )
    assert manifest.identity.service_id == "fire-detection"
    assert manifest.phase == "ai"
    assert len(manifest.inputs) == 1
    assert len(manifest.outputs) == 1
    assert manifest.runtime.resource_class == "gpu"


def test_package_manifest_minimal():
    """PackageManifest works with only required fields."""
    from contracts.packaging import PackageManifest, ApplicationIdentity

    manifest = PackageManifest(
        identity=ApplicationIdentity(
            service_id="preprocess",
            version="0.1.0",
            image="ghcr.io/example/preprocess:0.1.0",
        ),
    )
    assert manifest.inputs == []
    assert manifest.outputs == []
    assert manifest.phase is None


# ── Negative validation (Copilot review fixes) ──────────────────────


def test_reject_negative_memory():
    from contracts.packaging import RuntimePreference

    with pytest.raises(ValidationError):
        RuntimePreference(min_memory_mb=-1)


def test_reject_negative_execution_seconds():
    from contracts.packaging import PolicyHints

    with pytest.raises(ValidationError):
        PolicyHints(max_execution_seconds=-10)


def test_reject_invalid_resource_class():
    from contracts.packaging import RuntimePreference

    with pytest.raises(ValidationError):
        RuntimePreference(resource_class="quantum")


def test_reject_invalid_phase():
    from contracts.packaging import PackageManifest, ApplicationIdentity

    with pytest.raises(ValidationError):
        PackageManifest(
            identity=ApplicationIdentity(service_id="test", version="1.0", image="img"),
            phase="launch",
        )


# ── Sample manifest file ─────────────────────────────────────────────


def test_sample_package_manifest_exists_and_loads():
    """A sample package manifest YAML must exist and load into PackageManifest."""
    from pathlib import Path
    import yaml
    from contracts.packaging import PackageManifest

    path = Path("configs/samples/sample_package_manifest.yaml")
    assert path.exists(), "sample manifest file must exist"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    manifest = PackageManifest(**data)
    assert manifest.identity.service_id != ""
