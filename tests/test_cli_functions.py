"""Direct function-level tests for cli.py (contributes to coverage)."""

import json
from pathlib import Path

import pytest
import yaml

from orbital_mission_compiler.cli import (
    build_parser,
    cmd_compile,
    cmd_inspect,
    cmd_render_argo,
    cmd_render_kueue,
    cmd_policy,
    main,
)


def test_build_parser_has_all_subcommands():
    parser = build_parser()
    for cmd in ["compile", "render-argo", "render-kueue", "inspect", "policy"]:
        args = parser.parse_args([cmd, "--input", "dummy.yaml"] + (
            ["--output", "out.yaml"] if cmd == "compile" else
            ["--output-dir", "out/"] if cmd in ("render-argo", "render-kueue") else
            []
        ))
        assert args.command == cmd


def test_cmd_compile(tmp_path, capsys):
    out = tmp_path / "result.yaml"
    args = build_parser().parse_args([
        "compile",
        "--input", "configs/mission_plans/sample_maritime_surveillance.yaml",
        "--output", str(out),
    ])
    cmd_compile(args)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "ok"
    assert out.exists()


def test_cmd_inspect(capsys):
    args = build_parser().parse_args([
        "inspect",
        "--input", "configs/mission_plans/sample_maritime_surveillance.yaml",
    ])
    cmd_inspect(args)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert isinstance(data, list)
    assert data[0]["service_id"] == "maritime-surveillance"


def test_cmd_render_argo(tmp_path, capsys):
    args = build_parser().parse_args([
        "render-argo",
        "--input", "configs/mission_plans/sample_maritime_surveillance.yaml",
        "--output-dir", str(tmp_path),
    ])
    cmd_render_argo(args)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "ok"
    assert isinstance(data["files"], list)
    assert len(data["files"]) >= 1
    for f in data["files"]:
        assert Path(f).exists()


def test_cmd_render_kueue(tmp_path, capsys):
    args = build_parser().parse_args([
        "render-kueue",
        "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
        "--output-dir", str(tmp_path),
    ])
    cmd_render_kueue(args)
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "ok"
    assert isinstance(data["files"], list)
    assert len(data["files"]) >= 1
    for f in data["files"]:
        assert Path(f).exists()


def test_cmd_render_kueue_dra_fallback_job_uses_exactly_not_first_available(tmp_path, capsys):
    """End-to-end: render-kueue --dra-fallback emits the scheduler-route
    firstAvailable RCT, but the Kueue Job references the exactly RCT. Kueue rejects
    firstAvailable as Inadmissible, so the Job must never reference it.

    The two claims also go to separate files. A single file holding both reads as
    though the admitted Job falls back, and applying it creates a claim template
    that nothing in the bundle consumes.
    """
    args = build_parser().parse_args([
        "render-kueue",
        "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
        "--output-dir", str(tmp_path),
        "--dra-fallback",
    ])
    cmd_render_kueue(args)
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "ok" and data["files"]

    def _has_fa(rct):
        return "firstAvailable" in rct["spec"]["spec"]["devices"]["requests"][0]

    def _load(path):
        return [d for d in yaml.safe_load_all(Path(path).read_text()) if d]

    kueue_files = [f for f in data["files"] if f.endswith("-kueue.yaml")]
    sched_files = [f for f in data["files"] if f.endswith("-scheduler-fallback.yaml")]
    assert kueue_files and sched_files, data["files"]

    fa_names, ex_names = set(), set()
    for f in sched_files:
        docs = _load(f)
        assert all(d["kind"] == "ResourceClaimTemplate" and _has_fa(d) for d in docs), docs
        assert all(d["metadata"]["labels"]["orbital/dra-route"] == "scheduler" for d in docs)
        fa_names |= {d["metadata"]["name"] for d in docs}
    assert fa_names, "expected a scheduler-route firstAvailable RCT"

    for f in kueue_files:
        docs = _load(f)
        rcts = [d for d in docs if d["kind"] == "ResourceClaimTemplate"]
        jobs = [d for d in docs if d["kind"] == "Job"]
        assert jobs, "expected a Kueue Job"
        assert not any(_has_fa(r) for r in rcts), "firstAvailable leaked into the Kueue bundle"
        ex_names |= {r["metadata"]["name"] for r in rcts}
        for job in jobs:
            refs = {
                c["resourceClaimTemplateName"]
                for c in job["spec"]["template"]["spec"].get("resourceClaims", [])
            }
            assert refs & ex_names, "Kueue Job must reference the exactly RCT"
            assert not (refs & fa_names), "Kueue Job must NOT reference a firstAvailable RCT"
    assert ex_names, "expected a Kueue-route exactly RCT"


def test_cmd_policy(capsys):
    args = build_parser().parse_args([
        "policy",
        "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
    ])
    with pytest.raises(SystemExit) as exc_info:
        cmd_policy(args)
    assert exc_info.value.code in (0, 2)  # 0=OPA pass, 2=OPA not installed


