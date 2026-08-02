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
# OUT, if the caller sets it, is a PARENT for this run's directory rather than the
# directory itself; see where OUT_ROOT is resolved below. Left unset it becomes a
# temporary directory this script creates and removes.

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
# How many races each arm runs. One race cannot separate a mechanism from a coin
# toss: under "the order is arbitrary" a single expected result has probability 1/2.
# Five per arm puts that at 1/32, and the run reports the tally rather than a sentence
# about it, so a reader can see how many attempts there were.
REPS="${REPS:-5}"
case "${REPS}" in
  ''|*[!0-9]*) printf 'REPS must be a positive integer, got %s\n' "${REPS}" >&2
               printf 'RESULT: FAIL\n'; exit 2 ;;
esac
[ "${REPS}" -ge 1 ] || { printf 'REPS must be at least 1\n' >&2; printf 'RESULT: FAIL\n'; exit 2; }

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

# The output directory is deleted at the start, so it must be one this script owns.
# It used to be whatever the caller put in OUT, deleted recursively with no check at
# all: an inherited CI variable, a wrapper passing the wrong argument or a typo like
# OUT=$HOME was a recursive delete of that path. Now the caller chooses a parent at
# most, the run works inside a subdirectory named for itself, and that subdirectory
# is only removed when it carries this script's own marker.
OUT_ROOT="${OUT:-}"
if [ -z "${OUT_ROOT}" ]; then
  OUT_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/kueue-priority.XXXXXXXX")" || {
    printf 'could not create a working directory\n' >&2; printf 'RESULT: FAIL\n'; exit 2; }
  OUT_ROOT_IS_OURS=1
else
  case "${OUT_ROOT}" in
    /) printf 'OUT must not be the filesystem root\n' >&2; printf 'RESULT: FAIL\n'; exit 2 ;;
  esac
  mkdir -p "${OUT_ROOT}" || { printf 'OUT is not creatable: %s\n' "${OUT_ROOT}" >&2; printf 'RESULT: FAIL\n'; exit 2; }
  OUT_ROOT_IS_OURS=0
fi
OUT="${OUT_ROOT}/run-${RUN_ID}"
SENTINEL="${OUT}/.kueue-priority-run"
# The sentinel names the run that owns the directory, and must be a regular file.
# `[ -e ]` alone said only "something this script might have made is here", so a
# second run sharing OUT and RUN_ID -- which line 31 documents as a way to
# reproduce a name -- deleted the first run's live output from under it. A
# directory or symlink called .kueue-priority-run satisfied it too, which let a
# planted path licence the deletion of whatever sat beside it.
if [ -e "$OUT" ]; then
  if [ ! -f "$SENTINEL" ] || [ "$(cat "$SENTINEL" 2>/dev/null)" != "owned-by-${RUN_ID}" ]; then
    printf '%s exists and is not this run\x27s to delete; refusing\n' "$OUT" >&2
    printf 'RESULT: FAIL\n'; exit 2
  fi
  printf 'a previous run with id %s left %s behind; reusing it\n' "${RUN_ID}" "$OUT" >&2
fi
rm -rf "$OUT" || { printf 'could not clear %s\n' "$OUT" >&2; printf 'RESULT: FAIL\n'; exit 2; }
# F7: unchecked, these two failures surfaced much later as a compiler that
# "exposes no mapping version" -- a filesystem error reported as a code fault.
mkdir -p "$OUT" || { printf 'could not create %s\n' "$OUT" >&2; printf 'RESULT: FAIL\n'; exit 2; }
printf 'owned-by-%s\n' "${RUN_ID}" > "$SENTINEL" || {
  printf 'could not write the ownership marker in %s\n' "$OUT" >&2
  printf 'RESULT: FAIL\n'; exit 2; }

PASS=0; FAIL=0
LOW_JOB=""; HIGH_JOB=""   # set mid-run; initialised so the cleanup trap is set -u safe
# Set once, immediately BEFORE the first thing that can create an object -- not after
# a successful apply. `kubectl apply -f` over a multi-document manifest is not one
# transaction: it creates the documents in order and can fail on a later one, so a
# flag set only on overall success left a namespace and a flavor on the cluster with
# teardown believing nothing had been made.
MUTATION_STARTED=0
CLEANUP_FAILED=0
report() { if [ "$1" = PASS ]; then echo "[PASS] $2"; PASS=$((PASS+1)); else echo "[FAIL] $2"; FAIL=$((FAIL+1)); fi; }

