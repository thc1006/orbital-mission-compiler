from orbital_mission_compiler.compiler import load_mission_plan, compile_plan_to_intents, render_argo_workflow


def test_compile_plan_to_intents():
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    intents = compile_plan_to_intents(plan)
    assert len(intents) == 1
    assert intents[0].service_id == "maritime-surveillance"
    assert intents[0].resource_hints["requires_gpu"] is True


def test_render_argo_workflow():
    plan = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    intent = compile_plan_to_intents(plan)[0]
    wf = render_argo_workflow(intent)
    assert wf["kind"] == "Workflow"
    assert wf["metadata"]["labels"]["service-id"] == "maritime-surveillance"
