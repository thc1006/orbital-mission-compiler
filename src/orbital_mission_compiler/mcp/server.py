from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, cast

try:
    from fastmcp import FastMCP
except ImportError:
    FastMCP = None  # type: ignore[assignment,misc]

from orbital_mission_compiler.compiler import (
    load_mission_plan,
    compile_plan_to_intents,
    write_individual_workflows,
)
from orbital_mission_compiler.policy import eval_policy

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ALLOWED_PLANS = (_REPO_ROOT / "configs" / "mission_plans").resolve()
_ALLOWED_BUNDLES = (_REPO_ROOT / "configs" / "policies").resolve()


def _is_within(child: Path, parent: Path) -> bool:
    """Check if child path is within or equal to parent directory."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _validate_plan_path(path: str) -> Path:
    """Validate plan path is a filename within configs/mission_plans/. CWE-22 prevention."""
    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Path outside allowed directory: {path}")
    # Only accept bare filenames — reject paths with directory components
    if candidate != Path(candidate.name):
        raise ValueError(f"Path outside allowed directory: {path}")
    resolved = (_ALLOWED_PLANS / candidate.name).resolve()
    if not _is_within(resolved, _ALLOWED_PLANS):
        raise ValueError(f"Path outside allowed directory: {path}")
    if not resolved.exists():
        raise ValueError(f"Plan file not found: {path}")
    return resolved


def _validate_bundle_path(bundle: str) -> Path:
    """Validate bundle path is within configs/policies/. CWE-22 prevention."""
    candidate = Path(bundle)
    # Resolve relative paths against _REPO_ROOT (CWD-independent)
    if not candidate.is_absolute():
        resolved = (_REPO_ROOT / candidate).resolve()
    else:
        resolved = candidate.resolve()
    if not _is_within(resolved, _ALLOWED_BUNDLES):
        raise ValueError(f"Bundle path outside allowed directory: {bundle}")
    return resolved


def build_server() -> Any:
    if FastMCP is None:
        raise RuntimeError(
            "fastmcp is not installed. Install optional extras with: pip install -e '.[mcp]'"
        )

    server = FastMCP("orbital-mission-compiler")

    @server.tool
    def validate_plan(path: str) -> dict[str, Any]:
        safe_path = _validate_plan_path(path)
        plan = load_mission_plan(safe_path)
        return {"mission_id": plan.mission_id, "events": len(plan.events), "status": "validated"}

    @server.tool
    def compile_plan(path: str) -> dict[str, Any]:
        safe_path = _validate_plan_path(path)
        plan = load_mission_plan(safe_path)
        intents = compile_plan_to_intents(plan)
        return {
            "mission_id": plan.mission_id,
            "intent_count": len(intents),
            "services": [intent.service_id for intent in intents],
        }

    @server.tool
    def render_argo(path: str) -> dict[str, Any]:
        safe_path = _validate_plan_path(path)
        with tempfile.TemporaryDirectory() as tmpdir:
            files = write_individual_workflows(safe_path, tmpdir)
            return {"files": [f.name for f in files], "count": len(files)}

    @server.tool
    def explain_policy(
        path: str, bundle: str = "configs/policies", decision: str = "data.orbitalmission"
    ) -> dict[str, Any]:
        safe_path = _validate_plan_path(path)
        safe_bundle = _validate_bundle_path(bundle)
        plan = load_mission_plan(safe_path)
        rc, out = eval_policy(str(safe_bundle), plan.model_dump(mode="json"), decision)
        return {"exit_code": rc, "raw": out}

    @server.tool
    def diff_plans(path_a: str, path_b: str) -> dict[str, Any]:
        """Structural diff of two mission plans."""
        plan_a = load_mission_plan(_validate_plan_path(path_a))
        plan_b = load_mission_plan(_validate_plan_path(path_b))

        services_a = {
            svc.service_id for ev in plan_a.events for svc in ev.services
        }
        services_b = {
            svc.service_id for ev in plan_b.events for svc in ev.services
        }
        return {
            "mission_a": plan_a.mission_id,
            "mission_b": plan_b.mission_id,
            "events_a": len(plan_a.events),
            "events_b": len(plan_b.events),
            "added_services": sorted(services_b - services_a),
            "removed_services": sorted(services_a - services_b),
            "common_services": sorted(services_a & services_b),
        }

    @server.tool
    def check_timeline_conflicts(path: str) -> dict[str, Any]:
        """Detect overlapping acquisition windows in a mission plan."""
        from datetime import datetime, timezone

        plan = load_mission_plan(_validate_plan_path(path))
        acq_events = []
        skipped = []
        for ev in plan.events:
            if ev.event_type.value != "acquisition":
                continue
            try:
                ts = datetime.fromisoformat(ev.timestamp.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
            except ValueError:
                skipped.append(ev.timestamp)
                continue
            if ev.duration_seconds is None:
                skipped.append(ev.timestamp)
                continue
            duration = ev.duration_seconds
            acq_events.append({
                "timestamp": ev.timestamp,
                "start": ts.timestamp(),
                "end": ts.timestamp() + duration,
            })

        conflicts = []
        for i in range(len(acq_events)):
            for j in range(i + 1, len(acq_events)):
                a, b = acq_events[i], acq_events[j]
                max_start = max(cast(float, a["start"]), cast(float, b["start"]))
                min_end = min(cast(float, a["end"]), cast(float, b["end"]))
                if max_start < min_end:
                    conflicts.append({
                        "event_a": a["timestamp"],
                        "event_b": b["timestamp"],
                        "overlap_seconds": round(min_end - max_start, 2),
                    })

        return {
            "conflicts": conflicts,
            "conflict_count": len(conflicts),
            "skipped_timestamps": skipped,
        }

    return server


def main() -> None:
    server = build_server()
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    server.run(transport=transport)


if __name__ == "__main__":
    main()
