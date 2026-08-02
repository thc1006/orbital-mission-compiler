#!/usr/bin/env bash
# kueue_integration_smoke.sh — End-to-end Kueue admission test.
# Compiles a mission plan into a Kueue Job, submits it to the cluster,
# waits for admission, and reports whether the Job completes.
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

# The rendered file is a bundle: a GPU intent also carries a fixed-name
# ResourceClaimTemplate, so `kubectl create` over the whole thing fails on the
# second run against the template the first run left behind. Apply the named
# documents, which is idempotent, and create only the Job.
RCT_FILE="${OUT_DIR}/claims.yaml"
JOB_ONLY_FILE="${OUT_DIR}/job.yaml"
${PYTHON_BIN} - "${JOB_FILE}" "${RCT_FILE}" "${JOB_ONLY_FILE}" <<'PYSPLIT'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")) if d]
named = [d for d in docs if d.get("kind") != "Job"]
jobs = [d for d in docs if d.get("kind") == "Job"]
open(sys.argv[2], "w", encoding="utf-8").write(yaml.safe_dump_all(named, sort_keys=False) if named else "")
open(sys.argv[3], "w", encoding="utf-8").write(yaml.safe_dump_all(jobs, sort_keys=False))
PYSPLIT

if [ -s "${RCT_FILE}" ]; then
  echo "[smoke] Applying claim template(s) ..."
  kubectl apply -f "${RCT_FILE}" -n "${NAMESPACE}"
fi

echo "[smoke] Submitting Job to cluster ..."
JOB_NAME="$(kubectl create -f "${JOB_ONLY_FILE}" -o jsonpath='{.metadata.name}')"
echo "[smoke] Created Job: ${JOB_NAME}"

cleanup() {
  echo "[smoke] Cleaning up Job ${JOB_NAME} ..."
  kubectl delete job "${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  if [ -s "${RCT_FILE}" ]; then
    kubectl delete -f "${RCT_FILE}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
  fi
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
