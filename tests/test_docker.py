"""Tests for Docker image build and basic functionality.

Issue #13. Skips if docker CLI or daemon is not available.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _docker_daemon_available() -> bool:
    """Check both docker CLI exists and daemon is accessible."""
    if not shutil.which("docker"):
        return False
    try:
        result = subprocess.run(
            ["docker", "info"], capture_output=True, check=False, timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


DOCKER_AVAILABLE = _docker_daemon_available()

pytestmark = pytest.mark.skipif(not DOCKER_AVAILABLE, reason="docker daemon not available")

IMAGE_TAG = "omc:test"


@pytest.fixture(scope="module", autouse=True)
def build_image():
    """Build the Docker image once for all tests in this module."""
    result = subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, "."],
        capture_output=True, text=True, check=False, timeout=120,
        cwd=str(REPO_ROOT),
    )
    if result.returncode != 0:
        pytest.fail(f"Docker build failed:\n{result.stderr}")
    yield
    subprocess.run(["docker", "rmi", IMAGE_TAG], capture_output=True, check=False)


def _docker_run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "run", "--rm", IMAGE_TAG, *args],
        capture_output=True, text=True, check=False, timeout=30,
    )


def test_docker_cli_help():
    """Container should print CLI help."""
    result = _docker_run()
    assert result.returncode == 0


def test_docker_import_works():
    """Python import should work inside container."""
    result = _docker_run(
        "python", "-c",
        "from orbital_mission_compiler.compiler import load_mission_plan; print('ok')",
    )
    assert result.returncode == 0
    assert "ok" in result.stdout


def test_docker_verify():
    """scripts/verify.py should pass inside container."""
    result = _docker_run("python", "scripts/verify.py")
    assert result.returncode == 0
