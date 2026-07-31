#!/usr/bin/env bash
# validate_live_cluster.sh — End-to-end live cluster validation.
# Compiles the validation mission plan through the full pipeline,
# submits to Argo and Kueue, and reports PASS/FAIL per step.
set -uo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
MISSION_FILE="configs/mission_plans/validation_live_cluster.yaml"
NAMESPACE="${NAMESPACE:-orbital-demo}"
QUEUE="${QUEUE:-orbital-demo-local}"
ARGO_SERVICE_ACCOUNT="${ARGO_SERVICE_ACCOUNT:-orbital-workflow-runner}"
ARGO_TIMEOUT_SECONDS="${ARGO_TIMEOUT_SECONDS:-120}"
KUEUE_ADMISSION_TIMEOUT_SECONDS="${KUEUE_ADMISSION_TIMEOUT_SECONDS:-60}"
KUEUE_COMPLETION_TIMEOUT_SECONDS="${KUEUE_COMPLETION_TIMEOUT_SECONDS:-120}"
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

_require_non_negative_integer() {
  local name="$1"
  local value="$2"
  case "${value}" in
    ''|*[!0-9]*)
      echo "[FAIL] ${name} must be a non-negative integer (seconds), got: ${value}" >&2
      exit 2
      ;;
  esac
}

_require_non_negative_integer "ARGO_TIMEOUT_SECONDS" "${ARGO_TIMEOUT_SECONDS}"
_require_non_negative_integer "KUEUE_ADMISSION_TIMEOUT_SECONDS" "${KUEUE_ADMISSION_TIMEOUT_SECONDS}"
_require_non_negative_integer "KUEUE_COMPLETION_TIMEOUT_SECONDS" "${KUEUE_COMPLETION_TIMEOUT_SECONDS}"

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
  # Match both install layouts: the release manifest names the deployment
  # "workflow-controller"; the Helm chart prefixes it ("argo-workflows-workflow-controller").
  ARGO_CTRL_DEPLOY="$(
    kubectl get deployments -n argo \
      -o jsonpath='{range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null \
      | grep -E '(^|-)workflow-controller$' | head -n1
  )"
  if [ -n "${ARGO_CTRL_DEPLOY}" ]; then
    ARGO_READY=$(kubectl get deployment -n argo "${ARGO_CTRL_DEPLOY}" -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [ "${ARGO_READY}" -ge 1 ] 2>/dev/null; then
      report PASS "Argo Workflow controller running (${ARGO_CTRL_DEPLOY}, ${ARGO_READY} replica(s))"
    else
      report FAIL "Argo Workflow controller not ready (${ARGO_CTRL_DEPLOY})"
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

COMPILE_LOG="${OUT_DIR}/compile.log"
if PYTHONPATH="${PYTHONPATH:-src}" ${PYTHON_BIN} -m orbital_mission_compiler.cli compile \
    --input "${MISSION_FILE}" \
    --output "${OUT_DIR}/compiled.yaml" >"${COMPILE_LOG}" 2>&1; then
  report PASS "Mission plan compiled"
else
  report FAIL "Mission plan compilation failed (see ${COMPILE_LOG})"
  if [ -s "${COMPILE_LOG}" ]; then
    cat "${COMPILE_LOG}" >&2
  else
    echo "Compilation failed, but no compile log was created or it is empty: ${COMPILE_LOG}" >&2
  fi
fi

# ── Step 4: Render and submit Argo Workflow ────────────────────────────

echo ""
echo "=== Argo Workflow ==="

rm -rf "${ARGO_OUT}"
mkdir -p "${ARGO_OUT}"

ARGO_RENDER_LOG="${OUT_DIR}/argo-render.log"
if PYTHONPATH="${PYTHONPATH:-src}" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-argo \
    --input "${MISSION_FILE}" \
    --namespace "${NAMESPACE}" \
    --output-dir "${ARGO_OUT}" >"${ARGO_RENDER_LOG}" 2>&1; then
  report PASS "Argo Workflow rendered"
else
  report FAIL "Argo Workflow rendering failed (see ${ARGO_RENDER_LOG})"
  if [ -s "${ARGO_RENDER_LOG}" ]; then
    cat "${ARGO_RENDER_LOG}" >&2
  else
    echo "Argo render log is missing or empty: ${ARGO_RENDER_LOG}" >&2
  fi
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
  if WF_NAME=$(argo submit "${ARGO_FILE}" -n "${NAMESPACE}" --serviceaccount "${ARGO_SERVICE_ACCOUNT}" -o name 2>/dev/null); then
    WF_RAW_NAME="${WF_NAME#*/}"
    report PASS "Argo Workflow submitted: ${WF_NAME}"

    echo "Waiting for Argo Workflow completion (up to ${ARGO_TIMEOUT_SECONDS}s) ..."
    deadline=$((SECONDS + ARGO_TIMEOUT_SECONDS))
    WF_STATUS="Unknown"
    ARGO_TIMED_OUT="true"
    while [ "${SECONDS}" -lt "${deadline}" ]; do
      WF_STATUS="$(
        argo get "${WF_NAME}" -n "${NAMESPACE}" -o json 2>/dev/null \
          | ${PYTHON_BIN} -c "import sys,json; print(json.load(sys.stdin).get('status',{}).get('phase','Unknown'))" \
          2>/dev/null || echo "Unknown"
      )"
      if [ "${WF_STATUS}" = "Succeeded" ]; then
        report PASS "Argo Workflow completed: ${WF_STATUS}"
        ARGO_TIMED_OUT="false"
        break
      fi
      if [ "${WF_STATUS}" = "Failed" ] || [ "${WF_STATUS}" = "Error" ]; then
        report FAIL "Argo Workflow status: ${WF_STATUS}"
        ARGO_TIMED_OUT="false"
        break
      fi
      sleep 2
    done
    if [ "${ARGO_TIMED_OUT}" = "true" ]; then
      report FAIL "Argo Workflow did not complete within timeout (${ARGO_TIMEOUT_SECONDS}s)"
      POD_NAME="$(
        kubectl get pods \
          -n "${NAMESPACE}" \
          -l "workflows.argoproj.io/workflow=${WF_RAW_NAME}" \
          -o jsonpath='{.items[0].metadata.name}' \
          2>/dev/null || true
      )"
      argo get "${WF_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 && \
        argo get "${WF_NAME}" -n "${NAMESPACE}" || true
      if [ -n "${POD_NAME}" ]; then
        kubectl describe "pod/${POD_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 && \
          kubectl describe "pod/${POD_NAME}" -n "${NAMESPACE}" | tail -30 || true
      fi
    fi

    # Cleanup
    argo delete "${WF_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 || true
  else
    report FAIL "Argo Workflow submission failed (serviceaccount=${ARGO_SERVICE_ACCOUNT})"
  fi
