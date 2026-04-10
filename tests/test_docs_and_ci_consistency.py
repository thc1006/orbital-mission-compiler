from __future__ import annotations

from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_docs_13_no_stale_counts():
    """Market positioning doc should not keep stale tool/rule/case counts."""
    text = (_REPO_ROOT / "docs" / "13_market_positioning.md").read_text(encoding="utf-8")
    assert "FastMCP (4 tools)" not in text
    assert "4 條 deny rules" not in text
    assert "2 cases" not in text


def test_docs_14_parallel_claim_updated():
    """Strategic analysis should not claim parallel mode is unsupported anymore."""
    text = (_REPO_ROOT / "docs" / "14_strategic_analysis.md").read_text(encoding="utf-8")
    assert "parallel 宣稱支援但 renderer 完全沒做" not in text


def test_docs_09_mcp_testing_checkbox_checked():
    """Validation checklist should mark MCP tooling as tested."""
    text = (_REPO_ROOT / "docs" / "09_validation_checklist.md").read_text(encoding="utf-8")
    assert "- [x] MCP tools tested (tests/test_mcp.py)" in text


def test_ci_verifies_opa_sha256():
    """CI must verify OPA binary integrity via SHA-256."""
    text = (_REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert ".sha256" in text
    assert "sha256sum -c" in text or "shasum -a 256 -c" in text


def test_live_validation_script_resolves_workload_from_job_uid_label():
    """Kueue admission check should resolve Workload by job UID label (official guidance)."""
    text = (_REPO_ROOT / "scripts" / "validate_live_cluster.sh").read_text(encoding="utf-8")
    assert "kueue.x-k8s.io/job-uid" in text
    assert "JOB_UID=" in text


def test_live_validation_script_uses_internal_polling_timeout_for_argo_wait():
    """Argo wait should use internal polling timeout (no GNU timeout dependency)."""
    text = (_REPO_ROOT / "scripts" / "validate_live_cluster.sh").read_text(encoding="utf-8")
    assert "ARGO_TIMEOUT_SECONDS" in text
    assert "deadline=$((SECONDS + ARGO_TIMEOUT_SECONDS))" in text
    assert "timeout 120s argo wait" not in text


def test_live_validation_script_validates_timeout_overrides_as_integers():
    """Timeout env overrides should be validated before arithmetic expansion."""
    text = (_REPO_ROOT / "scripts" / "validate_live_cluster.sh").read_text(encoding="utf-8")
    assert "_require_non_negative_integer" in text
    assert "_require_non_negative_integer \"ARGO_TIMEOUT_SECONDS\"" in text
    assert "_require_non_negative_integer \"KUEUE_ADMISSION_TIMEOUT_SECONDS\"" in text
    assert "_require_non_negative_integer \"KUEUE_COMPLETION_TIMEOUT_SECONDS\"" in text


def test_live_validation_script_fails_fast_when_job_uid_missing():
    """Kueue admission diagnosis should fail fast when JOB_UID cannot be resolved."""
    text = (_REPO_ROOT / "scripts" / "validate_live_cluster.sh").read_text(encoding="utf-8")
    assert "Unable to read Job UID for" in text
    assert "kubectl auth can-i get jobs.batch" in text


def test_readme_k8s_smoke_namespace_override_documents_rbac_requirement():
    """README should explain namespace override requires matching runtime RBAC in that namespace."""
    text = (_REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "override requires equivalent runtime RBAC" in text
    assert "orbital-workflow-runner" in text


def test_argo_executor_rbac_manifest_exists_with_workflowtaskresults_permissions():
    """Runtime SA must be dedicated and allowed to create/patch workflowtaskresults."""
    manifest = _REPO_ROOT / "manifests" / "k8s" / "argo" / "00-workflow-executor-rbac.yaml"
    assert manifest.exists(), "Expected Argo executor RBAC manifest to exist"

    docs = [d for d in yaml.safe_load_all(manifest.read_text(encoding="utf-8")) if d]
    service_account = next((d for d in docs if d.get("kind") == "ServiceAccount"), None)
    role = next((d for d in docs if d.get("kind") == "Role"), None)
    role_binding = next((d for d in docs if d.get("kind") == "RoleBinding"), None)

    assert service_account is not None, "RBAC manifest must include a ServiceAccount document"
    assert role is not None, "RBAC manifest must include a Role document"
    assert role_binding is not None, "RBAC manifest must include a RoleBinding document"

    assert service_account["metadata"]["name"] == "orbital-workflow-runner"
    assert role["metadata"]["namespace"] == "orbital-demo"
    assert role_binding["metadata"]["namespace"] == "orbital-demo"
    assert role_binding["subjects"][0]["name"] == "orbital-workflow-runner"

    rules = role.get("rules", [])
    match = [
        r
        for r in rules
        if r.get("apiGroups") == ["argoproj.io"]
        and r.get("resources") == ["workflowtaskresults"]
        and set(r.get("verbs", [])) >= {"create", "patch"}
    ]
    assert match, "Role must grant create/patch on workflowtaskresults"


def test_kueue_demo_apply_applies_argo_executor_rbac():
    """Demo bootstrap script should apply Argo runtime RBAC for orbital-demo."""
    text = (_REPO_ROOT / "scripts" / "kueue_demo_apply.sh").read_text(encoding="utf-8")
    assert "manifests/k8s/argo/00-workflow-executor-rbac.yaml" in text