# Teardown removes only objects carrying this run's ownership label. Deleting by label
# rather than by manifest is what keeps a pre-existing object of the same kind safe.
CLEANED=0
cleanup() {
  [ "${CLEANED}" -eq 1 ] && return 0
  CLEANED=1
  # Removing the working directory is safe whatever happened: it is named for this
  # run and carries this script's marker.
  if [ "${OUT_ROOT_IS_OURS:-0}" -eq 1 ]; then rm -rf "${OUT_ROOT}"; else rm -rf "${OUT}"; fi
  [ "${MUTATION_STARTED}" -eq 1 ] || return 0
  echo "=== cleanup (run ${RUN_ID}) ==="
  # Every delete's failure is kept. Swallowing them let a run print RESULT: PASS
  # while leaving cluster-scoped WorkloadPriorityClasses behind, which is the
  # "safe to run anywhere" claim failing silently.
  # --wait=false: the default waits for finalizers, and every call now carries a
  # 30s request timeout. A terminating namespace routinely takes longer than that,
  # which would end an otherwise clean run at exit 3 for a delete that was working.
  _del() {
    if ! kget delete "$@" --ignore-not-found --wait=false >/dev/null 2>&1; then
      CLEANUP_FAILED=1
      echo "  cleanup could not delete: $*" >&2
    fi
  }
  # One name at a time, and empty ones skipped. `kubectl delete job "" a b` is not
  # a NotFound and --ignore-not-found does not cover it: kubectl aborts the whole
  # request list at the empty name, so `a` and `b` were never deleted -- and the
  # run reported a cleanup failure for objects that mostly did not exist while
  # genuinely leaving behind the ones that did.
  for _job in "$LOW_JOB" "$HIGH_JOB" "$BLOCKER"; do
    [ -n "$_job" ] && _del job "$_job" -n "$NS"
  done
  _del workloadpriorityclass -l "$OWNER_LABEL"
  _del localqueue -n "$NS" -l "$OWNER_LABEL"
  _del clusterqueue -l "$OWNER_LABEL"
  _del resourceflavor -l "$OWNER_LABEL"
  _del namespace -l "$OWNER_LABEL"
  # Say what is left rather than leaving the operator to discover it. The
  # cluster-scoped kinds are the ones that outlive the namespace.
  # The one check that verifies the leak this design exists to prevent, so a read
  # that failed must not read as "nothing left". Empty output from a failed lookup
  # is the same conflation `existence()` was rewritten to remove.
  local leftover
  if ! leftover=$(kget get workloadpriorityclass,clusterqueue,resourceflavor \
      -l "$OWNER_LABEL" -o name 2>/dev/null); then
    CLEANUP_FAILED=1
    echo "  could not verify whether anything from run ${RUN_ID} is left behind" >&2
  elif [ -n "$(printf '%s' "$leftover" | tr -d '[:space:]')" ]; then
    CLEANUP_FAILED=1
    echo "  STILL PRESENT after cleanup: $(printf '%s' "$leftover" | tr '\n' ' ')" >&2
  fi
}
# EXIT covers the normal path. INT and TERM clean up and then stop: a handler that
# returns lets the script carry on and create the resources it has just deleted.
# The verdict, called explicitly at the end so cleanup has already run and its
# outcome can enter it. The EXIT trap cleans but never judges: a prerequisite
# failure exits 2, and a trap that re-judged would turn that into 1.
finish() {
  if [ "$FAIL" -ne 0 ] && [ "$CLEANUP_FAILED" -ne 0 ]; then
    echo "RESULT: FAIL (and cleanup left objects behind -- see above)"; exit 1
  elif [ "$FAIL" -ne 0 ]; then
    echo "RESULT: FAIL"; exit 1
  elif [ "$CLEANUP_FAILED" -ne 0 ]; then
    # The experiment's own verdict stands; the run is still not safe to call clean,
    # because cluster-scoped objects outlive the namespace and this one leaked some.
    echo "RESULT: PASS, CLEANUP FAILED -- objects from this run may remain"; exit 3
  fi
  echo "RESULT: PASS"; exit 0
}

