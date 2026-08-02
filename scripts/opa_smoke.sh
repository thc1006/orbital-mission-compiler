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

# Gate on the DECISION, not just on whether OPA ran: `opa eval` returns exit 0
# even for a denied plan, so this smoke must inspect the deny set itself. The
# --fail-defined flag exits non-zero when the query is defined, i.e. when at
# least one deny rule fired -- turning this into a real admission check.
echo "Gating on policy decision (the deny set must be empty) ..."
if opa eval --fail-defined --format=raw --stdin-input --data "${BUNDLE_DIR}" 'data.orbitalmission.deny[_]' < "$TMPFILE"; then
  echo "POLICY PASS: no deny rules fired for ${MISSION_FILE}"
else
  echo "POLICY DENIED: ${MISSION_FILE} violates one or more policy rules (see messages above)" >&2
  exit 1
fi
