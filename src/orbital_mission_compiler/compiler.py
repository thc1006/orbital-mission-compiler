from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml

from .schemas import MissionPlan, WorkflowIntent, ResourceClass, WorkflowStep

logger = logging.getLogger(__name__)


def sanitize_k8s_name(name: str, max_len: int = 63) -> str:
    """Sanitize a string to be a valid RFC 1123 DNS label (K8s container/resource name)."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s[:max_len].rstrip("-") or "step"


def _collision_resistant_k8s_name(name: str, max_len: int = 63, hash_len: int = 8) -> str:
    """Sanitize and preserve uniqueness when truncation is required."""
    if max_len < hash_len + 2:
        raise ValueError(f"max_len={max_len} too small for hash_len={hash_len}")
    normalized = sanitize_k8s_name(name, max_len=253)
    if len(normalized) <= max_len:
        return normalized
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:hash_len]
    head = normalized[: max_len - hash_len - 1].rstrip("-")
    if not head:
        head = "step"
    return f"{head}-{digest}"


def _to_rfc3339_z(ts: datetime) -> str:
    """Serialize a datetime to RFC3339 using Z for UTC when possible."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    text = ts.isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def scale_priority_orchide(priority: int) -> int:
    """Convert 0-100 priority to ORCHIDE 1-4 scale (1=highest).

    ORCHIDE slide 9 uses 1-4; the schema uses 0-100 (higher=higher).
    Mapping: 76-100→1, 51-75→2, 26-50→3, 1-25→4.
    Priority 0 is rejected (OPA rule 5 treats it as misconfiguration).
    """
    if priority < 0 or priority > 100:
        raise ValueError(f"priority {priority} out of range 0-100")
    if priority == 0:
        raise ValueError("priority 0 is a misconfiguration (ORCHIDE uses 1-4)")
    if priority >= 76:
        return 1
    if priority >= 51:
        return 2
    if priority >= 26:
        return 3
    return 4


def load_mission_plan(path: str | Path) -> MissionPlan:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return MissionPlan.model_validate(raw)


def analyze_timeline_conflicts(plan: MissionPlan) -> dict[str, Any]:
    """Detect overlapping acquisition windows and report skipped timestamps.

    Pairwise comparison is O(n^2) in acquisition events. For plans with
    hundreds of events, consider sorting by start time first (future optimization).
    """
    acq_events = []
    skipped = []

    for ev in plan.events:
        if ev.event_type.value != "acquisition":
            continue
        if ev.duration_seconds is None:
            ts_text = _to_rfc3339_z(ev.timestamp)
            logger.debug("Skipping event without duration_seconds: %s (plan: %s)", ts_text, plan.mission_id)
            skipped.append(ts_text)
            continue
        start = ev.timestamp.timestamp()
        ts_text = _to_rfc3339_z(ev.timestamp)
        acq_events.append({
            "timestamp": ts_text,
            "start": start,
            "end": start + ev.duration_seconds,
        })

    conflicts: list[dict[str, Any]] = []
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


def detect_timeline_conflicts(plan: MissionPlan) -> list[dict[str, Any]]:
    """Detect overlapping acquisition windows in a mission plan."""
    return cast(list[dict[str, Any]], analyze_timeline_conflicts(plan)["conflicts"])


