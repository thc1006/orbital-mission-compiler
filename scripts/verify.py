from pathlib import Path
import compileall
import sys
import yaml

REQUIRED = [
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "docs/00_transcript_grounding.md",
    "docs/04_architecture.md",
    "docs/07_installation_matrix.md",
    "docs/12_phase2_local_demo.md",
    "docs/14_traceability_matrix.md",
    "src/orbital_mission_compiler/compiler.py",
    "tests/test_compiler.py",
    "tests/test_traceability.py",
    "configs/mission_plans/sample_gpu_cpu_fallback.yaml",
    "manifests/examples/argo-gpu-cpu-fallback.yaml",
]

root = Path(__file__).resolve().parents[1]
missing = [p for p in REQUIRED if not (root / p).exists()]
if missing:
    print("Missing required files:")
    for p in missing:
        print(f"- {p}")
    sys.exit(1)

ok = compileall.compile_dir(str(root / "src"), quiet=1)
if not ok:
    print("Python syntax verification failed.")
    sys.exit(1)

with (root / "manifests/examples/argo-gpu-cpu-fallback.yaml").open("r", encoding="utf-8") as f:
    obj = yaml.safe_load(f)
if obj.get("kind") != "Workflow":
    print("manifests/examples/argo-gpu-cpu-fallback.yaml is not an Argo Workflow manifest")
    sys.exit(1)

print("Basic syntax verification passed.")
print("NOTE: external installs, Kubernetes bootstrap, OPA runtime, and GPU execution were not run here.")
