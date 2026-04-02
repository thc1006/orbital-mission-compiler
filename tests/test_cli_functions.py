"""Direct function-level tests for cli.py (contributes to coverage)."""

import json

from orbital_mission_compiler.cli import build_parser, cmd_compile, cmd_inspect


def test_build_parser_has_all_subcommands():
    parser = build_parser()
    # Parser should accept these subcommands without error
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
