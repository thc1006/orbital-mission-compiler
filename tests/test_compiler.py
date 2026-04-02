from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents, render_argo_workflow


def test_compile_plan_to_intents():
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    intents = compile_plan_to_intents(plan)
    assert len(intents) == 1
    assert intents[0].service_id == "maritime-surveillance"
    assert intents[0].resource_hints["requires_gpu"] is True
    assert intents[0].resource_hints["fallback_enabled"] is True


def test_render_argo_workflow():
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    intent = compile_plan_to_intents(plan)[0]
    wf = render_argo_workflow(intent)
    assert wf["kind"] == "Workflow"
    assert wf["metadata"]["labels"]["service-id"] == "maritime-surveillance"
    detect = [t for t in wf["spec"]["templates"] if t["name"] == "step-1-detect-ships"][0]
    annotations = detect["metadata"]["annotations"]
    assert annotations["fallback-resource-class"] == "cpu"
    assert detect["affinity"]["nodeAffinity"]["preferredDuringSchedulingIgnoredDuringExecution"][0]["weight"] == 100
