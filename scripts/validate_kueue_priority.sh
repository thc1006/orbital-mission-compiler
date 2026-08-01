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
#
# Everything this run creates carries a run-specific name and an ownership label, and
# teardown deletes only what it made. An earlier version used fixed names and deleted
# them unconditionally, which on a cluster that already had a `mission-prio` namespace
# or a `mission-critical` class would have adopted someone else's object and then
# removed it -- deleting a namespace takes everything inside it.
set -uo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
MANIFESTS="${HERE}/manifests/k8s/kueue/priority-ordering"
OUT="${OUT:-${HERE}/out/kueue-priority}"

# One identifier per run, so two runs on one cluster cannot collide and neither can
# touch anything that was already there. Override RUN_ID to reproduce a name.
RUN_ID="${RUN_ID:-r$(date +%s)$$}"
NS="prio-${RUN_ID}"
FLAVOR="prio-flavor-${RUN_ID}"
CQ="prio-cq-${RUN_ID}"
LQ="prio-lq-${RUN_ID}"
BLOCKER="prio-blocker-${RUN_ID}"
# The classes are cluster-scoped, so they get the run in their name too, through the
# compiler's own --priority-class-prefix rather than a second naming scheme.
CLASS_PREFIX="orbital-${RUN_ID}-"
HIGH_CLASS="${CLASS_PREFIX}mission-critical"
LOW_CLASS="${CLASS_PREFIX}mission-normal"
OWNER_LABEL="orbital.test/run-id=${RUN_ID}"

rm -rf "$OUT"; mkdir -p "$OUT"

PASS=0; FAIL=0
LOW_JOB=""; HIGH_JOB=""   # set mid-run; initialised so the cleanup trap is set -u safe
CREATED_QUEUES=0; CREATED_WPCS=0   # only tear down what was actually applied
report() { if [ "$1" = PASS ]; then echo "[PASS] $2"; PASS=$((PASS+1)); else echo "[FAIL] $2"; FAIL=$((FAIL+1)); fi; }

# Teardown removes only objects carrying this run's ownership label. Deleting by label
# rather than by manifest is what keeps a pre-existing object of the same kind safe.
cleanup() {
  echo "=== cleanup (run ${RUN_ID}) ==="
  kubectl delete job "$LOW_JOB" "$HIGH_JOB" "$BLOCKER" -n "$NS" --ignore-not-found >/dev/null 2>&1 || true
  if [ "$CREATED_WPCS" -eq 1 ]; then
    kubectl delete workloadpriorityclass -l "$OWNER_LABEL" --ignore-not-found >/dev/null 2>&1 || true
  fi
  if [ "$CREATED_QUEUES" -eq 1 ]; then
    kubectl delete localqueue -n "$NS" -l "$OWNER_LABEL" --ignore-not-found >/dev/null 2>&1 || true
    kubectl delete clusterqueue -l "$OWNER_LABEL" --ignore-not-found >/dev/null 2>&1 || true
    kubectl delete resourceflavor -l "$OWNER_LABEL" --ignore-not-found >/dev/null 2>&1 || true
    kubectl delete namespace -l "$OWNER_LABEL" --ignore-not-found >/dev/null 2>&1 || true
  fi
}
# EXIT covers the normal path. INT and TERM clean up and then stop: a handler that
# returns lets the script carry on and create the resources it has just deleted.
trap cleanup EXIT
trap 'cleanup; trap - EXIT; exit 130' INT
trap 'cleanup; trap - EXIT; exit 143' TERM

# Fill the run's names into a template. One substitution table feeds setup, render,
# lookup and teardown, so an override cannot leave the queue in one namespace and the
# Jobs in another.
render_template() { # $1 template path -> stdout
  "${PYTHON_BIN}" - "$1" "$NS" "$FLAVOR" "$CQ" "$LQ" "$BLOCKER" "$RUN_ID" <<'PY'
import sys
path, ns, flavor, cq, lq, blocker, run_id = sys.argv[1:8]
text = open(path, encoding="utf-8").read()
for token, value in (
    ("__NS__", ns), ("__FLAVOR__", flavor), ("__CQ__", cq),
    ("__LQ__", lq), ("__BLOCKER__", blocker), ("__RUN_ID__", run_id),
):
    text = text.replace(token, value)
sys.stdout.write(text)
PY
}

absent() { # $1 kind, $2 name, [$3 namespace] -> 0 when the object does not exist
  if [ $# -ge 3 ]; then kubectl get "$1" "$2" -n "$3" >/dev/null 2>&1; else kubectl get "$1" "$2" >/dev/null 2>&1; fi
  [ $? -ne 0 ]
}

wl_for_job() { # $1 job name -> workload name (via job-uid label)
  local uid; uid=$(kubectl get job "$1" -n "$NS" -o jsonpath='{.metadata.uid}' 2>/dev/null)
  [ -z "$uid" ] && return
  kubectl get workloads.kueue.x-k8s.io -n "$NS" -l "kueue.x-k8s.io/job-uid=${uid}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}
wl_admitted() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Admitted")].status}' 2>/dev/null; }
wl_priority() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.spec.priority}' 2>/dev/null; }
wl_class() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.spec.priorityClassName}' 2>/dev/null; }
wl_created() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null; }
wait_wl() { # $1 job name -> echo workload name once it exists (up to 30s)
  local w=""; local d=$((SECONDS+30))
  while [ $SECONDS -lt $d ]; do w=$(wl_for_job "$1"); [ -n "$w" ] && break; sleep 2; done
  echo "$w"
}

