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

# The identifier is substituted into object names, a label value, a label selector
# and the YAML templates, so an override carrying a newline, a comma, an equals or a
# slash would break the manifest, silently widen what cleanup deletes, or produce a
# name the API server refuses. Held to what all four uses accept: an RFC 1123 label.
# The 32-character cap leaves room for the longest name built from it,
# "orbital-<id>-mission-critical", inside the 63 a label value allows.
case "${RUN_ID}" in
  # Unreachable while the assignment above uses :- , which substitutes the default
  # for an empty override as well as an unset one. Kept because without it an empty
  # value would fall through to the accepting branch rather than be caught.
  "")            RUN_ID_BAD="it is empty" ;;
  [!a-z0-9]*)    RUN_ID_BAD="it must start with a lowercase letter or digit" ;;
  *[!a-z0-9])    RUN_ID_BAD="it must end with a lowercase letter or digit" ;;
  *[!a-z0-9-]*)  RUN_ID_BAD="it may hold only lowercase letters, digits and '-'" ;;
  *)             RUN_ID_BAD="" ;;
esac
if [ -z "${RUN_ID_BAD}" ] && [ "${#RUN_ID}" -gt 32 ]; then
  RUN_ID_BAD="it is longer than 32 characters"
fi
if [ -n "${RUN_ID_BAD}" ]; then
  printf 'RUN_ID is not usable: %s\n' "${RUN_ID_BAD}" >&2
  printf 'RESULT: FAIL\n'
  exit 2
fi
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
# --emit-priority-classes writes one class per ORCHIDE tier, so the run creates four
# whether or not the proof reads them all back. Checking only the two it reads left
# the other two applied over whatever was already there.
ALL_CLASSES="${CLASS_PREFIX}mission-critical ${CLASS_PREFIX}mission-high ${CLASS_PREFIX}mission-normal ${CLASS_PREFIX}mission-low"
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
# v1beta2 records the resolved class as a reference rather than a bare name, and the
# group is what says the value came from the WorkloadPriorityClass this proof emitted.
# It matters because the fallback is silent: with no such class Kueue takes the pod
# template's own PriorityClass instead, writes that into the same spec.priority, and
# sorts the queue by it just as well -- so the run would still admit HIGH first while
# proving nothing about the compiler's mapping.
wl_class() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.spec.priorityClassRef.name}' 2>/dev/null; }
wl_class_group() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.spec.priorityClassRef.group}' 2>/dev/null; }
wl_class_kind() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.spec.priorityClassRef.kind}' 2>/dev/null; }
wl_created() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.metadata.creationTimestamp}' 2>/dev/null; }
# Queued-and-waiting stated positively. Inferring it from "Admitted is not True" also
# accepts a workload that is structurally inadmissible, and a lookup that failed.
wl_quota_reserved() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="QuotaReserved")].status}' 2>/dev/null; }
wl_quota_reason() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="QuotaReserved")].reason}' 2>/dev/null; }
wl_admitted_at() { kubectl get workload "$1" -n "$NS" -o jsonpath='{.status.conditions[?(@.type=="Admitted")].lastTransitionTime}' 2>/dev/null; }
# The label naming the mapping that chose a class, read off two objects the compiler
# produces separately: the Job (via --priority-class) and the WorkloadPriorityClass
# itself (via --emit-priority-classes). Comparing those two is the point -- comparing
# either one against the constant that stamped it only asks the module whether it
# agrees with itself.
#
# The key is written in the escaped bracket form even though it has no dot today. A
# dotted key in the plain form resolves to empty with status 0, so a prefix moved to
# a DNS subdomain, which is the Kubernetes convention, would silently turn every
# reading below into "the label is missing" and blame the compiler for it.
# Read through `-o json` and pick the key out in Python rather than with kubectl's
# jsonpath. Two reasons, both of which turn a real failure into a silent empty string
# under jsonpath: a key containing a dot needs escaping and resolves to empty with
# status 0 without it, so moving the prefix to a DNS subdomain -- the Kubernetes
# convention -- would quietly make every reading below say "missing". And an absent
# label, a label whose value is the empty string (which the API server accepts), and a
# failed lookup all come back as the same empty string, so the check cannot say which
# it saw. This reports <absent> and <empty> as distinct, non-empty tokens that no
# comparison against a real version can accidentally satisfy.
MAPPING_LABEL="orbital/priority-mapping-version"
_label_of() { # $1 kubectl args... -> the label value, or <absent>/<empty>/<unreadable>
  kubectl "$@" -o json 2>/dev/null | "${PYTHON_BIN}" -c '
import json, sys
key = sys.argv[1]
try:
    obj = json.load(sys.stdin)
except Exception:
    print("<unreadable>"); raise SystemExit(0)
labels = (obj.get("metadata") or {}).get("labels") or {}
if key not in labels:
    print("<absent>")
else:
    print(labels[key] if labels[key] != "" else "<empty>")
' "${MAPPING_LABEL}" 2>/dev/null || echo "<unreadable>"
}
job_mapping() { _label_of get job "$1" -n "$NS"; }
class_mapping() { _label_of get workloadpriorityclass "$1"; }
class_value() { kubectl get workloadpriorityclass "$1" -o jsonpath='{.value}' 2>/dev/null; }
wait_wl() { # $1 job name -> echo workload name once it exists (up to 30s)
  local w=""; local d=$((SECONDS+30))
  while [ $SECONDS -lt $d ]; do w=$(wl_for_job "$1"); [ -n "$w" ] && break; sleep 2; done
  echo "$w"
}

