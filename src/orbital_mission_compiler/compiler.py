from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import re
import tempfile
from importlib import resources
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import yaml

from .schemas import MissionPlan, WorkflowIntent, ResourceClass, WorkflowStep

logger = logging.getLogger(__name__)


# DRA DeviceClass name for each compute class, used when rendering DRA
# ResourceClaimTemplates. Only classes with a registered DRA driver appear here:
# GPU via the NVIDIA DRA driver (gpu.nvidia.com) and CPU via
# kubernetes-sigs/dra-driver-cpu (dra.cpu). FPGA is deliberately absent -- no FPGA
# DRA driver exists -- so FPGA steps keep the legacy static-request path instead of
# emitting a claim against a nonexistent device class.
DRA_DEVICE_CLASS: dict[ResourceClass, str] = {
    ResourceClass.GPU: "gpu.nvidia.com",
    ResourceClass.CPU: "dra.cpu",
}


def sanitize_k8s_name(name: str, max_len: int = 63) -> str:
    """Sanitize a string to be a valid RFC 1123 DNS label (K8s container/resource name)."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9-]", "-", s)
    s = re.sub(r"-+", "-", s)
    s = s.strip("-")
    return s[:max_len].rstrip("-") or "step"


# An RFC 1123 DNS label: lowercase alphanumerics and '-', at most 63 characters,
# no dots. A Namespace name is one of these. A ServiceAccount and a LocalQueue
# are not -- see _RFC1123_SUBDOMAIN_RE below. Names the compiler derives from a
# plan are sanitized; these arrive from the operator and are copied into the
# manifest verbatim, so they are checked instead.
_RFC1123_LABEL_RE = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?\Z")

# resource.Quantity, transcribed from the grammar in the Kubernetes API
# reference rather than approximated:
# https://kubernetes.io/docs/reference/kubernetes-api/common-definitions/quantity/
#
#   <quantity>       ::= <signedNumber><suffix>
#   <suffix>         ::= <binarySI> | <decimalExponent> | <decimalSI>
#   <binarySI>       ::= Ki | Mi | Gi | Ti | Pi | Ei
#   <decimalSI>      ::= m | "" | k | M | G | T | P | E   (plus n and u)
#   <decimalExponent>::= ("e" | "E") <signedNumber>
#   <unsignedNumber> ::= <digits> | <digits> "." <digits> | <digits> "." | "." <digits>
#
# A character-class approximation is not enough: one accepts ".", "1..2", "1e",
# "1.2.3" and "1K", none of which resource.ParseQuantity accepts. Note the
# asymmetry in the SI suffixes -- decimal kilo is a lowercase "k", while the
# binary prefixes capitalise.
#
# [0-9] rather than \d: Python's \d is the whole Unicode Nd category, so the
# shorthand accepts Arabic-Indic and fullwidth digits that ParseQuantity rejects.
# The exponent is bounded because it is otherwise unbounded in the grammar, and
# ParseQuantity takes minutes and hundreds of MB on something like 1e2147483648 --
# which the API server would then run on admission.
_QUANTITY_RE = re.compile(
    r"[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)((Ki|Mi|Gi|Ti|Pi|Ei)|[munkMGTPE]|([eE][+-]?[0-9]{1,4}))?\Z"
)


# An RFC 1123 DNS subdomain, which is the default name class for a Kubernetes
# object: dots are allowed and the limit is 253, not 63. A ServiceAccount is one
# of these, so `workflow.runner` is a legal account name. Verified against a live
# API server: `kubectl create serviceaccount workflow.runner --dry-run=server`
# is accepted, while a Namespace with a dot is rejected.
_RFC1123_SUBDOMAIN_RE = re.compile(r"[a-z0-9]([-a-z0-9.]*[a-z0-9])?\Z")


def _require_k8s_subdomain(value: str, field: str, max_len: int = 253) -> str:
    """Reject a name the API server would reject, for objects named as subdomains.

    A subdomain is dot-separated DNS labels, each valid on its own -- checking
    only the first and last character of the whole string accepts ``a.-b`` and
    ``a-.b``, which the API server does not.
    """
    ok = (
        isinstance(value, str)
        and 0 < len(value) <= max_len
        and all(_RFC1123_LABEL_RE.fullmatch(part) for part in value.split("."))
    )
    if not ok:
        raise ValueError(
            f"{field} must be an RFC 1123 DNS subdomain (lowercase alphanumeric, '-' or '.', "
            f"starting and ending alphanumeric, at most {max_len} characters), got {value!r}"
        )
    return value


def _require_k8s_label(value: str, field: str) -> str:
    """Reject an operator-supplied name the API server would reject on apply.

    Rendering it anyway moves the failure to `kubectl apply`, which is after the
    point this compiler exists to check.
    """
    if not isinstance(value, str) or not _RFC1123_LABEL_RE.fullmatch(value) or len(value) > 63:
        raise ValueError(
            f"{field} must be an RFC 1123 DNS label (lowercase alphanumeric or '-', "
            f"starting and ending alphanumeric, at most 63 characters), got {value!r}"
        )
    return value


def _require_quantity(value: str, field: str) -> str:
    """Reject a resource request the API server would not parse as a quantity.

    Matches the stripped value and emits the stripped value, so surrounding
    whitespace is absorbed rather than rejected; what lands in the manifest is
    still exactly what ``resource.ParseQuantity`` accepts. Slightly stricter than
    that function at the degenerate end: it parses ``"."``, ``"m"`` and ``"+"``
    as zero, and those are rejected here, since none of them is a resource
    request anyone means to write.
    """
    text = value.strip() if isinstance(value, str) else value
    if not isinstance(text, str) or not text or not _QUANTITY_RE.fullmatch(text):
        raise ValueError(
            f"{field} must be a Kubernetes quantity (e.g. '1', '500m', '256Mi'), got {value!r}"
        )
    # Parsing is not the whole contract: `-1` and `-500m` are well-formed
    # quantities that the API server rejects for a resource request
    # ("must be greater than or equal to 0", checked against a live server).
    # Sub-milli CPU is deliberately not rejected -- 0.5m and 100n are accepted
    # there, so refusing them would be stricter than Kubernetes.
    if text.startswith("-"):
        raise ValueError(f"{field} must not be negative, got {value!r}")
    return text


def _collision_resistant_k8s_name(name: str, max_len: int = 63, hash_len: int = 8) -> str:
    """Sanitize and preserve uniqueness when truncation is required."""
    if max_len < hash_len + 2:
        raise ValueError(f"max_len={max_len} too small for hash_len={hash_len}")
    normalized = sanitize_k8s_name(name, max_len=253)
    if len(normalized) <= max_len:
        return normalized
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()[:hash_len]
    head = normalized[: max_len - hash_len - 1].rstrip("-")
    if not head:
        head = "step"
    return f"{head}-{digest}"


def _to_rfc3339_z(ts: datetime) -> str:
    """Serialize a datetime to RFC3339 using Z for UTC when possible."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    text = ts.isoformat()
    if text.endswith("+00:00"):
        return text[:-6] + "Z"
    return text


def scale_priority_orchide(priority: int) -> int:
    """Convert 0-100 priority to ORCHIDE 1-4 scale (1=highest).

    ORCHIDE slide 9 uses 1-4; the schema uses 0-100 (higher=higher).
    Mapping: 76-100→1, 51-75→2, 26-50→3, 1-25→4.
    Priority 0 is rejected (OPA rule 5 treats it as misconfiguration).
    """
    if priority < 0 or priority > 100:
        raise ValueError(f"priority {priority} out of range 0-100")
    if priority == 0:
        raise ValueError("priority 0 is a misconfiguration (ORCHIDE uses 1-4)")
    if priority >= 76:
        return 1
    if priority >= 51:
        return 2
    if priority >= 26:
        return 3
    return 4


