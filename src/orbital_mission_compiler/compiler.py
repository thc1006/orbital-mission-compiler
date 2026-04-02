from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .schemas import MissionPlan, WorkflowIntent, ResourceClass, WorkflowStep

logger = logging.getLogger(__name__)


def _sanitize_k8s_name(name: str) -> str:
    """Sanitize a string to be a valid RFC 1123 DNS label (K8s container/resource name)."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s[:63] or "step"


def load_mission_plan(path: str | Path) -> MissionPlan:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return MissionPlan.model_validate(raw)


def compile_plan_to_intents(plan: MissionPlan) -> List[WorkflowIntent]:
    intents: List[WorkflowIntent] = []
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
            hints = {
                "event_timestamp": event.timestamp,
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
                    workflow_name=f"{plan.mission_id}-{svc.service_id}-{event.timestamp.replace(':', '-').replace('T', '-').replace('Z', '')}".lower(),
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


def _preferred_affinity(step: WorkflowStep) -> Dict[str, Any] | None:
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


def render_argo_workflow(intent: WorkflowIntent) -> Dict[str, Any]:
    templates = []
    dag_tasks = []
    for idx, step in enumerate(intent.steps):
        template_name = f"step-{idx}-{_sanitize_k8s_name(step.name)}"
        annotations: Dict[str, str] = {
            "resource-class": step.resource_class.value,
            "needs-acceleration": str(step.needs_acceleration).lower(),
        }
        if step.phase is not None:
            annotations["phase"] = step.phase.value

        template: Dict[str, Any] = {
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

        safe_name = _sanitize_k8s_name(step.name)
        dag_task: Dict[str, Any] = {"name": safe_name, "template": template_name}
        # Sequential: linear chain (A→B→C). Parallel: no dependencies (all start at once).
        execution_mode = intent.resource_hints.get("execution_mode", "sequential")
        if execution_mode == "sequential" and idx > 0:
            dag_task["depends"] = _sanitize_k8s_name(intent.steps[idx - 1].name)
        dag_tasks.append(dag_task)

    wf_annotations: Dict[str, str] = {
        "orbital/priority": str(intent.priority),
        "orbital/execution-mode": intent.resource_hints.get("execution_mode", "sequential"),
        "orbital/requires-gpu": str(intent.resource_hints.get("requires_gpu", False)).lower(),
        "orbital/requires-fpga": str(intent.resource_hints.get("requires_fpga", False)).lower(),
        "orbital/fallback-enabled": str(intent.resource_hints.get("fallback_enabled", False)).lower(),
    }

    workflow = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "name": _sanitize_k8s_name(intent.workflow_name),
            "labels": {
                "mission-id": _sanitize_k8s_name(intent.mission_id),
                "service-id": _sanitize_k8s_name(intent.service_id),
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


def render_kueue_job(
    intent: WorkflowIntent,
    queue_name: str = "orbital-demo-local",
    namespace: str = "orbital-demo",
) -> Dict[str, Any]:
    requires_gpu = intent.resource_hints.get("requires_gpu", False)

    # Pick the primary compute step (GPU step if present, else first step).
    gpu_steps = [s for s in intent.steps if s.resource_class == ResourceClass.GPU]
    primary = gpu_steps[0] if gpu_steps else intent.steps[0]

    container: Dict[str, Any] = {
        "name": _sanitize_k8s_name(primary.name),
        "image": primary.image,
        "command": primary.command or ["sh", "-c"],
        "args": primary.args or [f'echo "run {primary.name}"'],
        "resources": {
            "requests": {
                "cpu": "1",
                "memory": "256Mi",
            },
        },
    }
    if requires_gpu:
        container["resources"]["requests"]["nvidia.com/gpu"] = "1"
        container["resources"]["limits"] = {"nvidia.com/gpu": "1"}

    pod_spec: Dict[str, Any] = {
        "restartPolicy": "Never",
        "containers": [container],
    }
    if requires_gpu:
        pod_spec["nodeSelector"] = {"accelerator": "nvidia"}
        pod_spec["tolerations"] = [
            {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}
        ]

    job_annotations: Dict[str, str] = {
        "orbital/priority": str(intent.priority),
        "orbital/requires-gpu": str(requires_gpu).lower(),
        "orbital/fallback-enabled": str(intent.resource_hints.get("fallback_enabled", False)).lower(),
    }

    job: Dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": f"{_sanitize_k8s_name(intent.workflow_name[:50])}-",
            "namespace": namespace,
            "labels": {
                "kueue.x-k8s.io/queue-name": queue_name,
                "mission-id": _sanitize_k8s_name(intent.mission_id),
                "service-id": _sanitize_k8s_name(intent.service_id),
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


def render_workflows_for_file(input_path: str | Path) -> List[Dict[str, Any]]:
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


def compile_file(input_path: str | Path, output_path: str | Path) -> Dict[str, Any]:
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