echo "=== run ${RUN_ID} ==="
echo "  namespace=${NS} clusterQueue=${CQ} classes=${HIGH_CLASS},${LOW_CLASS}"
# The full object name, and whether the tree it came from was clean. A short hash
# names a commit only until the repository grows, and a capture taken from a dirty
# tree cannot be rebuilt from any commit at all -- which matters here, because the
# captured run is what this experiment produces.
echo "  compiler commit: $(git -C "$HERE" rev-parse HEAD 2>/dev/null || echo unknown)"
echo "  working tree   : $( [ -n "$(git -C "$HERE" status --porcelain 2>/dev/null)" ] && echo 'DIRTY -- this capture cannot be rebuilt from a commit' || echo 'clean' )"
echo "  harness sha256 : $(sha256sum "$0" 2>/dev/null | cut -d' ' -f1 || echo unknown)"
# Which interpreter, and which copy of the compiler it actually imported. The commit
# above names the tree; it does not establish that the tree is what ran. `python -c`
# puts the current directory ahead of PYTHONPATH, so a stray orbital_mission_compiler/
# beside the caller shadows the checked-out one, and every value below would then come
# from code no commit describes while the header still cited a commit.
echo "  interpreter    : $("${PYTHON_BIN}" -c 'import sys; print(sys.executable)' 2>/dev/null || echo unknown)"
echo "  compiler module: $(PYTHONPATH="${HERE}/src" "${PYTHON_BIN}" -c 'import orbital_mission_compiler.compiler as m; print(m.__file__)' 2>/dev/null || echo unresolved)"