class _StrictLoader(yaml.SafeLoader):
    """A SafeLoader that refuses a mapping with a repeated key.

    PyYAML keeps the last value for a duplicate key, so a plan can read one way
    to a reviewer and load another way. For an artifact that a policy layer signs
    off before uplink, an ambiguous document is not something to resolve
    silently.
    """

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        self._refuse_repeated_keys(node, deep, set())
        return super().construct_mapping(node, deep=deep)

    def _refuse_repeated_keys(self, node: yaml.MappingNode, deep: bool, visiting: set[int]) -> None:
        """Raise if this mapping, or a mapping it merges in, repeats a key.

        Scanned before any merge source is flattened in. Flattening first
        conflates two different things: a key written twice, which is the
        ambiguity worth refusing, and a merge override, which is how YAML says
        "take these defaults and change this one". `<<: *defaults` followed by
        an explicit `priority:` leaves two `priority` entries in the flattened
        node, and rejecting that would refuse a document whose meaning YAML
        defines precisely.

        A merge source is a mapping the author wrote too, so it is scanned in
        its own right. `flatten_mapping` splices its pairs in without ever
        constructing it, and a source reached only through `<<:` is nobody's
        value, so a key repeated inside one is invisible to a scan of this node
        alone -- which is how `<<: {resource_class: gpu, resource_class: cpu}`
        came to load as cpu without complaint.
        """
        if id(node) in visiting:
            # A mapping that merges itself. Nothing to resolve, and recursing
            # would not terminate.
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping", node.start_mark,
                "found a merge key that refers to its own mapping", node.start_mark,
            )
        visiting = visiting | {id(node)}
        seen: set[Any] = set()
        merged = False
        for key_node, value_node in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                if merged:
                    # Two `<<` in one mapping is a repeated key, and the later
                    # one wins -- the opposite of `<<: [a, b]`, where the
                    # earlier does. Same document, two readings.
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping", node.start_mark,
                        "found duplicate merge key '<<'", key_node.start_mark,
                    )
                merged = True
                for source in self._merge_sources(value_node):
                    self._refuse_repeated_keys(source, deep, visiting)
                continue
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in seen
            except TypeError:
                # Let SafeConstructor report it, with the position it knows.
                return
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping", node.start_mark,
                    f"found duplicate key {key!r}", key_node.start_mark,
                )
            seen.add(key)

    @staticmethod
    def _merge_sources(value_node: yaml.Node) -> list[yaml.MappingNode]:
        """The mappings a `<<:` pulls from, whether written as one or a list."""
        candidates = (
            value_node.value if isinstance(value_node, yaml.SequenceNode) else [value_node]
        )
        return [n for n in candidates if isinstance(n, yaml.MappingNode)]


def load_mission_plan(path: str | Path) -> MissionPlan:
    raw = yaml.load(Path(path).read_text(encoding="utf-8"), Loader=_StrictLoader)  # noqa: S506
    return MissionPlan.model_validate(raw)


def analyze_timeline_conflicts(plan: MissionPlan) -> dict[str, Any]:
    """Detect overlapping acquisition windows and report skipped timestamps.

    Pairwise comparison is O(n^2) in acquisition events. For plans with
    hundreds of events, consider sorting by start time first (future optimization).
    """
    acq_events = []
    skipped = []

    for ev in plan.events:
        if ev.event_type.value != "acquisition":
            continue
        if ev.duration_seconds is None:
            ts_text = _to_rfc3339_z(ev.timestamp)
            logger.debug("Skipping event without duration_seconds: %s (plan: %s)", ts_text, plan.mission_id)
            skipped.append(ts_text)
            continue
        start = ev.timestamp.timestamp()
        ts_text = _to_rfc3339_z(ev.timestamp)
        acq_events.append({
            "timestamp": ts_text,
            "start": start,
            "end": start + ev.duration_seconds,
        })

    conflicts: list[dict[str, Any]] = []
    for i in range(len(acq_events)):
        for j in range(i + 1, len(acq_events)):
            a, b = acq_events[i], acq_events[j]
            max_start = max(cast(float, a["start"]), cast(float, b["start"]))
            min_end = min(cast(float, a["end"]), cast(float, b["end"]))
            if max_start < min_end:
                conflicts.append({
                    "event_a": a["timestamp"],
                    "event_b": b["timestamp"],
                    "overlap_seconds": round(min_end - max_start, 2),
                })
    return {
        "conflicts": conflicts,
        "conflict_count": len(conflicts),
        "skipped_timestamps": skipped,
    }


def detect_timeline_conflicts(plan: MissionPlan) -> list[dict[str, Any]]:
    """Detect overlapping acquisition windows in a mission plan."""
    return cast(list[dict[str, Any]], analyze_timeline_conflicts(plan)["conflicts"])


def _workflow_name(
    mission_id: str, service_id: str, event_timestamp: str, used: dict[str, int]
) -> str:
    """Name an intent, disambiguating a repeated occurrence.

    The schema does not require a service_id to be unique within an event or a
    timestamp to be unique across events, and distinct identifiers can normalise
    to the same Kubernetes name, so two occurrences can collide. Both writers use this name as the output filename
    and as the object name, so without a discriminator the second occurrence
    would silently overwrite the first. The first occurrence keeps the plain
    name, which is what existing goldens and manifests already carry.
    """
    canonical = _collision_resistant_k8s_name(f"{mission_id}-{service_id}-{event_timestamp}")
    seen = used.get(canonical, 0)
    used[canonical] = seen + 1
    if not seen:
        return canonical
    # Counting the raw string would miss identifiers that differ only in
    # characters the Kubernetes name rules erase: foo_bar, foo.bar, FOO-BAR and
    # foo--bar all normalise to the same label, so each would look like a first
    # occurrence and land on the same object and file.
    return _collision_resistant_k8s_name(f"{canonical}-{seen + 1}")


def compile_plan_to_intents(
    plan: MissionPlan,
    check_conflicts: bool = False,
) -> list[WorkflowIntent]:
    if check_conflicts:
        conflicts = detect_timeline_conflicts(plan)
        for c in conflicts[:10]:
            logger.warning(
                "Timeline conflict: %s overlaps with %s by %.1fs",
                c["event_a"], c["event_b"], c["overlap_seconds"],
            )
        if len(conflicts) > 10:
            logger.warning("... and %d more conflicts (total: %d)", len(conflicts) - 10, len(conflicts))
    intents: list[WorkflowIntent] = []
    used_names: dict[str, int] = {}
    skipped = 0
    for event in plan.events:
        if event.event_type.value != "acquisition":
            skipped += 1
            logger.info(
                "Skipping %s event at %s (only acquisition events produce workflow intents)",
                event.event_type.value,
                event.timestamp,
            )
            continue
        for svc in event.services:
            gpu_steps = [s for s in svc.steps if s.resource_class == ResourceClass.GPU]
            fpga_steps = [s for s in svc.steps if s.resource_class == ResourceClass.FPGA]
            fallback_steps = [s for s in svc.steps if s.fallback_resource_class is not None]
            event_timestamp = _to_rfc3339_z(event.timestamp)
            hints = {
                "event_timestamp": event_timestamp,
                "ground_visibility": event.ground_visibility,
                "region_type": event.region_type,
                "orbit": event.orbit,
                "duration_seconds": event.duration_seconds,
                "landscape_type": svc.landscape_type,
                "execution_mode": svc.execution_mode.value,
                "requires_gpu": bool(gpu_steps),
                "requires_fpga": bool(fpga_steps),
                "fallback_enabled": bool(fallback_steps),
            }
            intents.append(
                WorkflowIntent(
                    mission_id=plan.mission_id,
                    service_id=svc.service_id,
                    priority=svc.priority,
                    workflow_name=_workflow_name(
                        plan.mission_id, svc.service_id, event_timestamp, used_names
                    ),
                    steps=svc.steps,
                    resource_hints=hints,
                )
            )
    logger.info(
        "Compiled %d intents from %d events (%d skipped)",
        len(intents),
        len(plan.events),
        skipped,
    )
    return intents


def _preferred_affinity(step: WorkflowStep) -> dict[str, Any] | None:
    if not step.preferred_node_selector:
        return None
    expressions = [
        {"key": key, "operator": "In", "values": [value]}
        for key, value in step.preferred_node_selector.items()
    ]
    return {
        "nodeAffinity": {
            "preferredDuringSchedulingIgnoredDuringExecution": [
                {
                    "weight": 100,
                    "preference": {"matchExpressions": expressions},
                }
            ]
        }
    }


