"""Tests for Argo and Kueue rendering hardening.

Verifies rendered YAML carries phase annotations, priority metadata,
and runtime hints from the IR. Does NOT test live cluster behavior.
"""

from orbital_mission_compiler.compiler import (
    load_mission_plan,
    compile_plan_to_intents,
    render_argo_workflow,
    render_kueue_job,
)


def _intents(plan_file):
    return compile_plan_to_intents(load_mission_plan(plan_file))


# ── Argo: phase annotation on templates ──────────────────────────────


def test_argo_template_has_phase_annotation():
    """Argo templates should annotate the step phase (slide 10)."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    wf = render_argo_workflow(intent)
    # step-0-preprocess template
    preprocess = [t for t in wf["spec"]["templates"] if t["name"] == "step-0-preprocess"][0]
    assert preprocess["metadata"]["annotations"]["phase"] == "preprocessing"

    # step-1-detect-ships (AI phase)
    detect = [t for t in wf["spec"]["templates"] if t["name"] == "step-1-detect-ships"][0]
    assert detect["metadata"]["annotations"]["phase"] == "ai"


def test_argo_template_phase_absent_when_none():
    """Templates without phase should not have a phase annotation."""
    intent = _intents("configs/mission_plans/sample_maritime_surveillance.yaml")[0]
    wf = render_argo_workflow(intent)
    preprocess = [t for t in wf["spec"]["templates"] if t["name"] == "step-0-preprocess"][0]
    assert "phase" not in preprocess["metadata"]["annotations"]


# ── Argo: priority in workflow annotations ───────────────────────────


def test_argo_workflow_has_priority_annotation():
    """Workflow metadata should carry priority as annotation for scheduling."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    wf = render_argo_workflow(intent)
    annotations = wf["metadata"].get("annotations", {})
    assert annotations["orbital/priority"] == "90"


# ── Argo: resource hints in workflow annotations ─────────────────────


def test_argo_workflow_has_resource_annotations():
    """Workflow should annotate GPU/FPGA requirements for cluster-level visibility."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    wf = render_argo_workflow(intent)
    annotations = wf["metadata"].get("annotations", {})
    assert annotations["orbital/requires-gpu"] == "true"


# ── Kueue: priority label ────────────────────────────────────────────


def test_kueue_job_has_priority_annotation():
    """Kueue Job should carry priority as annotation (not just label)."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    job = render_kueue_job(intent)
    annotations = job["metadata"].get("annotations", {})
    assert annotations["orbital/priority"] == "90"


def test_kueue_job_has_resource_annotations():
    """Kueue Job should annotate resource requirements."""
    intent = _intents("configs/mission_plans/sample_orchide_format.yaml")[0]
    job = render_kueue_job(intent)
    annotations = job["metadata"].get("annotations", {})
    assert annotations["orbital/requires-gpu"] == "true"

# ── A step gets what it asked to run, and nothing it did not ───────────


def _one_step_intent(command, args):
    """An intent carrying a single step with the given command and args."""
    from orbital_mission_compiler.schemas import (
        AIService,
        MissionEvent,
        MissionEventType,
        MissionPlan,
        WorkflowStep,
    )

    step = WorkflowStep(name="my-step", image="img:latest", command=command, args=args)
    plan = MissionPlan(
        mission_id="entrypoint",
        events=[
            MissionEvent(
                timestamp="2029-10-06T00:23:00Z",
                event_type=MissionEventType.ACQUISITION,
                orbit=1,
                instrument="INST_1",
                services=[AIService(service_id="svc", priority=1, steps=[step])],
            )
        ],
    )
    return compile_plan_to_intents(plan)[0]


def _argo_container(command, args):
    wf = render_argo_workflow(_one_step_intent(command, args))
    return [t for t in wf["spec"]["templates"] if "container" in t][0]["container"]


def _kueue_container(command, args):
    job = render_kueue_job(_one_step_intent(command, args))
    return job["spec"]["template"]["spec"]["containers"][0]


def test_a_command_only_step_is_not_handed_an_argument():
    """`or` treats an empty list as absent, so /app/run gained an echo.

    The compiler was changing what runs, which is the one thing it must not do.
    """
    for container in (_argo_container(["/app/run"], []), _kueue_container(["/app/run"], [])):
        assert container["command"] == ["/app/run"]
        assert "args" not in container


def test_an_args_only_step_keeps_the_image_entrypoint():
    """Defaulting the command to sh -c makes the first arg the program it runs."""
    for container in (
        _argo_container([], ["--model", "/models/a"]),
        _kueue_container([], ["--model", "/models/a"]),
    ):
        assert "command" not in container
        assert container["args"] == ["--model", "/models/a"]


def test_a_step_naming_both_is_rendered_as_written():
    for container in (_argo_container(["/app/run"], ["--x"]), _kueue_container(["/app/run"], ["--x"])):
        assert container["command"] == ["/app/run"]
        assert container["args"] == ["--x"]


def test_a_step_naming_neither_leaves_the_image_defaults_alone():
    """Kubernetes runs the image's ENTRYPOINT and CMD when the spec names neither.

    Substituting a shell here would stop an image that carries its own entrypoint
    from ever running its application: an inference server declaring
    ENTRYPOINT ["/app/inference-server"] would be replaced by an echo. The compiler
    cannot know what an arbitrary image is for, so it says nothing.
    """
    for container in (_argo_container([], []), _kueue_container([], [])):
        assert "command" not in container
        assert "args" not in container


def test_the_demo_plans_still_render_the_command_they_always_did():
    """The demo command moved into the plans, so what they render is unchanged.

    Their images do not exist, so this is about the sample staying a working
    example rather than about anything running.
    """
    for plan in ("demo_gpu_no_fallback", "demo_gpu_fallback_fixed"):
        wf = render_argo_workflow(_intents(f"configs/mission_plans/{plan}.yaml")[0])
        containers = [t["container"] for t in wf["spec"]["templates"] if "container" in t]
        assert containers
        for container in containers:
            assert container["command"] == ["sh", "-c"]
            assert container["args"][0].startswith('echo "run ')
