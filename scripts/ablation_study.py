"""Run the ablation study and print results.

Usage:
    python scripts/ablation_study.py
    make ablation

The transcript this prints is the backing data for the schema-only / policy-only /
combined comparison in `docs/experiments/2026-07-07-opa-vs-baseline.md`, so it opens
with what the numbers can be attributed to. Two of those things are not in the
commit: the OPA binary, which is the engine under test and is resolved from PATH,
and the Rego pack, which is what the policy arm actually evaluates. Both are folded
in below -- a table produced against a different OPA build or an edited policy is a
different measurement, and without these lines nothing in the output says so.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from orbital_mission_compiler.ablation import (
    POLICY_BUNDLE,
    format_results_table,
    run_ablation_study,
)
from orbital_mission_compiler.policy import opa_available
from orbital_mission_compiler.provenance import emit

REPO = Path(__file__).resolve().parent.parent


def opa_version() -> str:
    """The OPA build that produced the policy arm, read from the binary.

    Returns "unknown" rather than raising, and says which failure it was: a table
    whose engine version is unrecorded is still worth printing, but it must not be
    printed as though the version had been confirmed.
    """
    binary = shutil.which("opa")
    if binary is None:
        return "not on PATH"
    try:
        proc = subprocess.run(
            [binary, "version"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unknown ({exc})"
    if proc.returncode != 0:
        return f"unknown (opa version exited {proc.returncode})"
    for line in proc.stdout.splitlines():
        if line.lower().startswith("version:"):
            return f"{line.split(':', 1)[1].strip()} ({binary})"
    return f"unknown (unrecognised output) ({binary})"


def main() -> None:
    if not opa_available():
        print("ERROR: OPA CLI not found. Install OPA to run the ablation study.")
        print("  See: https://www.openpolicyagent.org/docs/latest/#1-download-opa")
        print("  Verify the downloaded binary checksum before running it.")
        raise SystemExit(1)

    # sorted(): glob order is filesystem order, and the digest has to be the same
    # on two machines holding the same files.
    rego = tuple(sorted((REPO / POLICY_BUNDLE).glob("*.rego")))
    emit(
        Path(__file__),
        repo=REPO,
        inputs=rego,
        environment=(("opa", opa_version()),),
        # The result is a property of the policy pack and the engine, not of the
        # host: this arm counts which plans are rejected, not how fast they are.
        include_host=False,
    )

    print("Running ablation study: schema-only vs policy-only vs combined...")
    print()
    results = run_ablation_study()
    table = format_results_table(results)
    print(table)
    print()
    print("Done.")


if __name__ == "__main__":
    main()