echo "=== run ${RUN_ID} ==="
echo "  namespace=${NS} clusterQueue=${CQ} classes=${HIGH_CLASS},${LOW_CLASS}"
echo "  compiler commit: $(git -C "$HERE" rev-parse --short HEAD 2>/dev/null || echo unknown)$( [ -n "$(git -C "$HERE" status --porcelain 2>/dev/null)" ] && echo ' (dirty tree)' )"

echo "=== 0. prerequisites ==="
command -v kubectl >/dev/null 2>&1 && report PASS "kubectl available" || { report FAIL "kubectl missing"; exit 2; }
kubectl get deployment -n kueue-system kueue-controller-manager >/dev/null 2>&1 \
  && report PASS "Kueue controller present" || report FAIL "Kueue controller missing"

echo "=== 0b. nothing this run is about to create already exists ==="
COLLIDE=""
absent namespace "$NS" || COLLIDE="${COLLIDE} namespace/${NS}"
absent clusterqueue "$CQ" || COLLIDE="${COLLIDE} clusterqueue/${CQ}"
absent resourceflavor "$FLAVOR" || COLLIDE="${COLLIDE} resourceflavor/${FLAVOR}"
absent workloadpriorityclass "$HIGH_CLASS" || COLLIDE="${COLLIDE} wpc/${HIGH_CLASS}"
absent workloadpriorityclass "$LOW_CLASS" || COLLIDE="${COLLIDE} wpc/${LOW_CLASS}"
if [ -z "$COLLIDE" ]; then
  report PASS "no pre-existing object carries this run's names"
else
  report FAIL "refusing to adopt existing object(s):${COLLIDE}"
  echo "RESULT: FAIL"; exit 1
fi

echo "=== 1. apply namespace + ClusterQueue (cpu=1) + LocalQueue ==="
if render_template "${MANIFESTS}/00-namespace-and-queue.yaml" | kubectl apply -f - >/dev/null; then
  CREATED_QUEUES=1; report PASS "queue applied"
else
  report FAIL "queue apply failed"
fi

echo "=== 2. emit + apply the WorkloadPriorityClasses from the compiler ==="
PYTHONPATH="${HERE}/src" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-kueue \
  --input "${MANIFESTS}/plan-high.yaml" --output-dir "${OUT}/wpc" --queue "$LQ" --namespace "$NS" \
  --emit-priority-classes --priority-class --priority-class-prefix "$CLASS_PREFIX" \
  --policy-engine baseline >/dev/null 2>&1
# The compiler does not know about this run, so the ownership label is added here.
if "${PYTHON_BIN}" - "${OUT}/wpc/workload-priority-classes.yaml" "$RUN_ID" <<'PY' | kubectl apply -f - >/dev/null
import sys, yaml
path, run_id = sys.argv[1], sys.argv[2]
docs = [d for d in yaml.safe_load_all(open(path, encoding="utf-8")) if d]
for d in docs:
    d.setdefault("metadata", {}).setdefault("labels", {})["orbital.test/run-id"] = run_id
yaml.safe_dump_all(docs, sys.stdout)
PY
then
  CREATED_WPCS=1; report PASS "WorkloadPriorityClasses applied"
else
  report FAIL "WPC apply failed"
fi
kubectl get workloadpriorityclass "$HIGH_CLASS" "$LOW_CLASS" >/dev/null 2>&1 \
  && report PASS "${HIGH_CLASS} + ${LOW_CLASS} exist" || report FAIL "priority classes missing"

# The ordering claim rests on these two values, so read them back rather than trusting
# the mapping: a rename that silently changed a value would otherwise pass unnoticed.
HIGH_VALUE=$(kubectl get workloadpriorityclass "$HIGH_CLASS" -o jsonpath='{.value}' 2>/dev/null)
LOW_VALUE=$(kubectl get workloadpriorityclass "$LOW_CLASS" -o jsonpath='{.value}' 2>/dev/null)
if [ "$HIGH_VALUE" = "400" ] && [ "$LOW_VALUE" = "200" ]; then
  report PASS "class values as mapped (${HIGH_CLASS}=400, ${LOW_CLASS}=200)"
else
  report FAIL "unexpected class values: ${HIGH_CLASS}=${HIGH_VALUE:-<none>} ${LOW_CLASS}=${LOW_VALUE:-<none>}"
fi

