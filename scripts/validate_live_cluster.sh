#!/usr/bin/env bash
# validate_live_cluster.sh — End-to-end live cluster validation.
# Compiles the validation mission plan through the full pipeline,
# submits to Argo and Kueue, and reports PASS/FAIL per step.
set -uo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
MISSION_FILE="configs/mission_plans/validation_live_cluster.yaml"
NAMESPACE="orbital-demo"
QUEUE="orbital-demo-local"
OUT_DIR="out/live-validation"
ARGO_OUT="${OUT_DIR}/argo"
KUEUE_OUT="${OUT_DIR}/kueue"

PASS=0
FAIL=0

report() {
  local status="$1"
  local label="$2"
  if [ "${status}" = "PASS" ]; then
    echo "[PASS] ${label}"
    PASS=$((PASS + 1))
  else
    echo "[FAIL] ${label}"
    FAIL=$((FAIL + 1))
  fi
}

# ── Step 1: Check prerequisites ────────────────────────────────────────

echo "=== Checking prerequisites ==="

if command -v kubectl >/dev/null 2>&1; then
  report PASS "kubectl available"
else
  report FAIL "kubectl not found"
fi

if command -v argo >/dev/null 2>&1; then
  report PASS "argo CLI available"
else
  report FAIL "argo CLI not found"
fi

# ── Step 2: Check controllers ──────────────────────────────────────────

echo ""
echo "=== Checking cluster controllers ==="

if command -v kubectl >/dev/null 2>&1; then
  if kubectl get deployment -n argo workflow-controller >/dev/null 2>&1; then
    ARGO_READY=$(kubectl get deployment -n argo workflow-controller -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "${ARGO_READY}" -ge 1 ] 2>/dev/null; then
      report PASS "Argo Workflow controller running (${ARGO_READY} replica(s))"
    else
      report FAIL "Argo Workflow controller not ready"
    fi
  else
    report FAIL "Argo Workflow controller not found"
  fi

  if kubectl get deployment -n kueue-system kueue-controller-manager >/dev/null 2>&1; then
    KUEUE_READY=$(kubectl get deployment -n kueue-system kueue-controller-manager -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "${KUEUE_READY}" -ge 1 ] 2>/dev/null; then
      report PASS "Kueue controller running (${KUEUE_READY} replica(s))"
    else
      report FAIL "Kueue controller not ready"
    fi
  else
    report FAIL "Kueue controller not found"
  fi
else
  echo "Skipping controller checks (kubectl not available)"
fi

# ── Step 3: Compile mission plan ───────────────────────────────────────

echo ""
echo "=== Compiling validation mission plan ==="

mkdir -p "${OUT_DIR}"

if PYTHONPATH="${PYTHONPATH:-src}" ${PYTHON_BIN} -m orbital_mission_compiler.cli compile \
    --input "${MISSION_FILE}" \
    --output "${OUT_DIR}/compiled.yaml" >/dev/null 2>&1; then
  report PASS "Mission plan compiled"
else
  report FAIL "Mission plan compilation failed"
fi

# ── Step 4: Render and submit Argo Workflow ────────────────────────────

echo ""
echo "=== Argo Workflow ==="

rm -rf "${ARGO_OUT}"
mkdir -p "${ARGO_OUT}"

if PYTHONPATH="${PYTHONPATH:-src}" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-argo \
    --input "${MISSION_FILE}" \
    --output-dir "${ARGO_OUT}" >/dev/null 2>&1; then
  report PASS "Argo Workflow rendered"
else
  report FAIL "Argo Workflow rendering failed"
fi

