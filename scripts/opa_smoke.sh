#!/usr/bin/env bash
set -euo pipefail

MISSION_FILE="${1:-configs/mission_plans/sample_gpu_cpu_fallback.yaml}"
BUNDLE_DIR="${2:-configs/policies}"

if ! command -v opa >/dev/null 2>&1; then
  echo "OPA CLI not found. See docs/07_installation_matrix.md for official installation details."
  exit 2
fi

TMPFILE="$(mktemp /tmp/orbital-plan.XXXXXX.json)"
trap 'rm -f "$TMPFILE"' EXIT

python3 - "${MISSION_FILE}" > "$TMPFILE" <<'PYSMOKE'
from pathlib import Path
import json, yaml, sys
plan = yaml.safe_load(Path(sys.argv[1]).read_text(encoding='utf-8'))
print(json.dumps(plan))
PYSMOKE

echo "Running OPA policy evaluation against ${MISSION_FILE}"
opa eval   --format=pretty   --stdin-input   --data "${BUNDLE_DIR}"   'data.orbitalmission' < "$TMPFILE"