# The environment the result is about. Written by the run rather than typed into the
# capture afterwards: a version recorded by hand is a claim about the cluster, not
# evidence from it, and this transcript is what the experiment produces.
echo "=== environment ==="
echo "  kubectl client : $(kubectl version --client -o json 2>/dev/null | "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin)["clientVersion"]["gitVersion"])' 2>/dev/null || echo unknown)"
echo "  kube-apiserver : $(kubectl version -o json 2>/dev/null | "${PYTHON_BIN}" -c 'import json,sys; print(json.load(sys.stdin)["serverVersion"]["gitVersion"])' 2>/dev/null || echo unknown)"
echo "  nodes          : $(kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}={.status.nodeInfo.kubeletVersion} {end}' 2>/dev/null || echo unknown)"
echo "  kueue image    : $(kubectl get deployment -n kueue-system kueue-controller-manager -o jsonpath='{.spec.template.spec.containers[?(@.name=="manager")].image}' 2>/dev/null || echo unknown)"
echo "  kueue imageID  : $(kubectl get pods -n kueue-system -l control-plane=controller-manager -o jsonpath='{.items[0].status.containerStatuses[?(@.name=="manager")].imageID}' 2>/dev/null || echo unknown)"
# The sort this experiment measures is affected by Kueue's own configuration, so the
# gates and the config are captured rather than assumed to be defaults.
echo "  kueue gates    : $(kubectl get deployment -n kueue-system kueue-controller-manager -o jsonpath='{range .spec.template.spec.containers[?(@.name=="manager")].args[*]}{@}{"\n"}{end}' 2>/dev/null | grep -- '--feature-gates' || echo '(none set; built-in defaults apply)')"
kubectl get configmap -n kueue-system kueue-manager-config -o yaml > "${OUT}/kueue-manager-config.yaml" 2>/dev/null \
  && echo "  kueue config   : captured to $(basename "${OUT}")/kueue-manager-config.yaml" \
  || echo "  kueue config   : not readable"

echo "=== 0. prerequisites ==="
command -v kubectl >/dev/null 2>&1 && report PASS "kubectl available" || { report FAIL "kubectl missing"; exit 2; }
kubectl get deployment -n kueue-system kueue-controller-manager >/dev/null 2>&1 \
  && report PASS "Kueue controller present" || report FAIL "Kueue controller missing"

echo "=== 0b. nothing this run is about to create already exists ==="
COLLIDE=""
absent namespace "$NS" || COLLIDE="${COLLIDE} namespace/${NS}"
absent clusterqueue "$CQ" || COLLIDE="${COLLIDE} clusterqueue/${CQ}"
absent resourceflavor "$FLAVOR" || COLLIDE="${COLLIDE} resourceflavor/${FLAVOR}"
for cls in ${ALL_CLASSES}; do
  absent workloadpriorityclass "$cls" || COLLIDE="${COLLIDE} wpc/${cls}"
done
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

# Read every emitted value back, not only the two this proof goes on to use. Checking
# the pair the experiment reads leaves the other two tiers unpinned anywhere: the unit
# suite asserts the four are strictly decreasing, which a changed value can satisfy, so
# a mapping could be altered without bumping the version -- the one thing the version
# exists to make detectable -- and both the tests and this run would still pass.
VALUES_BAD=""
for spec in "mission-critical:400" "mission-high:300" "mission-normal:200" "mission-low:100"; do
  cls="${CLASS_PREFIX}${spec%%:*}"; want="${spec##*:}"; got=$(class_value "$cls")
  [ "$got" = "$want" ] || VALUES_BAD="${VALUES_BAD} ${cls}=${got:-<none>}(want ${want})"
done
if [ -z "$VALUES_BAD" ]; then
  report PASS "all four emitted classes carry the mapped values (400/300/200/100)"
else
  report FAIL "class values off the mapping:${VALUES_BAD}"
fi

# And that the classes now on the cluster are the ones this tree describes. Read from
# the source rather than hard-coded, so a deliberate bump to v3 does not fail the run;
# what it catches is a cluster holding a generation the tree no longer emits.
MAPPING_VERSION=$(PYTHONPATH="${HERE}/src" "${PYTHON_BIN}" -c \
  'from orbital_mission_compiler.compiler import PRIORITY_CLASS_MAPPING_VERSION as v; print(v)' \
  2>"${OUT}/mapping-version.err")
if [ -z "$MAPPING_VERSION" ]; then
  # Distinguished because the two have different culprits: a compiler that stopped
  # exposing the constant, and an interpreter that could not import the compiler at
  # all. Reporting the second as the first sends the reader to the wrong file.
  if [ -s "${OUT}/mapping-version.err" ]; then
    report FAIL "the compiler could not be imported by ${PYTHON_BIN} (see ${OUT}/mapping-version.err)"
  else
    report FAIL "the compiler exposes no mapping version to compare against"
  fi