def test_main_compile(tmp_path, capsys, monkeypatch):
    out = tmp_path / "main_test.yaml"
    monkeypatch.setattr(
        "sys.argv",
        ["omc", "compile",
         "--input", "configs/mission_plans/sample_maritime_surveillance.yaml",
         "--output", str(out)],
    )
    main()
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["status"] == "ok"
    assert out.exists()


# ── a complete output set is not a picture of the directory ───────────


def _shrink_plan(tmp_path, service_ids):
    services = "\n".join(
        f"      - service_id: {sid}\n"
        f"        priority: 50\n"
        f"        steps:\n"
        f"          - name: s\n"
        f"            image: busybox:1.36\n"
        f"            resource_class: cpu\n"
        for sid in service_ids
    )
    plan = tmp_path / f"plan-{len(service_ids)}.yaml"
    plan.write_text(
        "mission_id: m\n"
        "events:\n"
        "  - timestamp: '2026-08-01T00:00:00Z'\n"
        "    event_type: acquisition\n"
        "    instrument: cam\n"
        "    duration_seconds: 60\n"
        "    services:\n" + services,
        encoding="utf-8",
    )
    return plan


def test_a_shrunk_plan_reports_the_artifacts_it_no_longer_covers(tmp_path, capsys):
    """A render writes what the plan describes; it does not empty the directory.

    After a service is removed its manifest stays behind, and the documented
    `kubectl apply -f <dir>` redeploys exactly the workload the plan no longer
    asks for. The render cannot silently present that directory as its output.
    """
    out = tmp_path / "out"
    big = build_parser().parse_args([
        "render-argo", "--input", str(_shrink_plan(tmp_path, ["a", "b", "c"])),
        "--output-dir", str(out),
    ])
    cmd_render_argo(big)
    first = json.loads(capsys.readouterr().out)
    assert len(first["files"]) == 3 and "stale" not in first

    small = build_parser().parse_args([
        "render-argo", "--input", str(_shrink_plan(tmp_path, ["a"])),
        "--output-dir", str(out),
    ])
    cmd_render_argo(small)
    captured = capsys.readouterr()
    second = json.loads(captured.out)
    assert len(second["files"]) == 1
    assert len(second["stale"]) == 2, second
    assert "--prune" in captured.err
    # Left in place: removing a file is the operator's call, not a side effect.
    assert len(list(out.glob("*.yaml"))) == 3


def test_prune_removes_only_this_tools_leftovers(tmp_path, capsys):
    out = tmp_path / "out"
    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", str(_shrink_plan(tmp_path, ["a", "b", "c"])),
        "--output-dir", str(out),
    ]))
    capsys.readouterr()
    # An unrelated manifest an operator keeps alongside the rendered output.
    theirs = out / "their-own.yaml"
    theirs.write_text("apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: keep\n", encoding="utf-8")

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", str(_shrink_plan(tmp_path, ["a"])),
        "--output-dir", str(out), "--prune",
    ]))
    result = json.loads(capsys.readouterr().out)
    assert len(result["pruned"]) == 2
    assert "stale" not in result
    remaining = sorted(p.name for p in out.glob("*.yaml"))
    assert theirs.name in remaining, remaining
    assert len(remaining) == 2, remaining


def test_render_kueue_reports_its_own_leftovers(tmp_path, capsys):
    out = tmp_path / "kout"
    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", str(_shrink_plan(tmp_path, ["a", "b"])),
        "--output-dir", str(out),
    ]))
    capsys.readouterr()
    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", str(_shrink_plan(tmp_path, ["a"])),
        "--output-dir", str(out),
    ]))
    result = json.loads(capsys.readouterr().out)
    assert len(result["stale"]) == 1, result


def test_prune_does_not_reach_into_another_mission(tmp_path, capsys):
    """Ownership is not enough to delete by.

    Another mission's manifests in the same directory carry the same
    managed-by label and are equally this tool's output, but they are not this
    render's to remove -- and neither are the cluster-scoped priority classes the
    other renderer writes, which belong to no mission at all.
    """
    out = tmp_path / "shared"
    cmd_render_kueue(build_parser().parse_args([
        "render-kueue", "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
        "--output-dir", str(out), "--emit-priority-classes",
    ]))
    capsys.readouterr()
    other = sorted(p.name for p in out.glob("*.yaml"))
    assert any("wildfire" in n for n in other), other
    assert "workload-priority-classes.yaml" in other

    cmd_render_argo(build_parser().parse_args([
        "render-argo", "--input", str(_shrink_plan(tmp_path, ["a"])),
        "--output-dir", str(out), "--prune",
    ]))
    result = json.loads(capsys.readouterr().out)
    assert "pruned" not in result, result
    remaining = sorted(p.name for p in out.glob("*.yaml"))
    for name in other:
        assert name in remaining, f"{name} was pruned by another mission's render"