else
  echo "Skipping Argo submission (no rendered file or argo CLI unavailable)"
fi

# Interrupt, timeout or a failed step would otherwise leave the Job, its Workload
# and the claim templates on the cluster, and the next run would collide with them.
cleanup_all() {
  [ -n "${JOB_NAME:-}" ] && kubectl delete "job/${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1
  [ -n "${RCT_FILE:-}" ] && [ -s "${RCT_FILE}" ] && kubectl delete -f "${RCT_FILE}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1
  [ -n "${WF_NAME:-}" ] && argo delete "${WF_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1
  return 0
}
trap cleanup_all EXIT INT TERM

# ── Step 5: Render and submit Kueue Job ────────────────────────────────

echo ""
echo "=== Kueue Job ==="

rm -rf "${KUEUE_OUT}"
mkdir -p "${KUEUE_OUT}"

KUEUE_RENDER_LOG="${OUT_DIR}/kueue-render.log"
if PYTHONPATH="${PYTHONPATH:-src}" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-kueue \
    --input "${MISSION_FILE}" \
    --output-dir "${KUEUE_OUT}" \
    --queue "${QUEUE}" \
    --namespace "${NAMESPACE}" >"${KUEUE_RENDER_LOG}" 2>&1; then
  report PASS "Kueue Job rendered"
else
  report FAIL "Kueue Job rendering failed (see ${KUEUE_RENDER_LOG})"
  if [ -s "${KUEUE_RENDER_LOG}" ]; then
    cat "${KUEUE_RENDER_LOG}" >&2
  else
    echo "Kueue render log is missing or empty: ${KUEUE_RENDER_LOG}" >&2
  fi
fi

JOB_FILE=$(find "${KUEUE_OUT}" -name '*-kueue.yaml' -print -quit 2>/dev/null)
if [ -n "${JOB_FILE}" ] && command -v kubectl >/dev/null 2>&1; then
  # The bundle mixes a fixed-name ResourceClaimTemplate with a generateName Job,
  # so `kubectl create` over the whole file is not repeatable: the second run
  # fails on the template that the first run left behind. Apply the named
  # documents, which is idempotent, and create only the Job.
  RCT_FILE="${KUEUE_OUT}/claims.yaml"
  JOB_ONLY_FILE="${KUEUE_OUT}/job.yaml"
  ${PYTHON_BIN} - "${JOB_FILE}" "${RCT_FILE}" "${JOB_ONLY_FILE}" <<'PYSPLIT'
