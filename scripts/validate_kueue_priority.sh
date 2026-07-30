#!/usr/bin/env bash
# validate_kueue_priority.sh — prove that mission priority (via a Kueue
# WorkloadPriorityClass) drives admission ORDER, isolated from creation order.
#
# Method (reverse submission order):
#   1. A ClusterQueue with cpu nominalQuota=1 (one cpu=1 Job admissible at a time).
#   2. A blocker Job holds that quota.
#   3. Submit the LOW-priority Job FIRST, then the HIGH-priority Job.
#   4. Both are PENDING (quota held). Delete the blocker.
#   5. Kueue admits the higher-priority PENDING workload first. If HIGH is admitted
#      before LOW despite being submitted later, priority (not arrival order) decided.
#
# The Jobs are rendered by the compiler (`render-kueue --priority-class`), so this
# validates the compiler's own output, not a hand-written manifest.
set -uo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
NS="${NS:-mission-prio}"
LQ="${LQ:-mission-prio-lq}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
MANIFESTS="${HERE}/manifests/k8s/kueue/priority-ordering"
OUT="${OUT:-${HERE}/out/kueue-priority}"
rm -rf "$OUT"; mkdir -p "$OUT"

PASS=0; FAIL=0
LOW_JOB=""; HIGH_JOB=""   # set mid-run; initialised so the cleanup trap is set -u safe
report() { if [ "$1" = PASS ]; then echo "[PASS] $2"; PASS=$((PASS+1)); else echo "[FAIL] $2"; FAIL=$((FAIL+1)); fi; }

