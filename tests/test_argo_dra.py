"""End-to-end DRA rendering in the Argo route (opt-in --dra-fallback).

Closes the orphan-ResourceClaimTemplate gap: ``render_argo_workflow`` wires the
accelerator-fallback step's Pod to a ``firstAvailable`` RCT via ``podSpecPatch``,
and ``write_individual_workflows`` emits that RCT alongside the Workflow so the
reference resolves and the file is applyable end-to-end (scheduler-level GPU->CPU
fallback, paper Sec. V-D / V-F). Default off (runtime env-var switch preserved).
"""

import shutil
import subprocess

import pytest
import yaml

from orbital_mission_compiler.compiler import (
    _dra_fallback_steps,
    _rct_name_for_intent,
    compile_plan_to_intents,
    load_mission_plan,
    render_argo_workflow,
    write_individual_workflows,
)

GPU_FALLBACK = "configs/mission_plans/sample_gpu_cpu_fallback.yaml"  # gpu -> cpu (driver-backed)
FPGA = "configs/mission_plans/sample_fpga_signal.yaml"  # fpga -> cpu (no FPGA DRA driver)


def _intent(path: str):
    return compile_plan_to_intents(load_mission_plan(path))[0]


def _step_templates(wf: dict) -> list[dict]:
    return [t for t in wf["spec"]["templates"] if t["name"] != "main"]


# ── render_argo_workflow wiring ──────────────────────────────────────────


def test_default_argo_has_no_podspecpatch():
    # Regression guard: without dra_fallback the Argo path is unchanged (env-var).
    wf = render_argo_workflow(_intent(GPU_FALLBACK))
    assert all("podSpecPatch" not in t for t in _step_templates(wf))


def test_dra_fallback_wires_first_available_rct_two_halves():
    intent = _intent(GPU_FALLBACK)
    wf = render_argo_workflow(intent, dra_fallback=True)
    patched = [t for t in _step_templates(wf) if "podSpecPatch" in t]
    assert len(patched) == 1  # exactly the accelerator-fallback step
    step = patched[0]
    rct_name = _rct_name_for_intent(intent, "accel")
    # (1) pod-level resourceClaims via podSpecPatch (no structured Template field
    # exists for it); it references the RCT and carries ONLY the pod-level entry.
    patch = yaml.safe_load(step["podSpecPatch"])
    assert set(patch) == {"resourceClaims"}
    assert patch["resourceClaims"][0]["resourceClaimTemplateName"] == rct_name
    local = patch["resourceClaims"][0]["name"]
    # (2) the container binding is a NATIVE structural CRD field (Argo >= v4.0),
    # referencing the same local claim name.
    assert step["container"]["resources"]["claims"] == [{"name": local}]  # Argo names the user container 'main'


def test_fpga_step_is_not_wired():
    # FPGA has no DRA driver, so it does not qualify for a firstAvailable claim.
    intent = _intent(FPGA)
    assert _dra_fallback_steps(intent) == []
    wf = render_argo_workflow(intent, dra_fallback=True)
    assert all("podSpecPatch" not in t for t in _step_templates(wf))


# ── write_individual_workflows emits a self-contained, resolvable bundle ──


def test_write_emits_rct_and_the_reference_resolves(tmp_path):
    written = write_individual_workflows(GPU_FALLBACK, tmp_path, enforce_policy=False, dra_fallback=True)
    docs = [d for d in yaml.safe_load_all(written[0].read_text()) if d]
    rcts = [d for d in docs if d.get("kind") == "ResourceClaimTemplate"]
    wfs = [d for d in docs if d.get("kind") == "Workflow"]
    assert len(rcts) == 1 and len(wfs) == 1

    # The emitted claim is the scheduler-route firstAvailable [gpu.nvidia.com, dra.cpu].
    req = rcts[0]["spec"]["spec"]["devices"]["requests"][0]
    assert "firstAvailable" in req and "exactly" not in req
    classes = [d["deviceClassName"] for d in req["firstAvailable"]]
    assert classes == ["gpu.nvidia.com", "dra.cpu"]

    # The Workflow's podSpecPatch reference resolves to THIS RCT (no orphan).
    patched = [t for t in wfs[0]["spec"]["templates"] if "podSpecPatch" in t]
    assert len(patched) == 1
    patch = yaml.safe_load(patched[0]["podSpecPatch"])
    assert patch["resourceClaims"][0]["resourceClaimTemplateName"] == rcts[0]["metadata"]["name"]