def compile_plan_to_intents(
    plan: MissionPlan,
    check_conflicts: bool = False,
) -> list[WorkflowIntent]:
    if check_conflicts:
        conflicts = detect_timeline_conflicts(plan)
        for c in conflicts[:10]:
            logger.warning(
                "Timeline conflict: %s overlaps with %s by %.1fs",
                c["event_a"], c["event_b"], c["overlap_seconds"],
            )
        if len(conflicts) > 10:
            logger.warning("... and %d more conflicts (total: %d)", len(conflicts) - 10, len(conflicts))
    intents: list[WorkflowIntent] = []
    skipped = 0
    for event in plan.events:
        if event.event_type.value != "acquisition":
            skipped += 1
            logger.info(
                "Skipping %s event at %s (only acquisition events produce workflow intents)",
                event.event_type.value,
                event.timestamp,
            )
            continue
        for svc in event.services:
            gpu_steps = [s for s in svc.steps if s.resource_class == ResourceClass.GPU]
            fpga_steps = [s for s in svc.steps if s.resource_class == ResourceClass.FPGA]
            fallback_steps = [s for s in svc.steps if s.fallback_resource_class is not None]
            event_timestamp = _to_rfc3339_z(event.timestamp)
            hints = {
                "event_timestamp": event_timestamp,
                "ground_visibility": event.ground_visibility,
                "region_type": event.region_type,
                "orbit": event.orbit,
                "duration_seconds": event.duration_seconds,
                "landscape_type": svc.landscape_type,
                "execution_mode": svc.execution_mode.value,
                "requires_gpu": bool(gpu_steps),
                "requires_fpga": bool(fpga_steps),
                "fallback_enabled": bool(fallback_steps),
            }
            intents.append(
                WorkflowIntent(
                    mission_id=plan.mission_id,
                    service_id=svc.service_id,
                    priority=svc.priority,
                    workflow_name=_collision_resistant_k8s_name(
                        f"{plan.mission_id}-{svc.service_id}-{event_timestamp}"
                    ),
                    steps=svc.steps,
                    resource_hints=hints,
                )
            )
    logger.info(
        "Compiled %d intents from %d events (%d skipped)",
        len(intents),
        len(plan.events),
        skipped,
    )
    return intents


def _preferred_affinity(step: WorkflowStep) -> dict[str, Any] | None:
    if not step.preferred_node_selector:
        return None
    expressions = [
        {"key": key, "operator": "In", "values": [value]}
        for key, value in step.preferred_node_selector.items()
    ]
    return {
        "nodeAffinity": {
            "preferredDuringSchedulingIgnoredDuringExecution": [
                {
                    "weight": 100,
                    "preference": {"matchExpressions": expressions},
                }
            ]
        }
    }


def render_argo_workflow(intent: WorkflowIntent) -> dict[str, Any]:
    templates = []
    dag_tasks = []
    for idx, step in enumerate(intent.steps):
        template_name = f"step-{idx}-{sanitize_k8s_name(step.name)}"
        annotations: dict[str, str] = {
            "resource-class": step.resource_class.value,
            "needs-acceleration": str(step.needs_acceleration).lower(),
        }
        if step.phase is not None:
            annotations["phase"] = step.phase.value

        template: dict[str, Any] = {
            "name": template_name,
            "container": {
                "image": step.image,
                "command": step.command or ["sh", "-c"],
                "args": step.args or [f'echo "run {step.name}"'],
                "env": [
                    {"name": "ORBITAL_RESOURCE_CLASS", "value": step.resource_class.value},
                    {
                        "name": "ORBITAL_NEEDS_ACCELERATION",
                        "value": str(step.needs_acceleration).lower(),
                    },
                ],
            },
            "metadata": {
                "annotations": annotations,
            },
        }
        if step.fallback_resource_class is not None:
            template["container"]["env"].append(
                {
                    "name": "ORBITAL_FALLBACK_RESOURCE_CLASS",
                    "value": step.fallback_resource_class.value,
                }
            )
            template["metadata"]["annotations"]["fallback-resource-class"] = step.fallback_resource_class.value
        affinity = _preferred_affinity(step)
        if affinity:
            template["affinity"] = affinity
        templates.append(template)

        safe_name = sanitize_k8s_name(template_name)
        dag_task: dict[str, Any] = {"name": safe_name, "template": template_name}
        dag_tasks.append(dag_task)

    # Apply DAG dependencies based on execution_mode.
    # Sequential: linear chain (A→B→C). Parallel: no dependencies.
    # Unknown values raise ValueError (fail-closed for safety-critical contexts).
    execution_mode = intent.resource_hints.get("execution_mode", "sequential")
    if execution_mode not in ("sequential", "parallel"):
        raise ValueError(f"Unknown execution_mode {execution_mode!r}; expected 'sequential' or 'parallel'")
    if execution_mode == "sequential":
        for i in range(1, len(dag_tasks)):
            dag_tasks[i]["depends"] = dag_tasks[i - 1]["name"]

    wf_annotations: dict[str, str] = {
        "orbital/priority": str(intent.priority),
        "orbital/orchide-priority": str(scale_priority_orchide(intent.priority)),
        "orbital/execution-mode": execution_mode,
        "orbital/requires-gpu": str(intent.resource_hints.get("requires_gpu", False)).lower(),
        "orbital/requires-fpga": str(intent.resource_hints.get("requires_fpga", False)).lower(),
        "orbital/fallback-enabled": str(intent.resource_hints.get("fallback_enabled", False)).lower(),
    }

    workflow = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "name": sanitize_k8s_name(intent.workflow_name),
            "labels": {
                "mission-id": sanitize_k8s_name(intent.mission_id),
                "service-id": sanitize_k8s_name(intent.service_id),
                "priority": str(intent.priority),
            },
            "annotations": wf_annotations,
        },
        "spec": {
            "entrypoint": "main",
            "templates": [{"name": "main", "dag": {"tasks": dag_tasks}}, *templates],
        },
    }
    return workflow


