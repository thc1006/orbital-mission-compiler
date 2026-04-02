"""Storage Manager contracts — interface definitions for file management.

This module defines DATA CONTRACTS only. It does NOT implement EOS, Zot,
or any real distributed filesystem. A real Storage Manager (ORCHIDE's or
a ground-side equivalent) would implement these interfaces.

ORCHIDE references:
- Slide 20: Storage Manager (Zot + EOS) on orchestrator node
- Slide 22: ORCHIDE Storage Manager Architecture (FUSE mounts, file registration)
- D3.1 §3.2.1.2: "Storage Manager keeps track of files"
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel


class FileRegistration(BaseModel):
    """Contract for registering a file with the Storage Manager."""

    filename: str
    media_type: str = ""
    source: str = ""
    size_bytes: int = 0


class FileQuery(BaseModel):
    """Contract for querying files by source or type."""

    source: Optional[str] = None
    media_type: Optional[str] = None


class FileRecord(BaseModel):
    """Contract for a file record returned by the Storage Manager."""

    filename: str
    media_type: str = ""
    source: str = ""
    size_bytes: int = 0
    path: str = ""
    registered_at: str = ""