def test_default_write_is_single_workflow_doc(tmp_path):
    written = write_individual_workflows(GPU_FALLBACK, tmp_path, enforce_policy=False)
    docs = [d for d in yaml.safe_load_all(written[0].read_text()) if d]
    assert len(docs) == 1 and docs[0]["kind"] == "Workflow"


# ── argo lint accepts the DRA-wired Workflow ─────────────────────────────


@pytest.mark.skipif(shutil.which("argo") is None, reason="argo CLI not installed")
def test_argo_lint_accepts_dra_wired_workflow(tmp_path):
    # Lint the Workflow document (the RCT is a core k8s object, not an Argo kind,
    # so it is validated by the live cluster / kubeconform, not argo lint).
    intent = _intent(GPU_FALLBACK)
    wf = render_argo_workflow(intent, dra_fallback=True)
    wf_file = tmp_path / "wf.yaml"
    wf_file.write_text(yaml.safe_dump(wf, sort_keys=False), encoding="utf-8")
    r = subprocess.run(
        ["argo", "lint", "--offline", str(wf_file)], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


# ── Review-driven regression cases (PR #77 external review) ──────────────


def _synthetic_intent(steps, workflow_name="wf"):
    """Build an intent directly so a case can bypass the sample-plan corpus."""
    from orbital_mission_compiler.schemas import WorkflowIntent

    return WorkflowIntent(
        mission_id="m",
        service_id="s",
        priority=50,
        workflow_name=workflow_name,
        steps=steps,
        resource_hints={"execution_mode": "sequential"},
    )


def _step(name, primary, fallback=None):
    from orbital_mission_compiler.schemas import ResourceClass, WorkflowStep

    return WorkflowStep(
        name=name,
        image="img:1",
        resource_class=ResourceClass(primary),
        fallback_resource_class=ResourceClass(fallback) if fallback else None,
    )


def test_rct_names_stay_distinct_at_the_length_budget():
    """A long workflow name must not truncate the accel/gpu discriminator away.

    Plain truncation to 62 characters drops the suffix once the name fills the
    budget, so both templates would collapse to the same name and the second
    would overwrite the first on apply, silently removing the fallback route.
    """
    long_name = "w" * 63
    intent = _synthetic_intent([_step("a", "gpu", "cpu")], workflow_name=long_name)
    accel = _rct_name_for_intent(intent, "accel")
    gpu = _rct_name_for_intent(intent, "gpu")
    assert accel != gpu
    assert len(accel) <= 62 and len(gpu) <= 62


def test_every_emitted_object_identity_is_unique(tmp_path):
    """No two emitted documents may share (apiVersion, kind, namespace, name)."""
    written = write_individual_workflows(
        GPU_FALLBACK, tmp_path, enforce_policy=False, dra_fallback=True, namespace="ns-a"
    )
    identities = []
    for path in written:
        for doc in yaml.safe_load_all(path.read_text()):
            if doc:
                meta = doc.get("metadata", {})
                identities.append(
                    (doc.get("apiVersion"), doc.get("kind"), meta.get("namespace"), meta.get("name"))
                )
    assert len(identities) == len(set(identities)), identities


def test_multi_doc_places_workflow_and_template_in_one_namespace(tmp_path):
    """A Pod resolves a ResourceClaimTemplate only in its own namespace, so a
    multi-doc file that advertises itself as applyable must agree on one."""
    written = write_individual_workflows(
        GPU_FALLBACK, tmp_path, enforce_policy=False, dra_fallback=True, namespace="mission-ns"
    )
    docs = [d for d in yaml.safe_load_all(written[0].read_text()) if d]
    namespaces = {d["kind"]: d["metadata"].get("namespace") for d in docs}
    assert namespaces["ResourceClaimTemplate"] == "mission-ns"
    assert namespaces["Workflow"] == "mission-ns"


@pytest.mark.parametrize("mode", ["sequential", "parallel"])
def test_every_accelerator_step_is_wired_not_only_the_first(mode):
    """Two GPU-to-CPU steps in one service must both get claim wiring.

    Wiring only the first leaves the rest on the runtime-only path while the
    render still reports success, which is the failure worth catching.
    """
    intent = _synthetic_intent([_step("a", "gpu", "cpu"), _step("b", "gpu", "cpu")])
    intent.resource_hints["execution_mode"] = mode
    wf = render_argo_workflow(intent, dra_fallback=True)
    wired = [
        t
        for t in wf["spec"]["templates"]
        if "podSpecPatch" in t and t.get("container", {}).get("resources", {}).get("claims")
    ]
    assert len(wired) == 2, [t["name"] for t in wf["spec"]["templates"]]


def test_cpu_primary_with_gpu_fallback_is_not_treated_as_accelerator_fallback():
    """CPU-to-GPU would render "prefer CPU, else accelerator", the reverse of the
    documented accelerator-with-fallback semantics, so it must not qualify."""
    intent = _synthetic_intent([_step("a", "cpu", "gpu")])
    assert _dra_fallback_steps(intent) == []
    wf = render_argo_workflow(intent, dra_fallback=True)
    assert all("podSpecPatch" not in t for t in wf["spec"]["templates"])


# ── Third review round: normalization collisions, deployment contract ────


def test_ids_that_normalize_alike_get_distinct_names(tmp_path):
    """Dedup has to happen after Kubernetes name normalization.

    `foo_bar`, `foo.bar`, `FOO-BAR` and `foo-bar` are four distinct service ids
    that all sanitize to the same label. Counting the raw id treats each as a
    first occurrence, so they land on one object name and one filename, and three
    of the four services are silently lost.
    """
    services = "\n".join(
        f"      - service_id: {sid}\n"
        f"        priority: 50\n"
        f"        steps:\n"
        f"          - name: s\n"
        f"            image: i\n"
        f"            resource_class: cpu\n"
        for sid in ("foo_bar", "foo-bar", "foo.bar", "FOO-BAR")
    )
    plan = tmp_path / "collide.yaml"
    plan.write_text(
        "mission_id: m\n"
        "events:\n"
        "  - timestamp: '2026-08-01T00:00:00Z'\n"
        "    event_type: acquisition\n"
        "    instrument: cam\n"
        "    services:\n" + services,
        encoding="utf-8",
    )
    out = tmp_path / "out"
    written = write_individual_workflows(plan, out, enforce_policy=False)
    assert len(written) == 4, written
    assert len({p.name for p in written}) == 4, [p.name for p in written]
    names = [
        next(d for d in yaml.safe_load_all(p.read_text()) if d)["metadata"]["name"]
        for p in written
    ]
    assert len(set(names)) == 4, names


def test_service_account_is_stamped_for_the_kubectl_apply_path(tmp_path):
    """`argo submit --serviceaccount` cannot be used on the multi-doc bundle,
    because argo submit drops the ResourceClaimTemplate, so the account has to be
    in the manifest for the documented kubectl apply path to run correctly."""
    written = write_individual_workflows(
        GPU_FALLBACK, tmp_path, enforce_policy=False, dra_fallback=True,
        namespace="ns", service_account="orbital-workflow-runner",
    )
    docs = [d for d in yaml.safe_load_all(written[0].read_text()) if d]
    wf = next(d for d in docs if d["kind"] == "Workflow")
    assert wf["spec"]["serviceAccountName"] == "orbital-workflow-runner"


def test_duplicate_yaml_keys_are_rejected(tmp_path):
    """A plan that reads one way and loads another is not something to resolve
    silently in a toolchain whose output is signed off before uplink."""
    import pytest as _pytest

    bad = tmp_path / "dup.yaml"
    bad.write_text(
        "mission_id: m\n"
        "events:\n"
        "  - timestamp: '2026-08-01T00:00:00Z'\n"
        "    event_type: acquisition\n"
        "    instrument: cam\n"
        "    services:\n"
        "      - service_id: s\n"
        "        priority: 50\n"
        "        steps:\n"
        "          - name: a\n"
        "            image: i\n"
        "            resource_class: gpu\n"
        "            fallback_resource_class: gpu\n"
        "            fallback_resource_class: cpu\n",
        encoding="utf-8",
    )
    with _pytest.raises(Exception, match="duplicate key"):
        load_mission_plan(bad)
