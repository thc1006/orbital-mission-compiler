"""Security Manager contracts — interface definitions for auth and integrity.

This module defines DATA CONTRACTS only. It does NOT implement encryption,
certificate management, or runtime security enforcement.

ORCHIDE references:
- Slide 20: Security Manager on orchestrator node
- D3.1 §3.2.1.4: "Security Manager ensures on-satellite security posture"
- D3.1 §3.2.1.4: Responsibilities include encryption and authentication
"""

from __future__ import annotations

from pydantic import BaseModel


class AuthToken(BaseModel):
    """Contract for an authentication/authorization token."""

    subject: str
    scope: str = ""
    issued_at: str = ""
    expires_at: str = ""


class IntegrityCheck(BaseModel):
    """Contract for verifying artifact integrity (image signature, checksum)."""

    artifact: str
    algorithm: str = "sha256"
    digest: str = ""
    verified: bool = False
