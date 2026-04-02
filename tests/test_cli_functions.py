"""Direct function-level tests for cli.py (contributes to coverage)."""

import json

import pytest

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
    assert len(data["files"]) >= 1


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
    assert len(data["files"]) >= 1


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
    assert "ok" in captured.out
