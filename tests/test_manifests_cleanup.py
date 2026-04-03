"""Tests for issue #52: manifests cleanup and example alignment.

Verifies:
1. Placeholder READMEs in manifests/k8s and manifests/observability are removed
2. argo-gpu-cpu-fallback.yaml uses DAG format (compiler output), not steps format
3. README.md includes docker-compose usage section
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


# ── Placeholder READMEs must not exist ──────────────────────────────


def test_manifests_k8s_readme_deleted():
    """manifests/k8s/README.md placeholder must be removed."""
    path = REPO_ROOT / "manifests" / "k8s" / "README.md"
    assert not path.exists(), "manifests/k8s/README.md placeholder should be deleted"


def test_manifests_observability_readme_deleted():
    """manifests/observability/README.md placeholder must be removed."""
    path = REPO_ROOT / "manifests" / "observability" / "README.md"
    assert not path.exists(), "manifests/observability/README.md placeholder should be deleted"


# ── argo-gpu-cpu-fallback.yaml must use DAG format ──────────────────


def test_argo_example_exists():
    """manifests/examples/argo-gpu-cpu-fallback.yaml must exist."""
    path = REPO_ROOT / "manifests" / "examples" / "argo-gpu-cpu-fallback.yaml"
    assert path.exists(), "argo-gpu-cpu-fallback.yaml must exist"


def test_argo_example_is_workflow():
    """Example manifest must be kind: Workflow."""
    path = REPO_ROOT / "manifests" / "examples" / "argo-gpu-cpu-fallback.yaml"
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert obj["kind"] == "Workflow"
    assert obj["apiVersion"] == "argoproj.io/v1alpha1"


def test_argo_example_uses_dag_not_steps():
    """Example must use DAG format (compiler output), not hand-written steps format."""
    path = REPO_ROOT / "manifests" / "examples" / "argo-gpu-cpu-fallback.yaml"
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    main_template = [t for t in obj["spec"]["templates"] if t["name"] == "main"][0]
    assert "dag" in main_template, "main template must use 'dag' (not 'steps')"
    assert "steps" not in main_template, "main template must not use 'steps'"


def test_argo_example_dag_has_tasks():
    """DAG must have tasks list with entries."""
    path = REPO_ROOT / "manifests" / "examples" / "argo-gpu-cpu-fallback.yaml"
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    main_template = [t for t in obj["spec"]["templates"] if t["name"] == "main"][0]
    tasks = main_template["dag"]["tasks"]
    assert len(tasks) >= 3, "DAG should have at least 3 tasks (preprocess, detect, postprocess)"


def test_argo_example_has_sequential_dependencies():
    """DAG tasks should have sequential dependencies (compiler default)."""
    path = REPO_ROOT / "manifests" / "examples" / "argo-gpu-cpu-fallback.yaml"
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    main_template = [t for t in obj["spec"]["templates"] if t["name"] == "main"][0]
    tasks = main_template["dag"]["tasks"]
    # First task has no depends, subsequent tasks depend on previous
    assert "depends" not in tasks[0], "First task should have no dependency"
    for i in range(1, len(tasks)):
        assert "depends" in tasks[i], f"Task {i} should have a dependency"


def test_argo_example_has_orbital_annotations():
    """Compiler-generated workflow should have orbital annotations."""
    path = REPO_ROOT / "manifests" / "examples" / "argo-gpu-cpu-fallback.yaml"
    obj = yaml.safe_load(path.read_text(encoding="utf-8"))
    annotations = obj["metadata"].get("annotations", {})
    assert "orbital/priority" in annotations
    assert "orbital/fallback-enabled" in annotations


# ── README.md must document docker-compose usage ────────────────────


def test_readme_has_docker_compose_section():
    """README.md must include docker-compose usage section."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docker compose" in readme.lower() or "docker-compose" in readme.lower(), \
        "README.md must mention docker compose"


def test_readme_docker_compose_section_has_heading():
    """README.md docker-compose section should have a proper heading."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Local development with Docker Compose" in readme, \
        "README.md must have '## Local development with Docker Compose' heading"


def test_readme_docker_compose_has_command():
    """README.md docker-compose section should show the docker compose up command."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docker compose up" in readme, \
        "README.md must show 'docker compose up' command"
