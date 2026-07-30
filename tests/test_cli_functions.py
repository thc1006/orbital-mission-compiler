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
