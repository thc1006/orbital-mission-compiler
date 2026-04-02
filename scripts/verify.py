from __future__ import annotations

import compileall
from pathlib import Path


def main() -> int:
    required = [
        Path("README.md"),
        Path("AGENTS.md"),
        Path("CLAUDE.md"),
        Path("docs/00_transcript_grounding.md"),
        Path("docs/07_installation_matrix.md"),
        Path("src/orbital_mission_compiler/cli.py"),
        Path("configs/mission_plans/sample_maritime_surveillance.yaml"),
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        print("Missing required files:", missing)
        return 1

    if not compileall.compile_dir("src", quiet=1):
        print("Python syntax compilation failed")
        return 1

    print("Basic syntax verification passed.")
    print("NOTE: external installs, Kubernetes bootstrap, and GPU execution were not run here.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
