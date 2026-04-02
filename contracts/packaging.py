"""Packaging contracts — ground-side application packaging interface definitions.

This module defines the DATA CONTRACTS for describing a packaged application
that would run inside an ORCHIDE-compatible workflow step. It does NOT
implement OCI image building, registry push, or deployment.

A ground-side packaging tool would produce a PackageManifest for each
application, which the mission plan compiler can reference when validating
workflow steps.

ORCHIDE references:
- D3.1 §2.4.1.1: "The ORCHIDE SDK must provide the necessary tools for
  building and packaging executable applications"
- D3.1 §5.1: "Application Builder — build applications as binary packages,
  such as MirageOS and Unikraft"
- D3.1 §5.1: "Integration with popular AI frameworks like TensorFlow"
- Slide 7: Ground Level → Software Development Kit
- Slide 10: Each AI Service = Pre-processing → AI → Post-processing
"""

from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


class ApplicationIdentity(BaseModel):
    """Identity of a packaged application.

    Maps to ORCHIDE D3.1 §5.1: each application has a name, version,
    and a container/unikernel image reference.
    """

    service_id: str
    version: str = ""
    image: str = ""
    description: str = ""

    @field_validator("service_id")
    @classmethod
    def service_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("service_id must not be empty")
        return v


class ApplicationInput(BaseModel):
    """Contract for a named data dependency consumed by an application.

    Maps to ORCHIDE slide 25 (end-to-end demo): applications read from
    shared filesystem paths provided by the Storage Manager.
    """

    name: str
    media_type: str = ""
    source_path: str = ""


class ApplicationOutput(BaseModel):
    """Contract for a named result artifact produced by an application.

    Maps to ORCHIDE slide 25: results are written to paths managed by
    the Storage Manager for downstream consumption or downlink.
    """

    name: str
    media_type: str = ""
    destination_path: str = ""


class RuntimePreference(BaseModel):
    """Contract for declaring resource and acceleration preferences.

    Maps to ORCHIDE slide 14 (hardware diversity: CPU/GPU/FPGA)
    and slide 18 (ukAccel accelerator mediation).
    """

    resource_class: str = "cpu"
    fallback_resource_class: Optional[str] = None
    needs_acceleration: bool = False
    min_memory_mb: int = 256
    min_cpu_millicores: int = 100


class PolicyHints(BaseModel):
    """Contract for policy constraints that the compiler should enforce.

    These hints inform the OPA policy pack (configs/policies/) about
    application-specific constraints beyond the mission plan schema.
    """

    max_execution_seconds: Optional[int] = None
    requires_ground_visibility: bool = False
    allowed_landscape_types: List[str] = Field(default_factory=list)


class PackageManifest(BaseModel):
    """Complete packaging manifest for a ground-side application.

    This is a CONTRACT — it describes what a packaged application looks like,
    not how to build one. A real packaging tool (or ORCHIDE's SDK Application
    Builder) would produce this manifest.

    The mission plan compiler can consume PackageManifests to:
    - Validate that workflow steps reference real, packaged applications
    - Check runtime preferences against available resource classes
    - Apply policy hints during plan compilation
    """

    identity: ApplicationIdentity
    phase: Optional[str] = None
    inputs: List[ApplicationInput] = Field(default_factory=list)
    outputs: List[ApplicationOutput] = Field(default_factory=list)
    runtime: RuntimePreference = Field(default_factory=RuntimePreference)
    policy: PolicyHints = Field(default_factory=PolicyHints)