if command -v argo >/dev/null 2>&1; then
  shopt -s nullglob
  files=("${ARGO_OUT}"/*.yaml)
  shopt -u nullglob
  if [ ${#files[@]} -eq 0 ]; then
    report FAIL "No YAML files to lint"
  elif argo lint "${files[@]}" >/dev/null 2>&1; then
    report PASS "Argo lint passed"
  else
    report FAIL "Argo lint failed"
  fi
fi

ARGO_FILE=$(find "${ARGO_OUT}" -name '*.yaml' -print -quit 2>/dev/null)
if [ -n "${ARGO_FILE}" ] && command -v argo >/dev/null 2>&1; then
  echo "Submitting Argo Workflow to cluster ..."
  if WF_NAME=$(argo submit "${ARGO_FILE}" -n "${NAMESPACE}" -o name 2>/dev/null); then
    report PASS "Argo Workflow submitted: ${WF_NAME}"

    echo "Waiting for Argo Workflow completion (up to 120s) ..."
    if argo wait "${WF_NAME}" -n "${NAMESPACE}" --timeout 120s >/dev/null 2>&1; then
      WF_STATUS=$(argo get "${WF_NAME}" -n "${NAMESPACE}" -o json 2>/dev/null | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('phase','Unknown'))" 2>/dev/null || echo "Unknown")
      if [ "${WF_STATUS}" = "Succeeded" ]; then
        report PASS "Argo Workflow completed: ${WF_STATUS}"
      else
        report FAIL "Argo Workflow status: ${WF_STATUS}"
      fi
    else
      report FAIL "Argo Workflow did not complete within timeout"
    fi

    # Cleanup
    argo delete "${WF_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 || true
  else
    report FAIL "Argo Workflow submission failed"
  fi
else
  echo "Skipping Argo submission (no rendered file or argo CLI unavailable)"
fi

# ── Step 5: Render and submit Kueue Job ────────────────────────────────

echo ""
echo "=== Kueue Job ==="

rm -rf "${KUEUE_OUT}"
mkdir -p "${KUEUE_OUT}"

if PYTHONPATH="${PYTHONPATH:-src}" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-kueue \
    --input "${MISSION_FILE}" \
    --output-dir "${KUEUE_OUT}" \
    --queue "${QUEUE}" \
    --namespace "${NAMESPACE}" >/dev/null 2>&1; then
  report PASS "Kueue Job rendered"
else
  report FAIL "Kueue Job rendering failed"
fi

JOB_FILE=$(find "${KUEUE_OUT}" -name '*-kueue.yaml' -print -quit 2>/dev/null)
if [ -n "${JOB_FILE}" ] && command -v kubectl >/dev/null 2>&1; then
  echo "Submitting Kueue Job to cluster ..."
  if JOB_NAME=$(kubectl create -f "${JOB_FILE}" -o jsonpath='{.metadata.name}' 2>/dev/null); then
    report PASS "Kueue Job submitted: ${JOB_NAME}"

    echo "Checking Kueue admission (up to 60s) ..."
    ADMITTED="false"
    for _ in $(seq 1 12); do
      ADMITTED_STATUS=$(kubectl get workloads -l "job-name=${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.items[*].status.conditions[?(@.type=="Admitted")].status}' 2>/dev/null || true)
      if echo "${ADMITTED_STATUS}" | grep -q "True"; then
        ADMITTED="true"
        break
      fi
      sleep 5
    done

    if [ "${ADMITTED}" = "true" ]; then
      report PASS "Kueue admission confirmed"
    else
      report FAIL "Kueue admission not confirmed within timeout"
    fi

    echo "Waiting for Job completion (up to 120s) ..."
    if kubectl wait --for=condition=complete "job/${JOB_NAME}" -n "${NAMESPACE}" --timeout=120s >/dev/null 2>&1; then
      report PASS "Kueue Job completed"
    else
      report FAIL "Kueue Job did not complete within timeout"
    fi

    # Cleanup
    kubectl delete "job/${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  else
    report FAIL "Kueue Job submission failed"
  fi
else
  echo "Skipping Kueue submission (no rendered file or kubectl unavailable)"
fi

# ── Summary ────────────────────────────────────────────────────────────

echo ""
echo "=== Summary ==="
echo "PASS: ${PASS}  FAIL: ${FAIL}"

if [ "${FAIL}" -gt 0 ]; then
  echo "RESULT: FAIL"
  exit 1
else
  echo "RESULT: PASS"
  exit 0
fi