echo "=== 3. render HIGH (priority 90) and LOW (priority 50) Jobs ==="
for p in high low; do
  PYTHONPATH="${HERE}/src" ${PYTHON_BIN} -m orbital_mission_compiler.cli render-kueue \
    --input "${MANIFESTS}/plan-${p}.yaml" --output-dir "${OUT}/${p}" --queue "$LQ" --namespace "$NS" \
    --priority-class --priority-class-prefix "$CLASS_PREFIX" --policy-engine baseline >/dev/null 2>&1
done
HIGH_JOB_FILE=$(find "${OUT}/high" -name '*-kueue.yaml' | head -1)
LOW_JOB_FILE=$(find "${OUT}/low" -name '*-kueue.yaml' | head -1)

echo "=== 4. blocker holds the cpu=1 quota ==="
render_template "${MANIFESTS}/01-blocker-job.yaml" | kubectl apply -f - >/dev/null
BLOCK_WL=$(wait_wl "$BLOCKER")
d=$((SECONDS+60)); ba=""
while [ $SECONDS -lt $d ]; do ba=$(wl_admitted "$BLOCK_WL"); [ "$ba" = "True" ] && break; sleep 2; done
[ "$ba" = "True" ] && report PASS "blocker admitted (holds quota)" || report FAIL "blocker not admitted"

echo "=== 5. submit LOW first, then HIGH (reverse of priority) ==="
LOW_JOB=$(kubectl create -f "$LOW_JOB_FILE" -o jsonpath='{.metadata.name}' 2>/dev/null)
LOW_WL=$(wait_wl "$LOW_JOB")
echo "  LOW  job=$LOW_JOB workload=$LOW_WL priority=$(wl_priority "$LOW_WL") class=$(wl_class "$LOW_WL")"
sleep 6   # give the clock room; the assertion below reads the real timestamps
HIGH_JOB=$(kubectl create -f "$HIGH_JOB_FILE" -o jsonpath='{.metadata.name}' 2>/dev/null)
HIGH_WL=$(wait_wl "$HIGH_JOB")
echo "  HIGH job=$HIGH_JOB workload=$HIGH_WL priority=$(wl_priority "$HIGH_WL") class=$(wl_class "$HIGH_WL")"

echo "=== 5b. the chain the claim rests on ==="
HP=$(wl_priority "$HIGH_WL"); LP=$(wl_priority "$LOW_WL")
[ "$HP" = "400" ] && [ "$LP" = "200" ] \
  && report PASS "workload priorities resolved (HIGH=400 LOW=200)" \
  || report FAIL "workload priorities: HIGH=${HP:-<none>} LOW=${LP:-<none>}"
HC=$(wl_class "$HIGH_WL"); LC=$(wl_class "$LOW_WL")
[ "$HC" = "$HIGH_CLASS" ] && [ "$LC" = "$LOW_CLASS" ] \
  && report PASS "workloads reference the emitted classes" \
  || report FAIL "class references: HIGH=${HC:-<none>} LOW=${LC:-<none>}"
# Arrival order is the thing priority has to beat, so read it rather than assume the
# sleep achieved it.
HT=$(wl_created "$HIGH_WL"); LT=$(wl_created "$LOW_WL")
if [ -n "$HT" ] && [ -n "$LT" ] && [ "$LT" \< "$HT" ]; then
  report PASS "LOW was created before HIGH (${LT} < ${HT})"
else
  report FAIL "arrival order not established: LOW=${LT:-<none>} HIGH=${HT:-<none>}"
fi

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
kubectl delete job "$BLOCKER" -n "$NS" --ignore-not-found >/dev/null 2>&1
FIRST=""; d=$((SECONDS+60))
while [ $SECONDS -lt $d ]; do
  ha=$(wl_admitted "$HIGH_WL"); la=$(wl_admitted "$LOW_WL")
  # Both true at the first observation means the order happened between two polls and
  # is no longer knowable. Checking HIGH first would report it as a win either way.
  if [ "$ha" = "True" ] && [ "$la" = "True" ]; then FIRST="BOTH"; break; fi
  if [ "$ha" = "True" ]; then FIRST="HIGH"; break; fi
  if [ "$la" = "True" ]; then FIRST="LOW"; break; fi
  sleep 2
done
echo "  first admitted after quota freed: ${FIRST:-<none>}"
case "$FIRST" in
  HIGH) report PASS "HIGH (${HIGH_CLASS}, submitted LAST) admitted before LOW -> priority drove ordering" ;;
  BOTH) report FAIL "both admitted within one poll -> order unobservable, not evidence either way" ;;
  LOW)  report FAIL "LOW admitted first -> creation order, not priority, decided" ;;
  *)    report FAIL "neither workload was admitted within the window" ;;
esac

echo "" ; echo "=== Summary ===" ; echo "PASS: ${PASS}  FAIL: ${FAIL}"
# Teardown runs via the EXIT trap (also covers interrupts).
[ "$FAIL" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
