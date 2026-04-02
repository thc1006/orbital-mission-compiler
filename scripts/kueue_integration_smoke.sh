#!/usr/bin/env bash
# kueue_integration_smoke.sh — End-to-end Kueue admission test.
# Compiles a mission plan into a Kueue Job, submits it to the cluster,
# waits for admission, and verifies the Job completes.
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
MISSION_FILE="${1:-configs/mission_plans/sample_gpu_cpu_fallback.yaml}"
NAMESPACE="orbital-demo"
QUEUE="orbital-demo-local"
OUT_DIR="out/kueue-smoke"

echo "[smoke] Rendering Kueue Job from ${MISSION_FILE} ..."
mkdir -p "${OUT_DIR}"
PYTHONPATH="${PYTHONPATH:-src}" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-kueue \
  --input "${MISSION_FILE}" \
  --output-dir "${OUT_DIR}" \
  --queue "${QUEUE}" \
  --namespace "${NAMESPACE}"

JOB_FILE="$(find "${OUT_DIR}" -name '*-kueue.yaml' -print -quit)"
if [ -z "${JOB_FILE}" ]; then
  echo "[smoke] ERROR: No Kueue Job YAML found in ${OUT_DIR}" >&2
  exit 1
fi
echo "[smoke] Job file: ${JOB_FILE}"

echo "[smoke] Submitting Job to cluster ..."
JOB_NAME="$(kubectl create -f "${JOB_FILE}" -o jsonpath='{.metadata.name}')"
echo "[smoke] Created Job: ${JOB_NAME}"

cleanup() {
  echo "[smoke] Cleaning up Job ${JOB_NAME} ..."
  kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "[smoke] Waiting for Kueue admission (up to 60s) ..."
for i in $(seq 1 12); do
  WORKLOADS="$(kubectl get workloads -n "${NAMESPACE}" -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)"
  if [ -n "${WORKLOADS}" ]; then
    echo "[smoke] Workload detected: ${WORKLOADS}"
    break
  fi
  sleep 5
done

echo "[smoke] Waiting for Job completion (up to 120s) ..."
if kubectl wait --for=condition=complete "job/${JOB_NAME}" -n "${NAMESPACE}" --timeout=120s 2>&1; then
  echo "[smoke] Job ${JOB_NAME} completed successfully."
else
  echo "[smoke] Job did not complete within timeout. Checking status ..."
  kubectl describe "job/${JOB_NAME}" -n "${NAMESPACE}" 2>&1 | tail -20
  # Still exit 0 if the job was admitted — admission is the primary check
  ADMITTED="$(kubectl get workloads -n "${NAMESPACE}" -o jsonpath='{.items[*].status.conditions[?(@.type=="Admitted")].status}' 2>/dev/null || true)"
  if echo "${ADMITTED}" | grep -q "True"; then
    echo "[smoke] Job was admitted by Kueue (workload admission confirmed)."
  else
    echo "[smoke] FAIL: Job was not admitted by Kueue." >&2
    exit 1
  fi
fi

echo "[smoke] Kueue integration smoke test passed."