def render_argo_workflow(
    intent: WorkflowIntent,
    *,
    dra_fallback: bool = False,
    namespace: str | None = None,
    service_account: str | None = None,
) -> dict[str, Any]:
    """Render an Argo Workflow for the intent's steps.

    Default: the accelerator-with-fallback preference is realized only as the
    runtime env-var switch (``ORBITAL_FALLBACK_RESOURCE_CLASS``).

    Opt-in ``dra_fallback``: the accelerator-fallback step's Pod is wired to a DRA
    ``firstAvailable`` ResourceClaimTemplate via ``podSpecPatch`` (see
    ``_argo_dra_pod_spec_patch``), so the GPU-or-CPU choice is made by the
    scheduler at allocation time rather than by the runtime env-var switch. Pair
    with ``_first_available_rct`` (emitted alongside by
    ``write_individual_workflows``) so the reference resolves.

    This is DEVICE ALLOCATION fallback, not application fallback. The scheduler
    picks a device; it does not substitute the image, command or arguments, and
    the schema has no place to express a different implementation for the CPU
    case. A step rendered this way must therefore run under either allocation,
    and a workload that needs to know which one it got reads the device metadata
    Kubernetes exposes. The env-var pair still reports the declared classes, so
    it is not a signal of what was actually allocated.

    ``namespace``, when given, is stamped on the Workflow. A ResourceClaimTemplate
    is namespaced and a Pod can only reference one in its own namespace, so the
    multi-doc output has to place both objects in the same namespace to be
    applyable without an external ``kubectl -n``.
    """
    fallback_step_ids = {id(s) for s in _dra_fallback_steps(intent)} if dra_fallback else set()
    templates = []
    dag_tasks = []
    for idx, step in enumerate(intent.steps):
        template_name = _collision_resistant_k8s_name(f"step-{idx}-{step.name}")
        annotations: dict[str, str] = {
            "resource-class": step.resource_class.value,
            "needs-acceleration": str(step.needs_acceleration).lower(),
        }
        if step.phase is not None:
            annotations["phase"] = step.phase.value

        template: dict[str, Any] = {
            "name": template_name,
            "container": {
                "image": step.image,
                "command": step.command or ["sh", "-c"],
                "args": step.args or [f'echo "run {step.name}"'],
                "env": [
                    {"name": "ORBITAL_RESOURCE_CLASS", "value": step.resource_class.value},
                    {
                        "name": "ORBITAL_NEEDS_ACCELERATION",
                        "value": str(step.needs_acceleration).lower(),
                    },
                ],
            },
            "metadata": {
                "annotations": annotations,
            },
        }
        if step.fallback_resource_class is not None:
            template["container"]["env"].append(
                {
                    "name": "ORBITAL_FALLBACK_RESOURCE_CLASS",
                    "value": step.fallback_resource_class.value,
                }
            )
            template["metadata"]["annotations"]["fallback-resource-class"] = step.fallback_resource_class.value
        affinity = _preferred_affinity(step)
        if affinity:
            template["affinity"] = affinity
        # DRA scheduler-level fallback: bind THIS step's Pod to the firstAvailable
        # ResourceClaimTemplate (emitted alongside), so GPU->CPU fallback is a
        # scheduler decision rather than the runtime env-var switch. Two halves:
        # the container binding is a native CRD field (structural), the pod-level
        # resourceClaims entry has no Template field so it goes via podSpecPatch.
        if id(step) in fallback_step_ids:
            claim = "compute"
            template["container"].setdefault("resources", {})["claims"] = [{"name": claim}]
            template["podSpecPatch"] = _argo_dra_pod_spec_patch(
                _rct_name_for_intent(intent, "accel"), claim
            )
        templates.append(template)

        dag_task: dict[str, Any] = {"name": template_name, "template": template_name}
        dag_tasks.append(dag_task)

    # Apply DAG dependencies based on execution_mode.
    # Sequential: linear chain (A→B→C). Parallel: no dependencies.
    # Unknown values raise ValueError (fail-closed for safety-critical contexts).
    execution_mode = intent.resource_hints.get("execution_mode", "sequential")
    if execution_mode not in ("sequential", "parallel"):
        raise ValueError(f"Unknown execution_mode {execution_mode!r}; expected 'sequential' or 'parallel'")
    if execution_mode == "sequential":
        for i in range(1, len(dag_tasks)):
            dag_tasks[i]["depends"] = dag_tasks[i - 1]["name"]

    wf_annotations: dict[str, str] = {
        "orbital/priority": str(intent.priority),
        "orbital/orchide-priority": str(scale_priority_orchide(intent.priority)),
        "orbital/execution-mode": execution_mode,
        "orbital/requires-gpu": str(intent.resource_hints.get("requires_gpu", False)).lower(),
        "orbital/requires-fpga": str(intent.resource_hints.get("requires_fpga", False)).lower(),
        "orbital/fallback-enabled": str(intent.resource_hints.get("fallback_enabled", False)).lower(),
    }

    workflow = {
        "apiVersion": "argoproj.io/v1alpha1",
        "kind": "Workflow",
        "metadata": {
            "name": sanitize_k8s_name(intent.workflow_name),
            "labels": {
                "mission-id": sanitize_k8s_name(intent.mission_id),
                "service-id": sanitize_k8s_name(intent.service_id),
                "priority": str(intent.priority),
                MANAGED_BY_LABEL: MANAGED_BY_VALUE,
                MISSION_FINGERPRINT_LABEL: mission_fingerprint(intent.mission_id),
            },
            "annotations": _require_annotations_fit(
                {**wf_annotations, RAW_MISSION_ID_ANNOTATION: intent.mission_id},
                f"Workflow {intent.workflow_name}",
            ),
        },
        "spec": {
            "entrypoint": "main",
            "templates": [{"name": "main", "dag": {"tasks": dag_tasks}}, *templates],
        },
    }
    if namespace is not None:
        workflow["metadata"]["namespace"] = _require_k8s_label(namespace, "namespace")  # type: ignore[index]
    if service_account is not None:
        _require_k8s_subdomain(service_account, "service_account")
        # `argo submit --serviceaccount` cannot be used on the multi-document
        # bundle, because argo submit drops the ResourceClaimTemplate. Applying
        # the bundle with kubectl therefore needs the account in the manifest, or
        # the Workflow runs as default and fails the workflowtaskresults RBAC.
        workflow["spec"]["serviceAccountName"] = service_account  # type: ignore[index]
    return workflow


def _rct_name_for_intent(intent: WorkflowIntent, device: str) -> str:
    """Deterministic ResourceClaimTemplate name for a given intent and device type.

    Hashes rather than truncates: plain truncation drops the ``device``
    discriminator once the workflow name fills the budget, so the
    ``firstAvailable`` and ``exactly`` templates a ``--dra-fallback`` render emits
    together would collapse to the same name and overwrite one another on apply.
    """
    return _collision_resistant_k8s_name(f"{intent.workflow_name}-{device}-claim", max_len=62)


# Marks which admission route may reference a rendered ResourceClaimTemplate:
# "scheduler" for the firstAvailable claim (plain Pod / Argo), "kueue" for the
# exactly claim a Kueue Job is admitted on.
DRA_ROUTE_LABEL = "orbital/dra-route"


# The accelerator-to-CPU directions renderable as a DRA firstAvailable request.
# An explicit allowlist rather than "both classes have a driver and differ": the
# latter also accepts CPU primary with GPU fallback, which renders a request that
# prefers CPU and falls back to the accelerator -- the reverse of the
# accelerator-with-fallback semantics the flag and the docs describe. Add a pair
# here when a new accelerator gains a driver.
DRA_FALLBACK_DIRECTIONS: frozenset[tuple[ResourceClass, ResourceClass]] = frozenset(
    {(ResourceClass.GPU, ResourceClass.CPU)}
)


def _dra_fallback_steps(intent: WorkflowIntent) -> list[WorkflowStep]:
    """Every step expressing a driver-backed accelerator-to-CPU fallback.

    Returns all qualifying steps, not just the first: a service may declare
    several accelerator steps, and wiring only one leaves the rest on the
    runtime-only path while the render reports success. A step whose direction is
    not in ``DRA_FALLBACK_DIRECTIONS`` (FPGA, which has no driver, or a reversed
    CPU-to-GPU pair) does not qualify and keeps the legacy path.
    """
    return [
        step
        for step in intent.steps
        if step.fallback_resource_class is not None
        and (step.resource_class, step.fallback_resource_class) in DRA_FALLBACK_DIRECTIONS
    ]