_warn_leftovers() {
  [ "${CLEANUP_FAILED}" -eq 0 ] || echo "cleanup left objects from run ${RUN_ID} behind" >&2
}
trap 'cleanup; _warn_leftovers' EXIT
trap 'cleanup; trap - EXIT; _warn_leftovers; exit 130' INT
trap 'cleanup; trap - EXIT; _warn_leftovers; exit 143' TERM

# Fill the run's names into a template. One substitution table feeds setup, render,
# lookup and teardown, so an override cannot leave the queue in one namespace and the
# Jobs in another.
render_template() { # $1 template path -> stdout
  # BLOCKER_OVERRIDE lets a repeat cycle name its own blocker without a second naming
  # scheme; unset, every template still gets the run's single blocker name.
  "${PYTHON_BIN}" - "$1" "$NS" "$FLAVOR" "$CQ" "$LQ" "${BLOCKER_OVERRIDE:-$BLOCKER}" "$RUN_ID" <<'PY'
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

# Three outcomes, not two. An earlier version ran `kubectl get` and read any
# non-zero exit as "the name is free", so Forbidden, an expired token, a TLS
# failure, a discovery error and a timeout all licensed the run to start creating
# objects on a cluster it had never successfully read. --ignore-not-found makes a
# missing object a success with empty output, which separates "not there" from
# "could not look".
# Every call goes through a bounded request timeout. Not one of them had one, so a
# wedged apiserver, a proxy that stops answering or an admission webhook that never
# returns left the harness waiting with no upper bound -- and it holds cluster-scoped
# objects while it waits. Wrapping the name rather than editing forty call sites is
# what makes it exhaustive; `command` is what keeps it from recursing.
K8S_TIMEOUT="${K8S_TIMEOUT:-30s}"
KUBECTL_BIN="$(command -v kubectl 2>/dev/null || true)"
kubectl() { command kubectl --request-timeout="${K8S_TIMEOUT}" "$@"; }
kget() { kubectl "$@"; }

existence() { # $1 kind, $2 name, [$3 namespace] -> absent | present | unreadable
  local out
  if [ $# -ge 3 ]; then
    out=$(kubectl get "$1" "$2" -n "$3" --ignore-not-found -o name 2>/dev/null) || { echo unreadable; return; }
  else
    out=$(kubectl get "$1" "$2" --ignore-not-found -o name 2>/dev/null) || { echo unreadable; return; }
  fi
  [ -z "$out" ] && echo absent || echo present
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
# One admission race, start to finish, reporting only who won. The detailed pass in
# sections 4-7b examines a single race; this repeats it, and repeats it for the control
# arm, where the only difference is which pair of rendered Jobs it is given.
#
# The blocker name is a parameter so cycles cannot collide with each other or with the
# detailed pass; everything it creates is deleted before it returns, and the namespace
# teardown is the backstop.
# kubectl aborts a whole request list at an empty name -- "resource name may not
# be empty", which is not a NotFound, so --ignore-not-found does not cover it and
# every name AFTER the empty one is never acted on. Any name here can be empty:
# `kubectl create` failures leave `lj`/`hj` unset. Both the deletes and the drain
# read go through this.
jobs_present() { # $@ job names, possibly empty -> the ones that exist, on stdout
  local named=() n
  for n in "$@"; do [ -n "$n" ] && named+=("$n"); done
  [ ${#named[@]} -eq 0 ] && return 0
  kubectl get jobs "${named[@]}" -n "$NS" --ignore-not-found -o name 2>/dev/null
}
del_jobs() { # $@ job names, possibly empty
  local n
  for n in "$@"; do
    [ -n "$n" ] && kubectl delete job "$n" -n "$NS" --ignore-not-found --wait=false >/dev/null 2>&1
  done
}

race_once() { # $1 blocker name, $2 low job file, $3 high job file -> HIGH|LOW|BOTH|NONE
  local blocker="$1" lowf="$2" highf="$3"
  local lj hj lw hw first="" d ba
  BLOCKER_OVERRIDE="$blocker" render_template "${MANIFESTS}/01-blocker-job.yaml" \
    | kubectl apply -f - >/dev/null 2>&1
  d=$((SECONDS+60)); ba=""
  while [ $SECONDS -lt $d ]; do ba=$(wl_admitted "$(wl_for_job "$blocker")"); [ "$ba" = "True" ] && break; sleep 2; done
  if [ "$ba" != "True" ]; then
    del_jobs "$blocker"
    echo "NOBLOCK"; return
  fi
  lj=$(kubectl create -f "$lowf" -o jsonpath='{.metadata.name}' 2>/dev/null)
  lw=$(wait_wl "$lj")
  sleep 6   # the same separation the detailed pass uses, and for the same reason
  hj=$(kubectl create -f "$highf" -o jsonpath='{.metadata.name}' 2>/dev/null)
  hw=$(wait_wl "$hj")
  if [ -z "$lw" ] || [ -z "$hw" ]; then
    del_jobs "$blocker" "$lj" "$hj"
    echo "NOWL"; return
  fi
  del_jobs "$blocker"
  d=$((SECONDS+60))
  while [ $SECONDS -lt $d ]; do
    local h l; h=$(wl_admitted "$hw"); l=$(wl_admitted "$lw")
    if [ "$h" = "True" ] && [ "$l" = "True" ]; then first="BOTH"; break; fi
    if [ "$h" = "True" ]; then first="HIGH"; break; fi
    if [ "$l" = "True" ]; then first="LOW"; break; fi
    sleep 2
  done
  del_jobs "$lj" "$hj"
  # Wait for THIS cycle's Jobs to go, so the next cycle's blocker can be admitted.
  # The earlier version waited for the namespace to hold no Jobs at all, which can
  # never happen: the detailed pass's own LOW and HIGH Jobs live until teardown, so
  # every repeat burned its full 90 seconds and established nothing. A read that
  # failed is not "drained" either -- it is a read that did not answer.
  d=$((SECONDS+90))
  while [ $SECONDS -lt $d ]; do
    local remaining
    remaining=$(jobs_present "$blocker" "$lj" "$hj") || { sleep 3; continue; }
    [ -z "$remaining" ] && break
    sleep 3
  done
  echo "${first:-NONE}"
}

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
# The deployment's args only. Gates can also travel inside the file named by
# --config, which this does not read, so the line says what it looked at rather
# than concluding "defaults apply". And a failed read is reported as a failed
# read: `grep` exits 1 both when the flag is absent and when kubectl printed
# nothing, so the earlier version transcribed an unreadable cluster as a positive
# claim about its configuration.
KUEUE_ARGS=$(kubectl get deployment -n kueue-system kueue-controller-manager \
  -o jsonpath='{range .spec.template.spec.containers[?(@.name=="manager")].args[*]}{@}{"\n"}{end}' 2>/dev/null) \
  && echo "  kueue gates    : $(printf '%s' "$KUEUE_ARGS" | grep -- '--feature-gates' || echo '(no --feature-gates arg; see the config file captured below)')" \
  || echo "  kueue gates    : could not read the deployment"
kubectl get configmap -n kueue-system kueue-manager-config -o yaml > "${OUT}/kueue-manager-config.yaml" 2>/dev/null \
  && echo "  kueue config   : captured to $(basename "${OUT}")/kueue-manager-config.yaml" \
  || echo "  kueue config   : not readable"

echo "=== 0. prerequisites ==="
# Prerequisites gate the rest. Reporting one as FAIL and carrying on into object
# creation, which is what happened before, means a run with no Kueue on the cluster
# still made a namespace, a queue and four cluster-scoped classes before failing on
# something downstream.
# The binary, resolved before the wrapper function shadowed the name -- `command -v
# kubectl` would otherwise find the function and report a missing binary as present.
[ -n "${KUBECTL_BIN}" ] && report PASS "kubectl available (${KUBECTL_BIN})" \
  || { report FAIL "kubectl missing"; echo "RESULT: FAIL"; exit 2; }
if kget get deployment -n kueue-system kueue-controller-manager >/dev/null 2>&1; then
  report PASS "Kueue controller present"
else
  report FAIL "Kueue controller missing or unreadable -- nothing was created"
  echo "RESULT: FAIL"; exit 2
fi
# The verbs this run needs, checked before it needs them. Namespace-level access
# says nothing about the cluster-scoped objects, which are the ones a failed
# teardown would leave behind.
# `kubectl auth can-i` answers on stdout -- "yes" or "no" -- and exits 1 only for
# "no". Reading the exit code alone is not enough here, because a resource type the
# server does not have still answers "yes" with exit 0: RBAC grants verbs on a
# resource NAME, and a name nothing implements is grantable. That case is reported
# on stderr instead. So the check is stdout "yes" AND nothing on stderr, which
# separates permitted, denied, and misspelled. --all-namespaces is the documented
# form for a cluster-scoped resource; without it kubectl warns about scope and the
# warning would read as a missing type.
RBAC_MISSING=""; RBAC_UNKNOWN=""
# Two questions, asked separately, because kubectl answers them together and
# ambiguously. "Does this resource type exist" comes from discovery, once. "Is the
# verb permitted" comes from `auth can-i -q`, whose exit code is the answer and
# which prints nothing.
#
# Reading stderr, as an earlier version did, could not tell an unknown type from a
# deprecation warning from a partial-discovery hiccup -- so a cluster that emits
# any warning at all failed every check and aborted the run.
KNOWN_RESOURCES=$(kubectl api-resources --no-headers -o name 2>/dev/null | sed 's/\..*//' | sort -u)
if [ -z "$KNOWN_RESOURCES" ]; then
  report FAIL "could not list the cluster's resource types -- nothing was created"
  echo "RESULT: FAIL"; exit 2
fi
can_i() { # $1 verb, $2 resource -> permitted | denied | unknown-type
  printf '%s\n' "$KNOWN_RESOURCES" | grep -qx -- "$2" || { echo unknown-type; return; }
  if kubectl auth can-i "$1" "$2" --all-namespaces -q >/dev/null 2>&1; then
    echo permitted
  else
    echo denied
  fi
}
for spec in "create:workloadpriorityclasses" "delete:workloadpriorityclasses" \
            "create:clusterqueues" "delete:clusterqueues" \
            "create:resourceflavors" "delete:resourceflavors" \
            "create:namespaces" "delete:namespaces" \
            "create:localqueues" "delete:localqueues" \
            "create:jobs" "delete:jobs" \
            "get:workloads" "get:workloadpriorityclasses" "get:clusterqueues"; do
  verb="${spec%%:*}"; res="${spec##*:}"
  case "$(can_i "$verb" "$res")" in
    permitted)    ;;
    denied)       RBAC_MISSING="${RBAC_MISSING} ${verb}/${res}" ;;
    unknown-type) RBAC_UNKNOWN="${RBAC_UNKNOWN} ${res}" ;;
  esac
done
if [ -n "$RBAC_UNKNOWN" ]; then
  # Not a denial. An unresolvable resource type, a discovery hiccup or an
  # unreachable apiserver produce the same shape, and naming RBAC for any of them
  # sends the reader to the wrong place -- while proceeding would start creating
  # objects on a cluster this run could not question.
  report FAIL "the cluster has no such resource type(s):${RBAC_UNKNOWN} -- nothing was created"
  echo "RESULT: FAIL"; exit 2
fi
if [ -z "$RBAC_MISSING" ]; then
  report PASS "the cluster-scoped verbs this run needs are permitted"
else
  report FAIL "missing permission for:${RBAC_MISSING} -- nothing was created"
  echo "RESULT: FAIL"; exit 2
fi

echo "=== 0b. nothing this run is about to create already exists ==="
COLLIDE=""; UNREADABLE=""
check_free() { # $@ -> args for existence()
  case "$(existence "$@")" in
    present)    COLLIDE="${COLLIDE} $1/$2" ;;
    unreadable) UNREADABLE="${UNREADABLE} $1/$2" ;;
  esac
}
check_free namespace "$NS"
check_free clusterqueue "$CQ"
check_free resourceflavor "$FLAVOR"
for cls in ${ALL_CLASSES}; do check_free workloadpriorityclass "$cls"; done
if [ -n "$UNREADABLE" ]; then
  # Not "free". A lookup that failed says nothing about the name, and creating on
  # top of that guess is how a run adopts and then deletes someone else's object.
  report FAIL "could not determine whether these names are free:${UNREADABLE} -- nothing was created"
  echo "RESULT: FAIL"; exit 2
