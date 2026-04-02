#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
OUT_DIR="${OUT_DIR:-out/rendered}"

mkdir -p "${OUT_DIR}"

${PYTHON_BIN} -m orbital_mission_compiler.cli render-argo   --input configs/mission_plans/sample_maritime_surveillance.yaml   --output-dir "${OUT_DIR}/maritime"

${PYTHON_BIN} -m orbital_mission_compiler.cli render-argo   --input configs/mission_plans/sample_gpu_cpu_fallback.yaml   --output-dir "${OUT_DIR}/fallback"

find "${OUT_DIR}" -type f | sort