def _rct_name_for_intent(intent: WorkflowIntent, device: str) -> str:
    """Deterministic ResourceClaimTemplate name for a given intent and device type."""
    return sanitize_k8s_name(f"{intent.workflow_name}-{device}-claim", max_len=62)


def render_resource_claim_templates(
    intent: WorkflowIntent,
    namespace: str = "orbital-demo",
) -> list[dict[str, Any]]:
    """Render DRA ResourceClaimTemplates for accelerator steps.

    GPU steps produce a ResourceClaimTemplate with deviceClassName gpu.nvidia.com.
    FPGA steps produce nothing (no DRA driver available as of 2026-04).
    CPU steps produce nothing.
    """
    templates: list[dict[str, Any]] = []
    requires_gpu = intent.resource_hints.get("requires_gpu", False)
    if requires_gpu:
        templates.append({
            "apiVersion": "resource.k8s.io/v1",
            "kind": "ResourceClaimTemplate",
            "metadata": {
                "name": _rct_name_for_intent(intent, "gpu"),
                "namespace": namespace,
            },
            "spec": {
                "spec": {
                    "devices": {
                        "requests": [
                            {
                                "name": "gpu",
                                "exactly": {
                                    "deviceClassName": "gpu.nvidia.com",
                                },
                            }
                        ],
                    },
                },
            },
        })
    return templates