fi
if [ -z "$COLLIDE" ]; then
  report PASS "no pre-existing object carries this run's names"
else
  report FAIL "refusing to adopt existing object(s):${COLLIDE}"
  echo "RESULT: FAIL"; exit 1
fi

echo "=== 1. apply namespace + ClusterQueue (cpu=1) + LocalQueue ==="
MUTATION_STARTED=1   # before the first create: a partial apply must still be torn down
# create, not apply. The preflight above establishes that these names are free, but
# it is a check-then-act: another run or another operator can create the same name in
# the gap, and apply would quietly adopt it, relabel it as ours, and let teardown
# delete it. create turns that race into AlreadyExists, which stops the run.
if render_template "${MANIFESTS}/00-namespace-and-queue.yaml" | kubectl create -f - >/dev/null; then
  report PASS "queue applied"
else
  report FAIL "queue apply failed -- nothing further attempted"
  cleanup; finish
fi

echo "=== 2. emit + apply the WorkloadPriorityClasses from the compiler ==="
PYTHONPATH="${HERE}/src" "${PYTHON_BIN}" -m orbital_mission_compiler.cli render-kueue \
  --input "${MANIFESTS}/plan-high.yaml" --output-dir "${OUT}/wpc" --queue "$LQ" --namespace "$NS" \
  --emit-priority-classes --priority-class --priority-class-prefix "$CLASS_PREFIX" \
  --policy-engine baseline >"${OUT}/render-wpc.log" 2>&1