def _first_available_rct(intent: WorkflowIntent, namespace: str | None) -> dict[str, Any] | None:
    """The scheduler-route ``firstAvailable`` ResourceClaimTemplate for the intent's
    driver-backed accelerator-with-fallback step, or ``None`` if no step qualifies.

    "prefer <primary>, else <fallback>" as a single scheduler-level decision. This
    is the artifact the Argo/plain-Pod (non-Kueue) route consumes; Kueue admission
    rejects ``firstAvailable`` and uses the ``exactly`` claim instead.
    """
    steps = _dra_fallback_steps(intent)
    if not steps:
        return None
    if namespace is None:
        # A ResourceClaimTemplate is namespaced and a Pod resolves one only in its
        # own namespace, so a bundle whose two documents could land in different
        # namespaces is not something to emit and hope for.
        raise ValueError(
            "a DRA fallback render needs an explicit namespace, so the Workflow "
            "and the claim template it references cannot be separated"
        )
    # Every qualifying step shares the same direction (DRA_FALLBACK_DIRECTIONS), so
    # one template serves them all: each Pod that references it gets its own claim.
    step = steps[0]
    primary = step.resource_class
    fallback = cast(ResourceClass, step.fallback_resource_class)
    return {
        "apiVersion": "resource.k8s.io/v1",
        "kind": "ResourceClaimTemplate",
        "metadata": {
            "name": _rct_name_for_intent(intent, "accel"),
            "namespace": namespace,
            # Which route may reference this template. A Kueue Job never does, so
            # an operator reading the applied object -- not just the file it came
            # from -- can tell that this claim is not what the Job was admitted on.
            "labels": {
                DRA_ROUTE_LABEL: "scheduler",
                MANAGED_BY_LABEL: MANAGED_BY_VALUE,
                MISSION_FINGERPRINT_LABEL: mission_fingerprint(intent.mission_id),
            },
            "annotations": {RAW_MISSION_ID_ANNOTATION: intent.mission_id},
        },
        "spec": {
            "spec": {
                "devices": {
                    "requests": [
                        {
                            "name": "compute",
                            "firstAvailable": [
                                {"name": primary.value, "deviceClassName": DRA_DEVICE_CLASS[primary]},
                                {"name": fallback.value, "deviceClassName": DRA_DEVICE_CLASS[fallback]},
                            ],
                        }
                    ],
                },
            },
        },
    }


def _argo_dra_pod_spec_patch(rct_name: str, claim_name: str = "compute") -> str:
    """An Argo ``podSpecPatch`` that adds ONLY the pod-level ``resourceClaims``
    entry binding a DRA ResourceClaimTemplate.

    The split is deliberate and matches Argo's schema (>= v4.0, k8s api v0.33+):
    the container binding (``resources.claims``) is a native CRD field and is set
    structurally on ``template.container`` by the renderer; but the Template has NO
    structured pod-level ``resourceClaims`` field, so that half must go through
    ``podSpecPatch`` (a strategic-merge patch the controller applies to the final
    PodSpec before creating the Pod).

    This requires Argo >= v4.0 on a Kubernetes that serves ``resource.k8s.io/v1``.
    Do not rely on an older Argo degrading gracefully: the container half is
    pruned by a CRD that lacks the field, but ``podSpecPatch`` is an opaque
    string the controller merges into the PodSpec regardless, so the request can
    reach the API server and be rejected there rather than falling back to the
    runtime env-var switch. Leave ``dra_fallback`` off on older stacks.
    """
    patch = {"resourceClaims": [{"name": claim_name, "resourceClaimTemplateName": rct_name}]}
    return yaml.safe_dump(patch, sort_keys=False)


def render_resource_claim_templates(
    intent: WorkflowIntent,
    namespace: str = "orbital-demo",
    dra_fallback: bool = False,
) -> list[dict[str, Any]]:
    """Render DRA ResourceClaimTemplates for accelerator steps.

    Default: a GPU step produces one ResourceClaimTemplate with an ``exactly``
    request for deviceClassName gpu.nvidia.com. FPGA and CPU steps produce nothing
    (no FPGA DRA driver; CPU keeps standard requests for portability).

    Opt-in ``dra_fallback``: when a step declares both a driver-backed
    ``resource_class`` and a driver-backed ``fallback_resource_class`` (see
    ``DRA_DEVICE_CLASS``), emit a ``firstAvailable`` request -- the scheduler
    allocates the primary device if one is free, else the fallback -- rendering the
    step's fallback as a scheduler-level decision rather than the runtime env-var
    switch emitted by ``render_argo_workflow``.

    Kueue admission does NOT accept a ``firstAvailable`` claim: it rejects such a
    workload as Inadmissible ("FirstAvailable device selection is not supported",
    verified live on Kueue v0.17.3 and v0.18.3) and quota-counts only ``exactly``
    requests. The firstAvailable RCT is therefore a SCHEDULER-route artifact (a
    plain Pod / non-Kueue consumer references it). So that ``render_kueue_job`` has
    a Kueue-admissible template to reference, this function ALSO emits the
    ``exactly`` GPU RCT for an accelerator step. A GPU accelerator step thus yields
    TWO templates under ``dra_fallback``: the scheduler-route ``firstAvailable``
    claim and the Kueue-route ``exactly`` claim.
    """
    _require_k8s_label(namespace, "namespace")
    templates: list[dict[str, Any]] = []
    if dra_fallback:
        rct = _first_available_rct(intent, namespace)
        if rct is not None:
            templates.append(rct)
            # Fall through: also emit the exactly GPU RCT below (Kueue route).
    requires_gpu = intent.resource_hints.get("requires_gpu", False)
    if requires_gpu:
        templates.append({
            "apiVersion": "resource.k8s.io/v1",
            "kind": "ResourceClaimTemplate",
            "metadata": {
                "name": _rct_name_for_intent(intent, "gpu"),
                "namespace": namespace,
                "labels": {
                    DRA_ROUTE_LABEL: "kueue",
                    MANAGED_BY_LABEL: MANAGED_BY_VALUE,
                    MISSION_FINGERPRINT_LABEL: mission_fingerprint(intent.mission_id),
                },
                "annotations": {RAW_MISSION_ID_ANNOTATION: intent.mission_id},
            },
            "spec": {
                "spec": {
                    "devices": {
                        "requests": [
                            {
                                "name": "gpu",
                                "exactly": {
                                    "deviceClassName": "gpu.nvidia.com",
                                },
                            }
                        ],
                    },
                },
            },
        })
    return templates


ORCHIDE_PRIORITY_CLASS_PREFIX = "orbital-orchide-"
# Bump when the tier->value mapping below changes, so a cluster can detect a Job
# labelled against a stale class set.
PRIORITY_CLASS_MAPPING_VERSION = "v1"


