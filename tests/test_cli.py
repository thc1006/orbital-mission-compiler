"""Tests for CLI subcommands.

Covers: compile, render-argo, render-kueue, inspect, policy.
Goal: push cli.py from 0% to >80% coverage.
"""

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    """Run CLI as subprocess with PYTHONPATH set."""
    return subprocess.run(
        [sys.executable, "-m", "orbital_mission_compiler.cli", *args],
        capture_output=True,
        text=True,
        env={"PYTHONPATH": "src:.", "PATH": "/usr/bin:/bin:/usr/local/bin:" + str(Path.home() / ".local/bin")},
        check=False,
    )


# ── compile ───────────────────────────────────────────────────────────


def test_cli_compile(tmp_path):
    out = tmp_path / "output.yaml"
    result = _run_cli("compile", "--input", "configs/mission_plans/sample_maritime_surveillance.yaml", "--output", str(out))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "ok"
    assert data["workflows"] >= 1
    assert out.exists()


# ── render-argo ───────────────────────────────────────────────────────


def test_cli_render_argo(tmp_path):
    result = _run_cli("render-argo", "--input", "configs/mission_plans/sample_maritime_surveillance.yaml", "--output-dir", str(tmp_path))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "ok"
    assert len(data["files"]) >= 1


# ── render-kueue ──────────────────────────────────────────────────────


def test_cli_render_kueue(tmp_path):
    result = _run_cli("render-kueue", "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml", "--output-dir", str(tmp_path))
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert data["status"] == "ok"


# ── inspect ───────────────────────────────────────────────────────────


def test_cli_inspect():
    result = _run_cli("inspect", "--input", "configs/mission_plans/sample_maritime_surveillance.yaml")
    assert result.returncode == 0
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "mission_id" in data[0]


# ── policy ────────────────────────────────────────────────────────────


def test_cli_policy():
    result = _run_cli("policy", "--input", "configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    # rc=0 if OPA available and plan valid, rc=2 if OPA not installed
    assert result.returncode in (0, 2)


# ── error cases ───────────────────────────────────────────────────────


def test_cli_missing_input():
    result = _run_cli("compile", "--input", "nonexistent.yaml", "--output", "/tmp/out.yaml")
    assert result.returncode != 0


def test_cli_no_command():
    result = _run_cli()
    assert result.returncode != 0