# The compiler does not know about this run, so the ownership label is added here.
# create for the same reason as the queue above, and more so: these four are
# cluster-scoped, so adopting one would relabel an object shared with everything
# else on the cluster, and teardown would then delete it.
if "${PYTHON_BIN}" - "${OUT}/wpc/workload-priority-classes.yaml" "$RUN_ID" <<'PY' | kubectl create -f - >/dev/null
import sys, yaml
path, run_id = sys.argv[1], sys.argv[2]
docs = [d for d in yaml.safe_load_all(open(path, encoding="utf-8")) if d]
for d in docs:
    d.setdefault("metadata", {}).setdefault("labels", {})["orbital.test/run-id"] = run_id
yaml.safe_dump_all(docs, sys.stdout)
PY
then
  report PASS "WorkloadPriorityClasses applied"
else
  report FAIL "WPC apply failed -- nothing further attempted"
  cleanup; finish
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

# The control arm: the same two plans, the same submission order, rendered WITHOUT
# --priority-class. No priority-class label means Kueue resolves no
# WorkloadPriorityClass, both Workloads take priority 0, and the sort falls through to
# the creation timestamp -- so the prediction inverts and the first submitted should
# win. It is what makes the treatment arm evidence rather than an observation: without
# it, "priority beat arrival order" is asserted against a null that was never run, and
# any mechanism favouring the later submission would look identical.
for p in high low; do
  PYTHONPATH="${HERE}/src" "${PYTHON_BIN}" -m orbital_mission_compiler.cli render-kueue \
    --input "${MANIFESTS}/plan-${p}.yaml" --output-dir "${OUT}/ctl-${p}" --queue "$LQ" --namespace "$NS" \
    --policy-engine baseline >"${OUT}/render-ctl-${p}.log" 2>&1 || RENDER_BAD="${RENDER_BAD} ctl-${p}(exit $?)"