# An RFC 1123 label, which is what both a WorkloadPriorityClass name and the
# kueue.x-k8s.io/priority-class label value must be.
_K8S_LABEL_RE = re.compile(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?\Z")


def _priority_class_name(orchide_priority: int, prefix: str = ORCHIDE_PRIORITY_CLASS_PREFIX) -> str:
    """Kueue WorkloadPriorityClass name for an ORCHIDE 1-4 tier.

    Rejects a prefix that would produce a name the API server refuses, rather
    than emitting YAML that fails only on apply. The same string becomes a label
    value on the Job, so it must satisfy the 63-character label bound too.
    """
    name = f"{prefix}{orchide_priority}"
    if len(name) > 63 or not _K8S_LABEL_RE.fullmatch(name):
        raise ValueError(
            f"priority-class prefix {prefix!r} yields invalid name {name!r}: must be an "
            "RFC 1123 label (lowercase alphanumeric and '-', starting and ending "
            "alphanumeric) of at most 63 characters"
        )
    return name


def render_workload_priority_classes(
    prefix: str = ORCHIDE_PRIORITY_CLASS_PREFIX,
) -> list[dict[str, Any]]:
    """Kueue WorkloadPriorityClass objects for the four ORCHIDE priority tiers.

    A rendered Kueue Job references one of these via the
    ``kueue.x-k8s.io/priority-class`` label, so a mission plan's priority feeds
    Kueue's queue-sorting and **contributes to preemption eligibility** (whether a
    preemption actually occurs still depends on the ClusterQueue/cohort preemption
    configuration). Higher ORCHIDE tier maps to a higher Kueue value (ORCHIDE~1 is
    highest). These are cluster-scoped: apply them once per cluster before
    submitting Jobs (``kubectl apply`` is idempotent); a configurable ``prefix``
    keeps parallel installations from colliding on the fixed names.
    """
    return [
        {
            "apiVersion": "kueue.x-k8s.io/v1beta2",
            "kind": "WorkloadPriorityClass",
            "metadata": {
                "name": _priority_class_name(tier, prefix),
                "labels": {
                    "app.kubernetes.io/managed-by": "orbital-mission-compiler",
                    "orbital/priority-mapping-version": PRIORITY_CLASS_MAPPING_VERSION,
                },
            },
            "value": (5 - tier) * 100,  # ORCHIDE 1 -> 400 (highest), 4 -> 100
            "description": f"ORCHIDE priority tier {tier} (1=highest)",
        }
        for tier in (1, 2, 3, 4)
    ]


def kueue_step_projection(intent: WorkflowIntent) -> dict[str, Any] | None:
    """Which step a Kueue Job for this intent runs, and which it leaves out.

    Derived here rather than recomputed by the caller: the renderer selects the
    step by identity, and a caller comparing names finds nothing dropped when two
    steps share one -- which silences the very warning this exists to raise.
    """
    primary = _primary_step(intent)
    dropped = [step.name for step in intent.steps if step is not primary]
    if not dropped:
        return None
    return {
        "service_id": intent.service_id,
        "executed_step": primary.name,
        "steps_not_in_job": dropped,
    }


def _primary_step(intent: WorkflowIntent) -> WorkflowStep:
    """The one step a Kueue Job runs: GPU first, then FPGA, then the first step."""
    gpu = [s for s in intent.steps if s.resource_class == ResourceClass.GPU]
    fpga = [s for s in intent.steps if s.resource_class == ResourceClass.FPGA]
    if gpu:
        return gpu[0]
    if fpga:
        return fpga[0]
    return intent.steps[0]


def render_kueue_job(
    intent: WorkflowIntent,
    queue_name: str = "orbital-demo-local",
    namespace: str = "orbital-demo",
    cpu_request: str = "1",
    memory_request: str = "256Mi",
    dra_enabled: bool = True,
    dra_fallback: bool = False,
    priority_class: bool = False,
    priority_class_prefix: str = ORCHIDE_PRIORITY_CLASS_PREFIX,
) -> dict[str, Any]:
    cpu_request = _require_quantity(cpu_request, "cpu_request")
    memory_request = _require_quantity(memory_request, "memory_request")
    _require_k8s_label(namespace, "namespace")
    # The queue name is stamped as the kueue.x-k8s.io/queue-name label value and
    # names a LocalQueue. The object name may be a subdomain, the label value is
    # capped at 63, so the binding constraint is the intersection.
    _require_k8s_subdomain(queue_name, "queue_name", max_len=63)

    # Pick the primary compute step (GPU > FPGA > first step).
    primary = _primary_step(intent)

    # Derived from the step this Job actually runs, not from the whole service.
    # The aggregate hints cover every step, including the ones the projection
    # leaves out, so a service whose GPU step is followed by an FPGA step read as
    # one Pod asking for both and was rejected -- although the Job that would be
    # rendered holds only the GPU step. Argo runs those two as separate Pods, so
    # the service is fine; it is this projection that has to be described right.
    requires_gpu = primary.resource_class == ResourceClass.GPU
    requires_fpga = primary.resource_class == ResourceClass.FPGA

    # This Job is a STANDALONE workload that demonstrates Kueue admission for the
    # service's primary step. It is not an admission gate for the Argo Workflow:
    # nothing links the two, the Job's Kueue Workload reserves quota for itself
    # alone, and applying both artifacts runs the primary step twice. Kueue's own
    # Argo integration works the other way round -- a queue-name label in
    # spec.podMetadata or a template's metadata, so Kueue admits each Pod Argo
    # creates -- and it is per-Pod, not whole-workflow atomic. Wiring that up is
    # a feature, not a rename, and is deliberately not attempted here.
    # A service with several steps is therefore projected onto its primary step,
    # and the rest do not run in this Job -- the Argo Workflow is what executes
    # the full sequence. Silently dropping them would make the Job look like the
    # whole service, so the projection is recorded on the object and reported by
    # the caller. Preserving multi-step semantics under Kueue needs a different
    # owner (a Kueue-managed Workflow, JobSet, or one Job per step) and is a
    # contract decision, not something to infer here.
    # By identity, not by name: two steps may share a name, and comparing names
    # would report nothing dropped while one of them is silently absent.
    dropped = [step.name for step in intent.steps if step is not primary]

    container: dict[str, Any] = {
        "name": sanitize_k8s_name(primary.name),
        "image": primary.image,
        "command": primary.command or ["sh", "-c"],
        "args": primary.args or [f'echo "run {primary.name}"'],
        "resources": {
            "requests": {
                "cpu": cpu_request.strip(),
                "memory": memory_request.strip(),
            },
        },
    }

    pod_spec: dict[str, Any] = {
        "restartPolicy": "Never",
        "containers": [container],
    }

    # ── GPU handling ──────────────────────────────────────────────────
    # Kueue admission rejects `firstAvailable` device selection as Inadmissible
    # ("FirstAvailable device selection is not supported", verified live on Kueue
    # v0.17.3 and v0.18.3) and quota-counts only `exactly` requests. A Kueue Job for
    # a DRA accelerator step therefore ALWAYS uses the `exactly` gpu.nvidia.com claim
    # (which Kueue quota-counts). The scheduler-level firstAvailable GPU->CPU fallback
    # is available only off the Kueue admission path: a plain Pod / scheduler route
    # consumes the firstAvailable RCT that render_resource_claim_templates emits.
    if dra_fallback and dra_enabled and requires_gpu and _dra_fallback_steps(intent):
        logger.warning(
            "DRA firstAvailable fallback is not admissible under Kueue; the Kueue "
            "Job uses an exactly gpu.nvidia.com claim. Use the scheduler route "
            "(plain Pod / Argo) for the firstAvailable GPU->CPU fallback."
        )
    if requires_gpu and dra_enabled:
        # DRA path: exactly gpu.nvidia.com ResourceClaim (Kueue quota-counts this).
        rct_name = _rct_name_for_intent(intent, "gpu")
        pod_spec["resourceClaims"] = [
            {"name": "gpu", "resourceClaimTemplateName": rct_name},
        ]
        container["resources"]["claims"] = [{"name": "gpu"}]
    elif requires_gpu:
        # Legacy path: static nvidia.com/gpu request.
        container["resources"]["requests"]["nvidia.com/gpu"] = "1"
        container["resources"]["limits"] = {"nvidia.com/gpu": "1"}
        pod_spec["nodeSelector"] = {"accelerator": "nvidia"}
        pod_spec["tolerations"] = [
            {"key": "nvidia.com/gpu", "operator": "Exists", "effect": "NoSchedule"}
        ]

    # ── FPGA handling (legacy only — no DRA driver available) ─────────
    # ORCHIDE slide 14 uses separate node types (GPU vs FPGA), and one Pod asking
    # for both would be unschedulable. That cannot arise here now: the Job holds
    # one container from one step, so it has one resource class. A service that
    # mixes them stays legal, and the Argo render is what expresses it, as
    # separate Pods.
    if requires_fpga:
        container["resources"]["requests"]["xilinx.com/fpga"] = "1"
        container["resources"].setdefault("limits", {})["xilinx.com/fpga"] = "1"
        pod_spec["nodeSelector"] = {"accelerator": "fpga"}
        pod_spec["tolerations"] = [
            {"key": "xilinx.com/fpga", "operator": "Exists", "effect": "NoSchedule"}
        ]

    job_annotations: dict[str, str] = {
        "orbital/priority": str(intent.priority),
        "orbital/orchide-priority": str(scale_priority_orchide(intent.priority)),
        RAW_MISSION_ID_ANNOTATION: intent.mission_id,
        "orbital/executed-step": primary.name,
        # Named explicitly so an operator reading the applied Job can see that it
        # does not run the whole service, without having to diff it against the plan.
        "orbital/steps-not-in-this-job": ",".join(dropped),
        "orbital/kueue-artifact-role": "standalone-primary-step",
        # Named for what they describe: these are the projected Job's, and the
        # service-wide hints sit beside them so the two are not confused.
        "orbital/executed-step-resource-class": primary.resource_class.value,
        "orbital/requires-gpu": str(requires_gpu).lower(),
        "orbital/requires-fpga": str(requires_fpga).lower(),
        "orbital/fallback-enabled": str(primary.fallback_resource_class is not None).lower(),
        "orbital/service-requires-gpu": str(intent.resource_hints.get("requires_gpu", False)).lower(),
        "orbital/service-requires-fpga": str(intent.resource_hints.get("requires_fpga", False)).lower(),
    }

    job: dict[str, Any] = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "generateName": f"{sanitize_k8s_name(intent.workflow_name, max_len=62)}-",
            "namespace": namespace,
            "labels": {
                "kueue.x-k8s.io/queue-name": queue_name,
                MANAGED_BY_LABEL: MANAGED_BY_VALUE,
                MISSION_FINGERPRINT_LABEL: mission_fingerprint(intent.mission_id),
                "mission-id": sanitize_k8s_name(intent.mission_id),
                "service-id": sanitize_k8s_name(intent.service_id),
                "priority": str(intent.priority),
            },
            "annotations": _require_annotations_fit(
                job_annotations, f"Job for {intent.workflow_name}"
            ),
        },
        "spec": {
            "template": {
                "spec": pod_spec,
            },
        },
    }
    # Opt-in: a kueue.x-k8s.io/priority-class label that Kueue reads for queue
    # sorting and preemption eligibility. Off by default because the referenced
    # WorkloadPriorityClass must already exist in the cluster (Kueue errors on a
    # missing class); apply render_workload_priority_classes() first (or use the
    # CLI's --emit-priority-classes). The prefix must match the emitted classes.
    if priority_class:
        job["metadata"]["labels"]["kueue.x-k8s.io/priority-class"] = _priority_class_name(
            scale_priority_orchide(intent.priority), priority_class_prefix
        )
    return job


