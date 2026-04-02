from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from .schemas import MissionPlan, WorkflowIntent, ResourceClass


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
            hints = {
                "event_timestamp": event.timestamp,
                "ground_visibility": event.ground_visibility,
                "region_type": event.region_type,
                "requires_gpu": bool(gpu_steps),
                "requires_fpga": bool(fpga_steps),
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


def render_argo_workflow(intent: WorkflowIntent) -> Dict[str, Any]:
    templates = []
    dag_tasks = []
    for idx, step in enumerate(intent.steps):
        template_name = f"step-{idx}-{step.name}"
        templates.append(
            {
                "name": template_name,
                "container": {
                    "image": step.image,
                    "command": step.command or ["sh", "-c"],
                    "args": step.args or [f'echo "run {step.name}"'],
                },
                "metadata": {
                    "annotations": {
                        "resource-class": step.resource_class.value,
                        "needs-acceleration": str(step.needs_acceleration).lower(),
                    }
                },
            }
        )
        depends = intent.steps[idx - 1].name if idx > 0 else None
        dag_task = {
            "name": step.name,
            "template": template_name,
        }
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
            "templates": [
                {
                    "name": "main",
                    "dag": {
                        "tasks": dag_tasks
                    },
                },
                *templates,
            ],
        },
    }
    return workflow


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