import sys, yaml
docs = [d for d in yaml.safe_load_all(open(sys.argv[1], encoding="utf-8")) if d]
named = [d for d in docs if d.get("kind") != "Job"]
jobs = [d for d in docs if d.get("kind") == "Job"]
open(sys.argv[2], "w", encoding="utf-8").write(yaml.safe_dump_all(named, sort_keys=False) if named else "")
open(sys.argv[3], "w", encoding="utf-8").write(yaml.safe_dump_all(jobs, sort_keys=False))
PYSPLIT
  if [ -s "${RCT_FILE}" ]; then
    kubectl apply -f "${RCT_FILE}" -n "${NAMESPACE}" >/dev/null 2>&1 \
      && report PASS "Kueue claim template(s) applied" \
      || report FAIL "Kueue claim template(s) failed to apply"
  fi
  echo "Submitting Kueue Job to cluster ..."
  if JOB_NAME=$(kubectl create -f "${JOB_ONLY_FILE}" -o jsonpath='{.metadata.name}' 2>/dev/null); then
    report PASS "Kueue Job submitted: ${JOB_NAME}"

    echo "Checking Kueue admission (up to ${KUEUE_ADMISSION_TIMEOUT_SECONDS}s) ..."
    ADMITTED="false"
    WORKLOAD_NAME=""
    deadline=$((SECONDS + KUEUE_ADMISSION_TIMEOUT_SECONDS))
    JOB_UID="$(kubectl get job "${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.metadata.uid}' 2>/dev/null || true)"
    if [ -z "${JOB_UID}" ]; then
      report FAIL "Unable to read Job UID for ${JOB_NAME}; skipping Kueue admission lookup"
      kubectl get "job/${JOB_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 && \
        kubectl get "job/${JOB_NAME}" -n "${NAMESPACE}" -o yaml | tail -30 || true
      kubectl auth can-i get jobs.batch -n "${NAMESPACE}" >/dev/null 2>&1 && \
        kubectl auth can-i get jobs.batch -n "${NAMESPACE}" || true
    else
      while [ "${SECONDS}" -lt "${deadline}" ]; do
        if [ -n "${WORKLOAD_NAME}" ]; then
          ADMITTED_STATUS="$(kubectl get workload "${WORKLOAD_NAME}" -n "${NAMESPACE}" -o jsonpath='{.status.conditions[?(@.type=="Admitted")].status}' 2>/dev/null || true)"
        else
          WORKLOAD_NAME="$(
            kubectl get workloads.kueue.x-k8s.io \
              -n "${NAMESPACE}" \
              -l "kueue.x-k8s.io/job-uid=${JOB_UID}" \
              -o jsonpath='{.items[0].metadata.name}' \
              2>/dev/null || true
          )"
          ADMITTED_STATUS=""
        fi
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
        kubectl get workloads.kueue.x-k8s.io \
          -n "${NAMESPACE}" \
          -l "kueue.x-k8s.io/job-uid=${JOB_UID}" \
          >/dev/null 2>&1 && \
          kubectl get workloads.kueue.x-k8s.io \
            -n "${NAMESPACE}" \
            -l "kueue.x-k8s.io/job-uid=${JOB_UID}" || true
      fi
    fi

    # A Kueue Job runs one container, so a multi-step service is admitted as its
    # primary step and the rest are not in this Job. Name the step being waited
    # on, so "Kueue Job completed" is not read as "the service ran".
    EXECUTED_STEP="$(kubectl get "job/${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.metadata.annotations.orbital/executed-step}' 2>/dev/null || true)"
    SKIPPED_STEPS="$(kubectl get "job/${JOB_NAME}" -n "${NAMESPACE}" -o jsonpath='{.metadata.annotations.orbital/steps-not-in-this-job}' 2>/dev/null || true)"
    echo "Waiting for Job completion (up to ${KUEUE_COMPLETION_TIMEOUT_SECONDS}s) ..."
    if kubectl wait --for=condition=complete "job/${JOB_NAME}" -n "${NAMESPACE}" --timeout="${KUEUE_COMPLETION_TIMEOUT_SECONDS}s" >/dev/null 2>&1; then
      if [ -n "${SKIPPED_STEPS}" ]; then
        report PASS "Kueue Job completed (admission artifact: ran step '${EXECUTED_STEP}'; not in this Job: ${SKIPPED_STEPS} -- the Argo Workflow runs the full sequence)"
      else
        report PASS "Kueue Job completed"
      fi
    else
      report FAIL "Kueue Job did not complete within timeout"
      POD_NAME="$(kubectl get pods -n "${NAMESPACE}" -l "job-name=${JOB_NAME}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)"
      kubectl describe "job/${JOB_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 && \
        kubectl describe "job/${JOB_NAME}" -n "${NAMESPACE}" | tail -30 || true
      if [ -n "${POD_NAME}" ]; then
        kubectl describe "pod/${POD_NAME}" -n "${NAMESPACE}" >/dev/null 2>&1 && \
          kubectl describe "pod/${POD_NAME}" -n "${NAMESPACE}" | tail -30 || true
      fi
    fi

    # Cleanup. The claim templates go too: leaving them behind is what made a
    # second run of this script fail on a GPU plan.
    kubectl delete "job/${JOB_NAME}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
    if [ -s "${RCT_FILE}" ]; then
      kubectl delete -f "${RCT_FILE}" -n "${NAMESPACE}" --ignore-not-found >/dev/null 2>&1 || true
    fi
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