else
  CLASS_MAP_BAD=""
  for spec in mission-critical mission-high mission-normal mission-low; do
    cls="${CLASS_PREFIX}${spec}"; got=$(class_mapping "$cls")
    [ "$got" = "$MAPPING_VERSION" ] || CLASS_MAP_BAD="${CLASS_MAP_BAD} ${cls}=${got}"
  done
  if [ -z "$CLASS_MAP_BAD" ]; then
    report PASS "all four classes are labelled with the mapping this tree emits (${MAPPING_VERSION})"
  else
    report FAIL "classes labelled off ${MAPPING_VERSION}:${CLASS_MAP_BAD}"
  fi
fi

echo "=== 3. render HIGH (priority 90) and LOW (priority 50) Jobs ==="
RENDER_BAD=""
for p in high low; do
  PYTHONPATH="${HERE}/src" "${PYTHON_BIN}" -m orbital_mission_compiler.cli render-kueue \
    --input "${MANIFESTS}/plan-${p}.yaml" --output-dir "${OUT}/${p}" --queue "$LQ" --namespace "$NS" \
    --priority-class --priority-class-prefix "$CLASS_PREFIX" --policy-engine baseline \
    >"${OUT}/render-${p}.log" 2>&1 || RENDER_BAD="${RENDER_BAD} ${p}(exit $?)"
done
HIGH_JOB_FILE=$(find "${OUT}/high" -name '*-kueue.yaml' | head -1)
LOW_JOB_FILE=$(find "${OUT}/low" -name '*-kueue.yaml' | head -1)
# The render had no assertion of its own, so a failure here was only noticed several
# steps later, as a Workload that never appeared. Both the exit status and the artifact
# are checked, because a command can succeed and still write nothing this run can use.
[ -n "$HIGH_JOB_FILE" ] || RENDER_BAD="${RENDER_BAD} high(no -kueue.yaml)"
[ -n "$LOW_JOB_FILE" ] || RENDER_BAD="${RENDER_BAD} low(no -kueue.yaml)"
if [ -z "$RENDER_BAD" ]; then
  report PASS "both Jobs rendered by the compiler"
else
  report FAIL "render failed:${RENDER_BAD} (logs in ${OUT})"
fi

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
# A Job and the class it names come from two different compiler entry points
# (--priority-class and --emit-priority-classes) and arrive as separate objects, so
# their agreeing is a statement about what the cluster holds. Comparing either one
# against the constant that stamped it only asks the module whether it agrees with
# itself. A Job outliving a rename is the case the label exists to make findable, and
# it is findable only if the Job and the class name the same generation.
if [ -z "$HIGH_JOB" ] || [ -z "$LOW_JOB" ]; then
  # Section 6 makes the same distinction for the Workloads. A Job that was never
  # created reads back as no label at all, which must not be reported as a compiler
  # that forgot to stamp one.
  report FAIL "no Job to read a mapping version from: HIGH=(${HIGH_JOB}) LOW=(${LOW_JOB})"
else
  HM=$(job_mapping "$HIGH_JOB"); LM=$(job_mapping "$LOW_JOB")
  HCM=$(class_mapping "$HIGH_CLASS"); LCM=$(class_mapping "$LOW_CLASS")
  # <absent>, <empty> and <unreadable> are reported as themselves; an equality test
  # alone would accept two objects that are both missing the label.
  case "$HM" in "<"*) MAPPING_READABLE=no ;; *) MAPPING_READABLE=yes ;; esac
  if [ "$MAPPING_READABLE" = yes ] && [ "$HM" = "$HCM" ] && [ "$LM" = "$LCM" ] && [ "$HM" = "$LM" ]; then
    report PASS "each Job carries the mapping its own class carries (${HM})"
  else
    report FAIL "mapping labels disagree: HIGH job=${HM} class=${HCM}; LOW job=${LM} class=${LCM}"
  fi