def _default_policy_bundle() -> str:
    """Locate the shipped Rego bundle without depending on the process CWD.

    The artifact commands default to the ``opa`` engine, so a bundle path that
    only resolves from the repository root makes the default path fail whenever
    the tool runs from anywhere else. Prefer a bundle packaged beside the module,
    then the checkout's ``configs/policies``, and fall back to the relative path
    so an explicit ``--bundle`` and the historical behaviour still work.
    """
    try:
        packaged = resources.files("orbital_mission_compiler") / "policies"
        if packaged.is_dir():
            return str(packaged)
    except (ModuleNotFoundError, TypeError):  # pragma: no cover - defensive
        pass
    checkout = Path(__file__).resolve().parents[2] / "configs" / "policies"
    if checkout.is_dir():
        return str(checkout)
    return "configs/policies"


DEFAULT_POLICY_BUNDLE = _default_policy_bundle()
DEFAULT_POLICY_DECISION = "data.orbitalmission"


class PolicyEngineUnavailableError(RuntimeError):
    """The selected policy engine could not render a decision (e.g. ``opa`` not
    installed, timeout, or an unparseable/undefined result).

    Enforcement fails **closed**: the compiler refuses to emit an artifact rather
    than silently downgrade to a different engine or skip the check. Distinct from
    ``PolicyViolationError`` (the plan was evaluated and denied).
    """


class PolicyViolationError(ValueError):
    """Raised when the plan violates a policy rule and enforcement is active.

    The file-level compile/render entrypoints are **fail-closed by default**: no
    artifact is produced for a plan the policy layer would deny. This realizes the
    paper's admission-gate claim -- "the compiler enforces four independent checks
    on every mission plan before any artifact is admitted to a cluster" (Sec. II).

    Enforcement runs through a selectable engine (``evaluate_policy_decision``):
    the authoritative ``opa`` engine executes the versioned, independently-auditable
    Rego bundle, and the ``baseline`` engine is the proven-equivalent in-process
    mirror. The four stages remain *independent modules* (Sec. VI): the
    enforcement-free primitives (``compile_plan_to_intents``, ``render_argo_workflow``,
    ``render_kueue_job``, ``baseline_validator``) are still callable in isolation.
    Only the file-level entrypoints (and the CLI/MCP that drive them) gate by
    default; each exposes an explicit ``enforce_policy=False`` / ``--unsafe-skip-policy``
    opt-out, matching the paper's caveat that a fully bypassed pipeline carries no
    guarantee.

    ``violations`` is the list of TYPED violation objects
    (``{rule, severity, provenance, path, message}``); ``messages`` is the string
    projection for backward-compatible consumers.
    """

    def __init__(self, violations: list[dict[str, Any]]) -> None:
        self.violations = list(violations)
        self.messages = [v["message"] for v in self.violations]
        joined = "; ".join(self.messages)
        super().__init__(
            f"policy denied the mission plan ({len(self.messages)} violation(s)): {joined}"
        )


_VIOLATION_KEYS = {"rule", "rule_id", "severity", "provenance", "path", "message"}


def _validate_typed_violation(item: Any) -> None:
    """Reject a violation whose fields are present but not usable.

    Key presence alone is not enough: a non-string message, for example, only
    surfaces later when the messages are joined for the error, as an unrelated
    TypeError far from the decision that produced it.
    """
    if not isinstance(item, dict) or not _VIOLATION_KEYS.issubset(item):
        raise PolicyEngineUnavailableError(
            f"policy decision carries a violation without the typed shape: {item!r}"
        )
    checks: list[tuple[str, bool]] = [
        ("rule", item["rule"] is None or (isinstance(item["rule"], int) and not isinstance(item["rule"], bool))),
        ("rule_id", isinstance(item["rule_id"], str) and bool(item["rule_id"])),
        ("severity", item["severity"] in {"T1", "T2", "T3", "T4"}),
        ("provenance", item["provenance"] in {"A", "D"}),
        ("path", isinstance(item["path"], str)),
        ("message", isinstance(item["message"], str) and bool(item["message"])),
    ]
    for field, ok in checks:
        if not ok:
            raise PolicyEngineUnavailableError(
                f"policy decision violation has an unusable {field!r}: {item!r}"
            )


def typed_violations_from_decision(value: Any) -> list[dict[str, Any]]:
    """Return the typed violations carried by an OPA decision value, or fail closed.

    A decision is only usable if its shape can be trusted, so this validates
    rather than probing for a key. Anything it cannot read as a decision, or that
    contradicts itself, raises ``PolicyEngineUnavailableError``: returning an
    empty list for an unreadable decision would admit the plan, which is the one
    outcome a fail-closed gate must never reach by accident. Ill-typed or
    contradictory results such as ``{"allow": false, "violations": []}`` or
    ``{"violations": ""}`` are therefore rejected, not silently admitted.

    A custom ``--decision`` exposing only the plain-string ``deny`` set is
    projected onto the typed shape, so every consumer sees one schema.
    """
    if not isinstance(value, dict):
        raise PolicyEngineUnavailableError(
            f"policy decision is not an object (got {type(value).__name__}); refusing to admit"
        )

    allow = value.get("allow")
    if "allow" in value and not isinstance(allow, bool):
        raise PolicyEngineUnavailableError(
            f"policy decision field 'allow' must be a boolean, got {allow!r}"
        )

    # `deny` is validated whenever it is present, even alongside `violations`:
    # parsing only one of them lets a decision that denies in the field this gate
    # ignores read as allowed.
    deny_messages: list[str] | None = None
    if "deny" in value:
        deny = value["deny"]
        if not isinstance(deny, list) or not all(isinstance(m, str) for m in deny):
            raise PolicyEngineUnavailableError(
                f"policy decision field 'deny' must be a list of strings, got {deny!r}"
            )
        deny_messages = list(deny)

    violations: list[dict[str, Any]] | None = None
    if "violations" in value:
        raw = value["violations"]
        if not isinstance(raw, list):
            raise PolicyEngineUnavailableError(
                f"policy decision field 'violations' must be a list, got {type(raw).__name__}"
            )
        for item in raw:
            _validate_typed_violation(item)
        violations = list(raw)
        if deny_messages is not None:
            # The bundle defines deny as the message projection of violations, so
            # comparing only emptiness would accept a decision that denies for one
            # reason in `deny` and a different one in `violations`, and every
            # consumer downstream would report whichever it happened to read.
            projected = {v["message"] for v in violations}
            if set(deny_messages) != projected:
                raise PolicyEngineUnavailableError(
                    "policy decision disagrees with itself: deny messages "
                    f"{sorted(set(deny_messages))} do not match the violation "
                    f"messages {sorted(projected)}"
                )
    elif deny_messages is not None:
        from .baseline_validator import STRUCTURAL_RULE_ID

        violations = [
            {
                "rule": None,
                "rule_id": STRUCTURAL_RULE_ID,
                "severity": "T1",
                "provenance": "A",
                "path": "",
                "message": m,
            }
            for m in deny_messages
        ]
    else:
        raise PolicyEngineUnavailableError(
            "policy decision carries neither a 'violations' nor a 'deny' set"
        )

    # A decision that says allowed while listing violations (or the reverse) is
    # not a decision this gate can act on.
    if isinstance(allow, bool) and allow == bool(violations):
        raise PolicyEngineUnavailableError(
            f"policy decision is contradictory: allow={allow} with {len(violations)} violation(s)"
        )
    return violations


