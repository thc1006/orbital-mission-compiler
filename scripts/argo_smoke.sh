#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
MISSION_FILE="${1:-configs/mission_plans/sample_gpu_cpu_fallback.yaml}"
OUT_DIR="${2:-out/argo-smoke}"

mkdir -p "${OUT_DIR}"
${PYTHON_BIN} -m orbital_mission_compiler.cli render-argo --input "${MISSION_FILE}" --output-dir "${OUT_DIR}"

${PYTHON_BIN} - "${OUT_DIR}" <<'PYSMOKE'
from pathlib import Path
import sys, yaml
for p in Path(sys.argv[1]).glob('*.yaml'):
    obj = yaml.safe_load(p.read_text(encoding='utf-8'))
    assert obj['apiVersion'] == 'argoproj.io/v1alpha1', p
    assert obj['kind'] == 'Workflow', p
    assert 'spec' in obj and 'entrypoint' in obj['spec'], p
print('Python manifest sanity check passed.')
PYSMOKE

if command -v argo >/dev/null 2>&1; then
  echo "Running official Argo lint"
  argo lint "${OUT_DIR}"/*.yaml
else
  echo "argo CLI not found; skipped argo lint."
fi