fi
# Read the reference on both Workloads. The ordering claim rests on two priorities, and
# a LOW whose value arrived through the pod-template fallback would leave the comparison
# measuring something other than this mapping.
REF_BAD=""
for pair in "HIGH ${HIGH_WL}" "LOW ${LOW_WL}"; do
  set -- $pair
  g=$(wl_class_group "$2"); k=$(wl_class_kind "$2")
  { [ "$g" = "kueue.x-k8s.io" ] && [ "$k" = "WorkloadPriorityClass" ]; } \
    || REF_BAD="${REF_BAD} $1(group=${g:-<none>} kind=${k:-<none>})"
done
if [ -z "$REF_BAD" ]; then
  report PASS "both references are WorkloadPriorityClasses, not Pod PriorityClasses"
else
  report FAIL "unexpected class reference:${REF_BAD}"
fi
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
lq=$(wl_quota_reserved "$LOW_WL"); hq=$(wl_quota_reserved "$HIGH_WL")
lr=$(wl_quota_reason "$LOW_WL"); hr=$(wl_quota_reason "$HIGH_WL")
# Both Workloads must EXIST, be un-admitted, and say so themselves through a
# QuotaReserved condition that is present and False. A missing Workload must not be
# mistaken for a pending one, and neither must a workload that is waiting for
# something other than quota.
if [ -n "$LOW_WL" ] && [ -n "$HIGH_WL" ] \
   && [ "$la" != "True" ] && [ "$ha" != "True" ] \
   && [ "$lq" = "False" ] && [ "$hq" = "False" ]; then
  report PASS "LOW and HIGH both waiting on quota (QuotaReserved=False; LOW ${lr:-<no reason>}, HIGH ${hr:-<no reason>})"
else
  report FAIL "expected both workloads present and waiting on quota, got LOW=($LOW_WL) admitted=${la:-<none>} quotaReserved=${lq:-<none>}(${lr:-<none>}) HIGH=($HIGH_WL) admitted=${ha:-<none>} quotaReserved=${hq:-<none>}(${hr:-<none>})"
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

echo "=== 7b. LOW was queued behind HIGH, not unable to run at all ==="
# Winning a race against something that could never have run is not winning. Without
# this, any asymmetry that made LOW permanently inadmissible -- a larger request, a
# flavor that does not match, a class name that resolves to nothing -- produces exactly
# the PASS above, and the earlier steps cannot tell the two apart: "not admitted yet"
# and "never admissible" both satisfy them.
d=$((SECONDS+120)); la=""
while [ $SECONDS -lt $d ]; do la=$(wl_admitted "$LOW_WL"); [ "$la" = "True" ] && break; sleep 3; done
if [ "$la" = "True" ]; then
  report PASS "LOW admitted once HIGH released the quota -> it was queued, not inadmissible"
else
  report FAIL "LOW never admitted (admitted=${la:-<none>}, quotaReserved=$(wl_quota_reserved "$LOW_WL"):$(wl_quota_reason "$LOW_WL")) -> the ordering result compares against a workload that may never have been runnable"
fi
# Second-resolution condition timestamps, kept because they are the cluster's own
# account of the order rather than the polling loop's.
echo "  admitted at: HIGH=$(wl_admitted_at "$HIGH_WL") LOW=$(wl_admitted_at "$LOW_WL")"

# The objects the claim is about, kept so a reader can check the resource shapes were
# symmetric, what quota each reserved, and that neither carried a requeue backoff --
# none of which is recoverable once the namespace goes.
kubectl get workloads.kueue.x-k8s.io -n "$NS" -o yaml > "${OUT}/workloads.yaml" 2>/dev/null \
  && echo "  workloads captured to $(basename "${OUT}")/workloads.yaml" || true
kubectl get clusterqueue "$CQ" -o yaml > "${OUT}/clusterqueue.yaml" 2>/dev/null \
  && echo "  defaulted ClusterQueue captured to $(basename "${OUT}")/clusterqueue.yaml" || true

echo "" ; echo "=== Summary ===" ; echo "PASS: ${PASS}  FAIL: ${FAIL}"
# Teardown runs via the EXIT trap (also covers interrupts).
[ "$FAIL" -eq 0 ] && { echo "RESULT: PASS"; exit 0; } || { echo "RESULT: FAIL"; exit 1; }
