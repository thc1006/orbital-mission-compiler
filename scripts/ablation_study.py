"""Run the ablation study and print results.

Usage:
    python scripts/ablation_study.py
    make ablation
"""

from orbital_mission_compiler.ablation import (
    format_results_table,
    run_ablation_study,
)
from orbital_mission_compiler.policy import opa_available


def main() -> None:
    if not opa_available():
        print("ERROR: OPA CLI not found. Install OPA to run the ablation study.")
        print("  curl -L -o opa https://openpolicyagent.org/downloads/latest/opa_linux_amd64_static")
        raise SystemExit(1)

    print("Running ablation study: schema-only vs policy-only vs combined...")
    print()
    results = run_ablation_study()
    table = format_results_table(results)
    print(table)
    print()
    print("Done.")


if __name__ == "__main__":
    main()