done
CTL_HIGH_FILE=$(find "${OUT}/ctl-high" -name '*-kueue.yaml' | head -1)
CTL_LOW_FILE=$(find "${OUT}/ctl-low" -name '*-kueue.yaml' | head -1)
[ -n "$CTL_HIGH_FILE" ] || RENDER_BAD="${RENDER_BAD} ctl-high(no -kueue.yaml)"
[ -n "$CTL_LOW_FILE" ] || RENDER_BAD="${RENDER_BAD} ctl-low(no -kueue.yaml)"

if [ -z "$RENDER_BAD" ]; then
  report PASS "both arms rendered by the compiler (priority-class and control)"
else
  report FAIL "render failed:${RENDER_BAD} (logs in ${OUT}) -- nothing further attempted"
  cleanup; finish
fi

# The control arm is only a control if its Jobs really carry no class. Checked here
# rather than assumed, because a control that silently kept the label would agree with
# the treatment arm and be read as the treatment arm failing to matter.
CTL_LABELLED=$("${PYTHON_BIN}" - "$CTL_HIGH_FILE" "$CTL_LOW_FILE" <<'PY'
import sys, yaml
hits = []
for path in sys.argv[1:3]:
    for doc in yaml.safe_load_all(open(path, encoding="utf-8")):
        if not doc:
            continue
        labels = (doc.get("metadata") or {}).get("labels") or {}
        if "kueue.x-k8s.io/priority-class" in labels:
            hits.append(f"{path}={labels['kueue.x-k8s.io/priority-class']}")
print(" ".join(hits))
PY
)
if [ -z "$CTL_LABELLED" ]; then
  report PASS "the control arm's Jobs carry no priority class"
