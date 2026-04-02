from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from .schemas import MissionPlan, WorkflowIntent, ResourceClass, WorkflowStep


def load_mission_plan(path: str | Path) -> MissionPlan:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return MissionPlan.model_validate(raw)


def compile_plan_to_intents(plan: MissionPlan) -> List[WorkflowIntent]:
    intents: List[WorkflowIntent] = []
    for event in plan.events:
        if event.event_type.value != "acquisition":
            continue
        for svc in event.services:
            gpu_steps = [s for s in svc.steps if s.resource_class == ResourceClass.GPU]
            fpga_steps = [s for s in svc.steps if s.resource_class == ResourceClass.FPGA]
            fallback_steps = [s for s in svc.steps if s.fallback_resource_class is not None]
            hints = {
                "event_timestamp": event.timestamp,
                "ground_visibility": event.ground_visibility,
                "region_type": event.region_type,
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
        template_name = f"step-{idx}-{step.name}"
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
                "annotations": {
                    "resource-class": step.resource_class.value,
                    "needs-acceleration": str(step.needs_acceleration).lower(),
                }
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

        depends = intent.steps[idx - 1].name if idx > 0 else None
        dag_task = {"name": step.name, "template": template_name}
        if depends:
            dag_task["depends"] = depends
        dag_tasks.append(dag_task)

    workflow = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "name": intent.workflow_name[:63],
            "labels": {
                "mission-id": intent.mission_id,
                "service-id": intent.service_id,
                "priority": str(intent.priority),
            },
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
        "name": primary.name,
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

    job: Dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": f"{intent.workflow_name[:50]}-",
            "namespace": namespace,
            "labels": {
                "kueue.x-k8s.io/queue-name": queue_name,
                "mission-id": intent.mission_id,
                "service-id": intent.service_id,
                "priority": str(intent.priority),
            },
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