# Unconditional teardown: runs on normal exit AND on interrupt (Ctrl-C / timeout),
# so the experiment never leaves the namespace, queue, or cluster-scoped classes behind.
cleanup() {
  echo "=== cleanup ==="
  kubectl delete job "$LOW_JOB" "$HIGH_JOB" prio-blocker -n "$NS" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete -f "${OUT}/wpc/workload-priority-classes.yaml" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete -f "${MANIFESTS}/00-namespace-and-queue.yaml" --ignore-not-found >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

wl_for_job() { # $1 job name -> workload name (via job-uid label)
  local uid; uid=$(kubectl get job "$1" -n "$NS" -o jsonpath='{.metadata.uid}' 2>/dev/null)
  [ -z "$uid" ] && return
  kubectl get workloads.kueue.x-k8s.io -n "$NS" -l "kueue.x-k8s.io/job-uid=${uid}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}
wl_admitted() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Admitted")].status}' 2>/dev/null; }
wl_priority() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.spec.priority}' 2>/dev/null; }
wait_wl() { # $1 job name -> echo workload name once it exists (up to 30s)
  local w=""; local d=$((SECONDS+30))
  while [ $SECONDS -lt $d ]; do w=$(wl_for_job "$1"); [ -n "$w" ] && break; sleep 2; done
  echo "$w"
}

echo "=== 0. prerequisites ==="
command -v kubectl >/dev/null 2>&1 && report PASS "kubectl available" || { report FAIL "kubectl missing"; exit 2; }
kubectl get deployment -n kueue-system kueue-controller-manager >/dev/null 2>&1 \
  && report PASS "Kueue controller present" || report FAIL "Kueue controller missing"

echo "=== 1. apply namespace + ClusterQueue (cpu=1) + LocalQueue ==="
kubectl apply -f "${MANIFESTS}/00-namespace-and-queue.yaml" >/dev/null && report PASS "queue applied" || report FAIL "queue apply failed"

echo "=== 2. emit + apply the WorkloadPriorityClasses from the compiler ==="
PYTHONPATH="${HERE}/src" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-kueue \
  --input "${MANIFESTS}/plan-high.yaml" --output-dir "${OUT}/wpc" --queue "$LQ" --namespace "$NS" \
  --emit-priority-classes --priority-class --policy-engine baseline >/dev/null 2>&1
kubectl apply -f "${OUT}/wpc/workload-priority-classes.yaml" >/dev/null \
  && report PASS "WorkloadPriorityClasses applied" || report FAIL "WPC apply failed"
kubectl get workloadpriorityclass mission-critical mission-normal >/dev/null 2>&1 \
  && report PASS "mission-critical + mission-normal exist" || report FAIL "priority classes missing"

echo "=== 3. render HIGH (priority 90) and LOW (priority 50) Jobs ==="
for p in high low; do
  PYTHONPATH="${HERE}/src" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-kueue \
    --input "${MANIFESTS}/plan-${p}.yaml" --output-dir "${OUT}/${p}" --queue "$LQ" --namespace "$NS" \
    --priority-class --policy-engine baseline >/dev/null 2>&1
done
HIGH_JOB_FILE=$(find "${OUT}/high" -name '*-kueue.yaml' | head -1)
LOW_JOB_FILE=$(find "${OUT}/low" -name '*-kueue.yaml' | head -1)

echo "=== 4. blocker holds the cpu=1 quota ==="
kubectl apply -f "${MANIFESTS}/01-blocker-job.yaml" >/dev/null
BLOCK_WL=$(wait_wl prio-blocker)
d=$((SECONDS+60)); ba=""
while [ $SECONDS -lt $d ]; do ba=$(wl_admitted "$BLOCK_WL"); [ "$ba" = "True" ] && break; sleep 2; done
[ "$ba" = "True" ] && report PASS "blocker admitted (holds quota)" || report FAIL "blocker not admitted"

echo "=== 5. submit LOW first, then HIGH (reverse of priority) ==="
LOW_JOB=$(kubectl create -f "$LOW_JOB_FILE" -o jsonpath='{.metadata.name}' 2>/dev/null)
LOW_WL=$(wait_wl "$LOW_JOB")
echo "  LOW  job=$LOW_JOB workload=$LOW_WL priority=$(wl_priority "$LOW_WL")"
sleep 6   # ensure LOW creationTimestamp strictly precedes HIGH
HIGH_JOB=$(kubectl create -f "$HIGH_JOB_FILE" -o jsonpath='{.metadata.name}' 2>/dev/null)
HIGH_WL=$(wait_wl "$HIGH_JOB")
echo "  HIGH job=$HIGH_JOB workload=$HIGH_WL priority=$(wl_priority "$HIGH_WL")"

echo "=== 6. both PENDING while blocker holds quota ==="
sleep 5
la=$(wl_admitted "$LOW_WL"); ha=$(wl_admitted "$HIGH_WL")
# Require both Workloads to actually EXIST and be un-admitted -- a missing Workload
# (empty name) must NOT be mistaken for "pending".
if [ -n "$LOW_WL" ] && [ -n "$HIGH_WL" ] && [ "$la" != "True" ] && [ "$ha" != "True" ]; then
  report PASS "LOW and HIGH both pending under full quota"
else
  report FAIL "expected both workloads present and pending, got LOW=($LOW_WL)=$la HIGH=($HIGH_WL)=$ha"
fi

echo "=== 7. free quota (delete blocker); the higher-priority pending workload wins ==="
kubectl delete -f "${MANIFESTS}/01-blocker-job.yaml" --ignore-not-found >/dev/null 2>&1
FIRST=""; d=$((SECONDS+60))
while [ $SECONDS -lt $d ]; do
  ha=$(wl_admitted "$HIGH_WL"); la=$(wl_admitted "$LOW_WL")
  if [ "$ha" = "True" ]; then FIRST="HIGH"; HIGH_LOW_AT_ADMIT="$la"; break; fi
  if [ "$la" = "True" ]; then FIRST="LOW"; break; fi
  sleep 2
done
echo "  first admitted after quota freed: ${FIRST:-<none>} (LOW status at that moment: ${HIGH_LOW_AT_ADMIT:-n/a})"
if [ "$FIRST" = "HIGH" ]; then
  report PASS "HIGH (mission-critical, submitted LAST) admitted before LOW -> priority drove ordering"
else
  report FAIL "expected HIGH first, got ${FIRST:-none} -> could not distinguish priority from creation order"
fi

echo "" ; echo "=== Summary ===" ; echo "PASS: ${PASS}  FAIL: ${FAIL}"
# Teardown runs via the EXIT trap (also covers interrupts).
[ "$FAIL" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
