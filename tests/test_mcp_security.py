"""Security tests for MCP server tools.

S-H1: MCP tools must reject paths outside allowed directories.
"""

import pytest


def test_validate_path_rejects_traversal():
    """Path traversal attempts must be rejected."""
    from orbital_mission_compiler.mcp.server import _validate_plan_path

    with pytest.raises(ValueError, match="outside allowed"):
        _validate_plan_path("../../etc/passwd")


def test_validate_path_rejects_absolute():
    """Absolute paths outside project must be rejected."""
    from orbital_mission_compiler.mcp.server import _validate_plan_path

    with pytest.raises(ValueError, match="outside allowed"):
        _validate_plan_path("/etc/passwd")


def test_validate_path_accepts_valid():
    """Valid plan paths should pass."""
    from orbital_mission_compiler.mcp.server import _validate_plan_path

    result = _validate_plan_path("configs/mission_plans/sample_maritime_surveillance.yaml")
    assert result.exists()


def test_validate_bundle_rejects_arbitrary():
    """Bundle path must be within configs/policies."""
    from orbital_mission_compiler.mcp.server import _validate_bundle_path

    with pytest.raises(ValueError, match="outside allowed"):
        _validate_bundle_path("/tmp/evil-rego")


def test_validate_bundle_accepts_default():
    """Default bundle path should pass."""
    from orbital_mission_compiler.mcp.server import _validate_bundle_path

    result = _validate_bundle_path("configs/policies")
    assert result.exists()


def test_validate_bundle_rejects_prefix_sibling():
    """configs/policies_evil must be rejected (common prefix bypass)."""
    from orbital_mission_compiler.mcp.server import _validate_bundle_path

    with pytest.raises(ValueError, match="outside allowed"):
        _validate_bundle_path("configs/policies_evil")