def evaluate_policy_decision(
    plan: dict[str, Any],
    *,
    engine: str = "baseline",
    bundle: str = DEFAULT_POLICY_BUNDLE,
    decision: str = DEFAULT_POLICY_DECISION,
) -> list[dict[str, Any]]:
    """Return the typed policy violations for a plan dict via the selected engine.

    ``engine="opa"`` executes the versioned, independently-auditable Rego bundle
    via ``opa`` (honouring ``bundle``/``decision``) -- the authoritative
    policy-as-code path an external reviewer runs. It fails CLOSED
    (``PolicyEngineUnavailableError``) when ``opa`` is unavailable or the result is
    unparseable/undefined; it never silently downgrades to the baseline.
    ``engine="baseline"`` uses the proven-equivalent in-process mirror (no
    subprocess), for tests/benchmarks and offline use.
    """
    if engine == "baseline":
        from . import baseline_validator

        return baseline_validator.violations(plan)
    if engine == "opa":
        import json as _json

        from .policy import eval_policy, opa_available

        if not opa_available():
            raise PolicyEngineUnavailableError(
                "policy engine 'opa' selected but the opa CLI is not installed; "
                "install opa or pass --policy-engine=baseline"
            )
        rc, out = eval_policy(bundle, plan, decision)
        if rc != 0:
            raise PolicyEngineUnavailableError(f"opa evaluation failed (rc={rc}): {out}")
        try:
            value = _json.loads(out)["result"][0]["expressions"][0]["value"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise PolicyEngineUnavailableError(
                f"opa returned an unparseable decision: {out[:200]}"
            ) from exc
        # Raises PolicyEngineUnavailableError for a decision that cannot be
        # trusted, so an unreadable result never reads as "no violations".
        return typed_violations_from_decision(value)
    raise ValueError(f"unknown policy engine: {engine!r} (expected 'opa' or 'baseline')")


def enforce_policy_or_raise(
    plan: MissionPlan,
    *,
    engine: str = "baseline",
    bundle: str = DEFAULT_POLICY_BUNDLE,
    decision: str = DEFAULT_POLICY_DECISION,
) -> None:
    """Run the policy layer via the selected engine and fail closed on any deny."""
    violations = evaluate_policy_decision(
        plan.model_dump(mode="json"), engine=engine, bundle=bundle, decision=decision
    )
    if violations:
        raise PolicyViolationError(violations)


def render_workflows_for_file(
    input_path: str | Path | MissionPlan,
    enforce_policy: bool = True,
    *,
    policy_engine: str = "baseline",
    bundle: str = DEFAULT_POLICY_BUNDLE,
    decision: str = DEFAULT_POLICY_DECISION,
    dra_fallback: bool = False,
    namespace: str | None = None,
) -> list[dict[str, Any]]:
    """Render the Kubernetes objects for a plan file.

    Under ``dra_fallback`` this returns the ResourceClaimTemplate ahead of each
    Workflow that references it. Returning the Workflow alone would hand the
    caller a manifest naming a template that this function never produced, and
    the reference would not resolve.
    """
    plan = _load_or_accept_plan(input_path)
    if enforce_policy:
        enforce_policy_or_raise(plan, engine=policy_engine, bundle=bundle, decision=decision)
    if dra_fallback and namespace is None:
        namespace = DRA_DEFAULT_NAMESPACE
    intents = compile_plan_to_intents(plan)
    objects: list[dict[str, Any]] = []
    for intent in intents:
        rct = _first_available_rct(intent, namespace) if dra_fallback else None
        if rct is not None:
            objects.append(rct)
        objects.append(
            render_argo_workflow(intent, dra_fallback=dra_fallback, namespace=namespace)
        )
    return objects


def _load_or_accept_plan(source: str | Path | MissionPlan) -> MissionPlan:
    """Accept a plan file or an already-loaded plan.

    A caller that evaluated the policy layer itself has to be able to render the
    exact object it judged. Handing the path back to the renderer means the file
    is read twice, and a file that changes between the two reads gets the verdict
    of the content that was reviewed applied to content that was not.
    """
    if isinstance(source, MissionPlan):
        return source
    return load_mission_plan(source)


# How a leftover artifact is told from a file that happened to be in the output
# directory. Not the `orbital/` prefix: that is an ordinary label namespace an
# operator may already be using, and keying deletion on it means --prune removes
# their files. This label is stamped by the renderers below and by nothing else.
MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "orbital-mission-compiler"

# Which mission an artifact belongs to, for deciding what a render may replace or
# remove. Not the `mission-id` label: that one is sanitized for display, and
# sanitizing is lossy -- `foo_bar`, `foo.bar` and `FOO-BAR` all become `foo-bar`,
# so keying ownership on it lets one mission delete or overwrite another's
# output. The raw id is kept in an annotation alongside, where it needs no
# sanitizing, so an operator can still read what it was.
# A DRA bundle's two documents have to share a namespace, so that mode supplies
# one when the caller did not. An ordinary render stays namespace-less, and the
# namespace is chosen when the manifest is applied.
DRA_DEFAULT_NAMESPACE = "orbital-demo"

# Kubernetes refuses an object whose annotations exceed this in total, keys and
# values together. Verified against a live API server: "metadata.annotations:
# Too long: may not be more than 262144 bytes". Counted in UTF-8 bytes, not
# characters, because that is what the API server counts.
MAX_ANNOTATION_BYTES = 262144


def _require_annotations_fit(annotations: dict[str, str], what: str) -> dict[str, str]:
    """Refuse to render an object the API server would reject for size.

    Identifiers from the plan are copied into annotations verbatim, and nothing
    in the schema bounds their length, so a plan that is otherwise valid can
    render a manifest that fails at apply -- which is the failure this compiler
    exists to move earlier.
    """
    total = sum(len(k.encode("utf-8")) + len(str(v).encode("utf-8")) for k, v in annotations.items())
    if total > MAX_ANNOTATION_BYTES:
        raise ValueError(
            f"{what} would carry {total} bytes of annotations, over the {MAX_ANNOTATION_BYTES} "
            "the API server accepts; shorten the mission, service or step identifiers"
        )
    return annotations


MISSION_FINGERPRINT_LABEL = "orbital/mission-fingerprint"
RAW_MISSION_ID_ANNOTATION = "orbital/raw-mission-id"


def mission_fingerprint(mission_id: str) -> str:
    """A lossless identity for a mission, safe to use as a label value."""
    return hashlib.sha256(mission_id.encode("utf-8")).hexdigest()[:16]


def _is_rendered_artifact(path: Path) -> bool:
    """Whether every document in this file is output this tool wrote.

    Every document, not any: a file holding one of our manifests and one of the
    operator's would otherwise be deleted whole by --prune.

    Anything unreadable is not ours. The read is deliberately broad about what it
    catches -- a file that is not valid UTF-8, or nests deeply enough to exhaust
    the parser, is still just a file in a directory, and letting that abort a
    render that has already written its output would strand the caller with
    artifacts on disk and no result.
    """
    try:
        docs = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8"))]
    except Exception:  # noqa: BLE001 - see the docstring: unreadable means not ours
        return False
    if not docs:
        return False
    for doc in docs:
        if not isinstance(doc, dict):
            return False
        meta = doc.get("metadata")
        labels = meta.get("labels") if isinstance(meta, dict) else None
        if not isinstance(labels, dict) or labels.get(MANAGED_BY_LABEL) != MANAGED_BY_VALUE:
            return False
    return True


def _artifact_mission(path: Path) -> str | None:
    """The mission fingerprint every document in this file carries, if they agree."""
    try:
        docs = [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8"))]
    except Exception:  # noqa: BLE001 - unreadable is not ours; see _is_rendered_artifact
        return None
    missions = {
        (d.get("metadata") or {}).get("labels", {}).get(MISSION_FINGERPRINT_LABEL)
        for d in docs
        if isinstance(d, dict)
    }
    return missions.pop() if len(missions) == 1 else None


def stale_rendered_artifacts(output_dir: str | Path, written: list[Path]) -> list[Path]:
    """Artifacts from an earlier render that this one did not replace.

    A render writes the files the current plan produces; it does not empty the
    directory first. When a plan shrinks -- a service removed, an event dropped --
    the manifests for what is gone stay behind, and the documented ``kubectl
    apply -f <dir>`` redeploys exactly the workloads the plan no longer asks for.
    The output is a complete set of what the plan describes, which is not the
    same as the directory being a picture of it.

    Only files carrying this tool's own label namespace are reported, so an
    operator who keeps other manifests alongside is not told they are stale.
    """
    out = Path(output_dir)
    if not out.is_dir():
        return []
    current = {p.resolve() for p in written}
    # Scoped to the missions this render just wrote. Ownership alone is not
    # enough to delete by: another mission's manifests in the same directory
    # carry the same managed-by label and are equally ours, but they are not
    # this render's to remove. Objects without a mission -- the cluster-scoped
    # WorkloadPriorityClasses the other renderer emits -- are never in scope.
    missions = {m for m in (_artifact_mission(p) for p in written) if m}
    if not missions:
        return []
    return sorted(
        p for p in out.glob("*.yaml")
        if p.resolve() not in current
        and _is_rendered_artifact(p)
        and _artifact_mission(p) in missions
    )


def preflight_writable(planned: list[tuple[Path, Any]]) -> None:
    """Refuse to overwrite an artifact this render does not own.

    Two missions whose ids sanitize alike -- `foo_bar` and `foo.bar` both become
    `foo-bar` -- produce the same filename for the same service and timestamp, so
    rendering the second into the same directory replaced the first with no
    warning and no way to notice. A file already at a planned path may only be
    replaced when it is this tool's output for the same mission; anything else,
    including a file the compiler did not write, is left alone and reported.
    """
    conflicts: list[str] = []
    for path, rendered in planned:
        if path.is_symlink():
            # Asked before `exists()`, which follows the link: a link with no
            # target reads as absent, and the planned path would then be taken
            # for free space. Not followed to decide ownership either -- what
            # the link points at says nothing about the entry this render would
            # replace.
            conflicts.append(f"{path} is a symlink")
            continue
        if not path.exists():
            continue
        if not _is_rendered_artifact(path):
            conflicts.append(f"{path} was not written by this compiler")
            continue
        theirs = _artifact_mission(path)
        ours = _rendered_mission(rendered)
        if theirs != ours:
            conflicts.append(f"{path} belongs to a different mission")
    if conflicts:
        raise ValueError(
            "refusing to overwrite output this render does not own: "
            + "; ".join(conflicts)
        )


def _rendered_mission(rendered: str | list[Any]) -> str | None:
    """The mission fingerprint carried by a rendered document set.

    Accepts either the serialized text or the documents themselves, because the
    two writers hold their pending output in different shapes.
    """
    if isinstance(rendered, str):
        try:
            docs: list[Any] = list(yaml.safe_load_all(rendered))
        except yaml.YAMLError:
            return None
    else:
        docs = list(rendered)
    marks = {
        (d.get("metadata") or {}).get("labels", {}).get(MISSION_FINGERPRINT_LABEL)
        for d in docs
        if isinstance(d, dict)
    }
    return marks.pop() if len(marks) == 1 else None


def _default_file_mode() -> int:
    """The mode `open()` would give a new file under this process's umask.

    Read once, at import: `os.umask` is process-wide, and reading it means
    setting it, which is not something to do while other threads are writing.
    """
    umask = os.umask(0)
    os.umask(umask)
    return 0o666 & ~umask


_DEFAULT_FILE_MODE = _default_file_mode()


def atomic_write(path: Path, text: str) -> None:
    """Write by renaming a sibling temporary file into place.

    `Path.write_text` opens the destination, which follows a symlink: a link
    planted in the output directory redirects the write outside it, past the
    ownership check. A rename replaces the directory entry instead, so the link
    itself is what goes. It also means a reader never sees a half-written file.

    The mode is set back to what the umask would have given, because
    `mkstemp` creates 0600 and `os.replace` keeps it -- publishing by rename
    would otherwise narrow every rendered artifact to its owner, and the
    operator who applies the output is not always the one who rendered it.
    """
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, _DEFAULT_FILE_MODE)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def preflight_unique(paths: list[Path]) -> None:
    """Fail before writing when two renders would land on the same file.

    Names are disambiguated at compile time, so a duplicate here means a naming
    invariant broke. Catching it before the first write keeps the output
    directory from ending up with one artifact silently replaced by another.
    """
    seen: set[Path] = set()
    duplicates = sorted({p for p in paths if p in seen or seen.add(p)})  # type: ignore[func-returns-value]
    if duplicates:
        raise ValueError(
            f"refusing to write: {len(duplicates)} output path(s) would be written twice: "
            + ", ".join(str(p) for p in duplicates)
        )


def write_individual_workflows(
    input_path: str | Path | MissionPlan,
    output_dir: str | Path,
    enforce_policy: bool = True,
    *,
    policy_engine: str = "baseline",
    bundle: str = DEFAULT_POLICY_BUNDLE,
    decision: str = DEFAULT_POLICY_DECISION,
    dra_fallback: bool = False,
    namespace: str | None = None,
    service_account: str | None = None,
) -> list[Path]:
    """Write one Argo manifest file per intent.

    With ``dra_fallback``, an intent whose accelerator-fallback step is
    driver-backed produces a **self-contained multi-doc file**: the scheduler-route
    ``firstAvailable`` ResourceClaimTemplate followed by the DRA-wired Workflow that
    references it (via ``podSpecPatch``), so the claim template is not an orphan.

    Apply it with ``kubectl apply -f``, which creates both documents. ``argo
    submit`` will NOT work for this file: its parser keeps only ``Workflow``
    kinds and logs the ResourceClaimTemplate as ignored, so the Workflow would be
    created referencing a template that was never applied. Use ``kubectl apply``
    for the bundle, or apply the template first and then submit the Workflow.

    Both documents carry ``namespace``. A ResourceClaimTemplate is namespaced and a
    Pod resolves a template only within its own namespace, so a Workflow left to the
    caller's current context could land beside a template it cannot reference.
    """
    plan = _load_or_accept_plan(input_path)
    if enforce_policy:
        enforce_policy_or_raise(plan, engine=policy_engine, bundle=bundle, decision=decision)
    if dra_fallback and namespace is None:
        namespace = DRA_DEFAULT_NAMESPACE
    intents = compile_plan_to_intents(plan)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    planned: list[tuple[Path, list[dict[str, Any]]]] = []
    for intent in intents:
        rct = _first_available_rct(intent, namespace) if dra_fallback else None
        # Stamp the namespace only when the template ships with the Workflow:
        # the two must agree for the Pod to resolve it. A plain render keeps its
        # previous namespace-less output, so a caller that selects the namespace
        # at apply time (kubectl -n / argo submit -n) is unaffected.
        workflow = render_argo_workflow(
            intent,
            dra_fallback=dra_fallback,
            namespace=namespace,
            service_account=service_account,
        )
        out = out_dir / f"{workflow['metadata']['name']}.yaml"
        planned.append((out, [rct, workflow] if rct is not None else [workflow]))

    preflight_unique([path for path, _ in planned])
    preflight_writable(planned)
    for out, docs in planned:
        if len(docs) > 1:
            atomic_write(out, yaml.safe_dump_all(docs, sort_keys=False))
        else:
            atomic_write(out, yaml.safe_dump(docs[0], sort_keys=False))
        written.append(out)
    return written


def compile_file(
    input_path: str | Path | MissionPlan,
    output_path: str | Path,
    enforce_policy: bool = True,
    *,
    policy_engine: str = "baseline",
    bundle: str = DEFAULT_POLICY_BUNDLE,
    decision: str = DEFAULT_POLICY_DECISION,
) -> dict[str, Any]:
    plan = _load_or_accept_plan(input_path)
    if enforce_policy:
        enforce_policy_or_raise(plan, engine=policy_engine, bundle=bundle, decision=decision)
    intents = compile_plan_to_intents(plan)
    payload = {
        "mission_id": plan.mission_id,
        "intents": [intent.model_dump(mode="json") for intent in intents],
        "workflows": [render_argo_workflow(intent) for intent in intents],
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(out, yaml.safe_dump(payload, sort_keys=False))
    return payload