else
  report FAIL "the control arm is not a control; it carries: ${CTL_LABELLED}"
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

echo "=== 8. the same race, repeated ==="
# The detailed pass above is race 1 of this arm; the remainder run here.
# Race 1 is the detailed pass above, and its outcome is $FIRST. An earlier version
# seeded the log with the literal "HIGH" and counted the win unconditionally, so a
# run whose first race went the other way printed "[FAIL] LOW admitted first" and
# then, three lines later, "priority arm outcomes: HIGH" and a PASS for 1/1. The
# transcript reported a result nobody observed.
TREAT_WINS=0; TREAT_LOG="${FIRST:-NONE}"
[ "${FIRST:-}" = "HIGH" ] && TREAT_WINS=1
i=1
while [ "$i" -lt "$REPS" ]; do
  i=$((i+1))
  w=$(race_once "${BLOCKER}-t${i}" "$LOW_JOB_FILE" "$HIGH_JOB_FILE")
  TREAT_LOG="${TREAT_LOG} ${w}"
  [ "$w" = "HIGH" ] && TREAT_WINS=$((TREAT_WINS+1))
  echo "  priority arm race ${i}/${REPS}: ${w}"
done
echo "  priority arm outcomes: ${TREAT_LOG}"
if [ "$TREAT_WINS" -eq "$REPS" ]; then
  report PASS "HIGH admitted first in ${TREAT_WINS}/${REPS} races despite being submitted last"
else
  report FAIL "HIGH admitted first in only ${TREAT_WINS}/${REPS} races (${TREAT_LOG})"
fi

echo "=== 9. control arm: the same plans and order, no priority class ==="
# The prediction inverts here. If the control also gives HIGH, the apparatus favours
# the later submission and the treatment arm shows nothing about priority.
CTL_WINS=0; CTL_LOG=""
i=0
while [ "$i" -lt "$REPS" ]; do
  i=$((i+1))
  w=$(race_once "${BLOCKER}-c${i}" "$CTL_LOW_FILE" "$CTL_HIGH_FILE")
  CTL_LOG="${CTL_LOG} ${w}"
  [ "$w" = "LOW" ] && CTL_WINS=$((CTL_WINS+1))
  echo "  control arm race ${i}/${REPS}: ${w}"
done
echo "  control arm outcomes:${CTL_LOG}"
if [ "$CTL_WINS" -eq "$REPS" ]; then
  report PASS "without a priority class the FIRST submitted won ${CTL_WINS}/${REPS} races -> the apparatus does observe arrival order, and the treatment arm inverted it"
else
  report FAIL "control arm did not follow arrival order:${CTL_LOG} (${CTL_WINS}/${REPS} to LOW)"
fi

echo "" ; echo "=== Summary ===" ; echo "PASS: ${PASS}  FAIL: ${FAIL}"
# Teardown runs via the EXIT trap (also covers interrupts).
cleanup
finish
