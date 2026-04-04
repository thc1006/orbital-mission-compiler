"""Tests for benchmark_scaling.py CLI argument parsing and JSON output.

Validates the argparse interface, JSON output structure, --skip-policy
flag, and custom --sizes handling. Uses minimal sizes and iterations
to keep tests fast.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from orbital_mission_compiler.policy import opa_available

# The benchmark script lives in scripts/ and is not a package module.
# Load via importlib to avoid mutating sys.path for the whole test run.
_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "benchmark_scaling.py"
_spec = importlib.util.spec_from_file_location("benchmark_scaling", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

PLAN_SIZES = _mod.PLAN_SIZES
build_parser = _mod.build_parser
main = _mod.main
parse_sizes = _mod.parse_sizes


class TestParseSizes:
    """Tests for the parse_sizes helper."""

    def test_default_sizes_match_module_constant(self):
        """build_parser default (None) should cause main() to use PLAN_SIZES."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.sizes is None
        # When None, main() falls back to PLAN_SIZES — verify structural invariants
        assert isinstance(PLAN_SIZES, list)
        assert PLAN_SIZES
        assert all(isinstance(s, int) and s > 0 for s in PLAN_SIZES)

    def test_parse_single_size(self):
        """A single integer should produce a one-element list."""
        assert parse_sizes("10") == [10]

    def test_parse_multiple_sizes(self):
        """Comma-separated values should produce a matching list."""
        assert parse_sizes("10,50,100") == [10, 50, 100]

    def test_parse_sizes_strips_whitespace(self):
        """Whitespace around values should be ignored."""
        assert parse_sizes(" 10 , 50 ") == [10, 50]

    def test_parse_sizes_rejects_non_integer(self):
        """Non-integer values should raise ArgumentTypeError."""
        import argparse

        with pytest.raises(argparse.ArgumentTypeError, match="Invalid size value"):
            parse_sizes("10,abc")

    def test_parse_sizes_rejects_zero(self):
        """Zero should be rejected as a size."""
        import argparse

        with pytest.raises(argparse.ArgumentTypeError, match="must be a positive integer"):
            parse_sizes("0")

    def test_parse_sizes_rejects_negative(self):
        """Negative values should be rejected."""
        import argparse

        with pytest.raises(argparse.ArgumentTypeError, match="must be a positive integer"):
            parse_sizes("-5")

    def test_parse_sizes_rejects_empty(self):
        """An empty string should be rejected."""
        import argparse

        with pytest.raises(argparse.ArgumentTypeError, match="at least one positive integer"):
            parse_sizes("")


class TestBenchmarkJsonOutput:
    """Tests for JSON output via --output flag."""

    def test_json_output_structure(self, tmp_path: Path):
        """Running with --output should produce a well-formed JSON file."""
        out_file = tmp_path / "bench.json"
        main(["--sizes", "10", "--iterations", "1", "--skip-policy", "--output", str(out_file)])

        assert out_file.exists()
        data = json.loads(out_file.read_text(encoding="utf-8"))

        # Top-level structure
        assert "metadata" in data
        assert "results" in data

        # Metadata fields
        meta = data["metadata"]
        assert meta["sizes"] == [10]
        assert meta["iterations"] == 1
        assert meta["policy_skipped"] is True
        assert meta["timing_unit"] == "seconds"
        assert "timestamp" in meta

        # Results structure
        assert len(data["results"]) == 1
        row = data["results"][0]
        assert row["n_events"] == 10
        assert row["iterations"] == 1
        for phase in ("parse_mean", "parse_std", "compile_mean", "compile_std",
                       "argo_mean", "argo_std", "kueue_mean", "kueue_std"):
            assert phase in row
            assert isinstance(row[phase], (int, float))

    def test_json_output_nonexistent_parent(self, tmp_path: Path):
        """A path with missing parent directory should exit with error."""
        bad_path = tmp_path / "does_not_exist" / "bench.json"
        with pytest.raises(SystemExit):
            main(["--sizes", "10", "--iterations", "1", "--skip-policy", "--output", str(bad_path)])

    def test_no_json_when_output_omitted(self, capsys):
        """Without --output, no JSON file should be created."""
        main(["--sizes", "10", "--iterations", "1", "--skip-policy"])
        captured = capsys.readouterr()
        # Should have table output but no "Results written" line
        assert "Scaling benchmark" in captured.out
        assert "Results written" not in captured.out


class TestSkipPolicyFlag:
    """Tests for the --skip-policy flag."""

    def test_skip_policy_excludes_policy_fields(self, tmp_path: Path):
        """With --skip-policy, results should not contain policy_mean/policy_std."""
        out_file = tmp_path / "bench.json"
        main(["--sizes", "10", "--iterations", "1", "--skip-policy", "--output", str(out_file)])

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["metadata"]["policy_skipped"] is True
        row = data["results"][0]
        assert "policy_mean" not in row
        assert "policy_std" not in row

    @pytest.mark.skipif(not opa_available(), reason="OPA CLI not installed")
    def test_with_policy_includes_policy_fields(self, tmp_path: Path):
        """Without --skip-policy (and OPA available), results should contain policy fields."""
        out_file = tmp_path / "bench.json"
        main(["--sizes", "10", "--iterations", "1", "--output", str(out_file)])

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["metadata"]["policy_skipped"] is False
        row = data["results"][0]
        assert "policy_mean" in row
        assert "policy_std" in row


class TestCustomSizes:
    """Tests for custom --sizes values."""

    def test_two_sizes_produce_two_results(self, tmp_path: Path):
        """--sizes '10,50' should produce exactly 2 result entries."""
        out_file = tmp_path / "bench.json"
        main(["--sizes", "10,50", "--iterations", "1", "--skip-policy", "--output", str(out_file)])

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data["results"]) == 2
        assert data["results"][0]["n_events"] == 10
        assert data["results"][1]["n_events"] == 50
        assert data["metadata"]["sizes"] == [10, 50]

    def test_single_size_produces_one_result(self, tmp_path: Path):
        """--sizes '10' should produce exactly 1 result entry."""
        out_file = tmp_path / "bench.json"
        main(["--sizes", "10", "--iterations", "1", "--skip-policy", "--output", str(out_file)])

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert len(data["results"]) == 1
        assert data["results"][0]["n_events"] == 10