def render_kueue_job(
    intent: WorkflowIntent,
    queue_name: str = "orbital-demo-local",
    namespace: str = "orbital-demo",
    cpu_request: str = "1",
    memory_request: str = "256Mi",
    dra_enabled: bool = True,
) -> dict[str, Any]:
    if not isinstance(cpu_request, str) or not cpu_request.strip():
        raise ValueError("cpu_request must not be empty")
    if not isinstance(memory_request, str) or not memory_request.strip():
        raise ValueError("memory_request must not be empty")
    requires_gpu = intent.resource_hints.get("requires_gpu", False)
    requires_fpga = intent.resource_hints.get("requires_fpga", False)

    # Pick the primary compute step (GPU > FPGA > first step).
    gpu_steps = [s for s in intent.steps if s.resource_class == ResourceClass.GPU]
    fpga_steps = [s for s in intent.steps if s.resource_class == ResourceClass.FPGA]
    if gpu_steps:
        primary = gpu_steps[0]
    elif fpga_steps:
        primary = fpga_steps[0]
    else:
        primary = intent.steps[0]

    container: dict[str, Any] = {
        "name": sanitize_k8s_name(primary.name),
        "image": primary.image,
        "command": primary.command or ["sh", "-c"],
        "args": primary.args or [f'echo "run {primary.name}"'],
        "resources": {
            "requests": {
                "cpu": cpu_request.strip(),
                "memory": memory_request.strip(),
            },
        },
    }

    pod_spec: dict[str, Any] = {
        "restartPolicy": "Never",
        "containers": [container],
    }

    # ── GPU handling ──────────────────────────────────────────────────
    if requires_gpu and dra_enabled:
        # DRA path: ResourceClaim reference instead of static resource request.
        rct_name = _rct_name_for_intent(intent, "gpu")
        pod_spec["resourceClaims"] = [
            {"name": "gpu", "resourceClaimTemplateName": rct_name},
        ]
        container["resources"]["claims"] = [{"name": "gpu"}]
    elif requires_gpu:
        # Legacy path: static nvidia.com/gpu request.
        container["resources"]["requests"]["nvidia.com/gpu"] = "1"
        container["resources"]["limits"] = {"nvidia.com/gpu": "1"}
        pod_spec["nodeSelector"] = {"accelerator": "nvidia"}
        pod_spec["tolerations"] = [
            {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}
        ]

    # ── FPGA handling (legacy only — no DRA driver available) ─────────
    # ORCHIDE slide 14 uses separate node types (GPU vs FPGA). Mixed
    # GPU+FPGA in a single pod would be unschedulable — reject early.
    if requires_gpu and requires_fpga:
        raise ValueError(
            f"Workflow intent '{intent.workflow_name}' requests both GPU and FPGA "
            "resources, but mixed GPU+FPGA execution in a single pod is not supported."
        )
    if requires_fpga:
        container["resources"]["requests"]["xilinx.com/fpga"] = "1"
        container["resources"].setdefault("limits", {})["xilinx.com/fpga"] = "1"
        pod_spec["nodeSelector"] = {"accelerator": "fpga"}
        pod_spec["tolerations"] = [
            {"key": "xilinx.com/fpga", "operator": "Exists", "effect": "NoSchedule"}
        ]

    job_annotations: dict[str, str] = {
        "orbital/priority": str(intent.priority),
        "orbital/orchide-priority": str(scale_priority_orchide(intent.priority)),
        "orbital/requires-gpu": str(requires_gpu).lower(),
        "orbital/requires-fpga": str(requires_fpga).lower(),
        "orbital/fallback-enabled": str(intent.resource_hints.get("fallback_enabled", False)).lower(),
    }

    job: dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": f"{sanitize_k8s_name(intent.workflow_name, max_len=62)}-",
            "namespace": namespace,
            "labels": {
                "kueue.x-k8s.io/queue-name": queue_name,
                "mission-id": sanitize_k8s_name(intent.mission_id),
                "service-id": sanitize_k8s_name(intent.service_id),
                "priority": str(intent.priority),
            },
            "annotations": job_annotations,
        },
        "spec": {
            "template": {
                "spec": pod_spec,
            },
        },
    }
    return job


def render_workflows_for_file(input_path: str | Path) -> list[dict[str, Any]]:
    plan = load_mission_plan(input_path)
    intents = compile_plan_to_intents(plan)
    return [render_argo_workflow(intent) for intent in intents]


def write_individual_workflows(input_path: str | Path, output_dir: str | Path) -> list[Path]:
    workflows = render_workflows_for_file(input_path)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for workflow in workflows:
        out = out_dir / f"{workflow['metadata']['name']}.yaml"
        out.write_text(yaml.safe_dump(workflow, sort_keys=False), encoding="utf-8")
        written.append(out)
    return written


def compile_file(input_path: str | Path, output_path: str | Path) -> dict[str, Any]:
    plan = load_mission_plan(input_path)
    intents = compile_plan_to_intents(plan)
    payload = {
        "mission_id": plan.mission_id,
        "intents": [intent.model_dump(mode="json") for intent in intents],
        "workflows": [render_argo_workflow(intent) for intent in intents],
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return payload
