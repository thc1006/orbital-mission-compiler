package orbitalmission

import rego.v1

default allow := false

# Structured, occurrence-level policy decisions. Each violation carries the deny
# message, the machine-readable severity tier (T1-T4) and provenance (A =
# author-imposed, D = ORCHIDE-derived, paper Table II/III), and a JSON-Pointer
# `path` to the exact offending node so two structurally-identical offenders are
# distinct set members (aligning the Rego set with the Python baseline's list on
# multiplicity). The plain-string `deny` set is the message projection of
# `violations`, so the accept/reject decision is unchanged.

# Per-rule severity tier and provenance, authoritative from paper Table II/III:
# T1{1,2}, T2{4,6}, T3{7,8}, T4{3,5,9,10}; 1A 2A 3D 4A 5A 6A 7D 8D 9A 10D.
_rule_meta := {
	1: {"severity": "T1", "provenance": "A"},
	2: {"severity": "T1", "provenance": "A"},
	3: {"severity": "T4", "provenance": "D"},
	4: {"severity": "T2", "provenance": "A"},
	5: {"severity": "T4", "provenance": "A"},
	6: {"severity": "T2", "provenance": "A"},
	7: {"severity": "T3", "provenance": "D"},
	8: {"severity": "T3", "provenance": "D"},
	9: {"severity": "T4", "provenance": "A"},
	10: {"severity": "T4", "provenance": "D"},
}

# Stable identifier for consumers that key on the rule rather than reading the
# message. Mirrors baseline_validator.rule_id: `OMP-004` for numbered rules, and
# one shared id for the structural guard, which is not a numbered paper rule.
_rule_id(rule) := sprintf("OMP-%03d", [rule])

_viol(rule, msg, path) := {
	"rule": rule,
	"rule_id": _rule_id(rule),
	"severity": _rule_meta[rule].severity,
	"provenance": _rule_meta[rule].provenance,
	"path": path,
	"message": msg,
}

# Structural fail-closed guard for malformed raw-JSON input (rule = null, T1/A).
_sviol(msg, path) := {
	"rule": null,
	"rule_id": "OMP-STRUCTURAL",
	"severity": "T1",
	"provenance": "A",
	"path": path,
	"message": msg,
}

# Normalized length of a services/steps container, mirroring the Python baseline's
# `_as_list`: an absent or JSON `null` value counts as 0 (treated as empty, so the
# emptiness rule fires), a list counts as its length, and a present non-list scalar
# is UNDEFINED (so the emptiness rule does not fire -- the structural guard reports
# it instead). Without this, `count(object.get(..., []))` on a present `null` is
# undefined and the emptiness rule silently vanishes (a fail-open on the bypass path).
_len_or_zero(container, key) := count(v) if {
	v := object.get(container, key, [])
	is_array(v)
}

_len_or_zero(container, key) := 0 if {
	object.get(container, key, "__absent__") == null
}

# ── Structural fail-closed guards ────────────────────────────────────────
# Pydantic catches these at Stage 1; on the raw-JSON bypass path both engines
# must fail closed on malformed structure (defense-in-depth, Section III).

# events present but not an array.
violations contains _sviol("events must be a list", "/events") if {
	ev := object.get(input, "events", null)
	ev != null
	not is_array(ev)
}

# an event that is not an object.
violations contains _sviol(sprintf("event %d must be an object", [i]), sprintf("/events/%d", [i])) if {
	is_array(input.events)
	some i
	event := input.events[i]
	not is_object(event)
}

# an event whose services field is present but not an array.
violations contains _sviol(sprintf("event %d services must be a list", [i]), sprintf("/events/%d/services", [i])) if {
	is_array(input.events)
	some i
	is_object(input.events[i])
	sv := object.get(input.events[i], "services", null)
	sv != null
	not is_array(sv)
}

# a service that is not an object.
violations contains _sviol("service must be an object", sprintf("/events/%d/services/%d", [i, j])) if {
	some i, j
	services := input.events[i].services
	is_array(services)
	svc := services[j]
	not is_object(svc)
}

# a service whose steps field is present but not an array.
violations contains _sviol("service steps must be a list", sprintf("/events/%d/services/%d/steps", [i, j])) if {
	some i, j
	is_object(input.events[i].services[j])
	st := object.get(input.events[i].services[j], "steps", null)
	st != null
	not is_array(st)
}

# a step that is not an object.
violations contains _sviol("step must be an object", sprintf("/events/%d/services/%d/steps/%d", [i, j, k])) if {
	some i, j, k
	steps := input.events[i].services[j].steps
	is_array(steps)
	step := steps[k]
	not is_object(step)
}

# ── Rule 1: mission_id must not be null/absent or a blank string ──────────
violations contains _viol(1, "mission_id must not be empty", "/mission_id") if {
	object.get(input, "mission_id", null) == null
}

violations contains _viol(1, "mission_id must not be empty", "/mission_id") if {
	mission_id := object.get(input, "mission_id", "")
	is_string(mission_id)
	trim_space(mission_id) == ""
}

# ── Rule 2: the plan must contain at least one event ─────────────────────
# Fires on a missing events key (matches the Python baseline treating missing
# as empty) and on a present-but-empty array.
violations contains _viol(2, "mission plan must contain at least one event", "/events") if {
	object.get(input, "events", null) == null
}

violations contains _viol(2, "mission plan must contain at least one event", "/events") if {
	is_array(input.events)
	count(input.events) == 0
}

# ── Rule 3: an acquisition event must declare at least one service ───────
violations contains _viol(3, msg, sprintf("/events/%d/services", [i])) if {
	some i
	event := input.events[i]
	is_object(event)
	event.event_type == "acquisition"
	_len_or_zero(event, "services") == 0
	msg := sprintf("acquisition event %v must declare at least one service", [i])
}

# ── Rule 4: any accelerator-bound step (GPU/FPGA) must declare a *usable*
# fallback -- present AND resolving to CPU, the only driver-backed
# non-accelerator target. A fallback equal to the primary class (or any non-CPU
# class) is not a real fallback. The trigger is resource_class alone (NOT the
# optional needs_acceleration flag, which could otherwise be omitted to bypass).
_accelerator_bound(step) if step.resource_class == "gpu"

_accelerator_bound(step) if step.resource_class == "fpga"

# 4a: fallback absent/null.
violations contains _viol(4, msg, sprintf("/events/%d/services/%d/steps/%d", [i, j, k])) if {
	some i, j, k
	step := input.events[i].services[j].steps[k]
	is_object(step)
	_accelerator_bound(step)
	object.get(step, "fallback_resource_class", null) == null
	msg := sprintf("accelerator step %q (resource_class %q) must declare fallback_resource_class", [object.get(step, "name", ""), step.resource_class])
}

# 4b: fallback present but not CPU (e.g. gpu->gpu or gpu->fpga is not usable).
violations contains _viol(4, msg, sprintf("/events/%d/services/%d/steps/%d", [i, j, k])) if {
	some i, j, k
	step := input.events[i].services[j].steps[k]
	is_object(step)
	_accelerator_bound(step)
	fb := object.get(step, "fallback_resource_class", null)
	fb != null
	fb != "cpu"
	msg := sprintf("accelerator step %q (resource_class %q) declares fallback_resource_class %v, but the only usable fallback is %q", [object.get(step, "name", ""), step.resource_class, fb, "cpu"])
}

# ── Rule 5: service priority must not be zero ────────────────────────────
violations contains _viol(5, msg, sprintf("/events/%d/services/%d", [i, j])) if {
	some i, j
	svc := input.events[i].services[j]
	is_object(svc)
	svc.priority == 0
	msg := sprintf("service %q has zero priority, which is likely a misconfiguration", [object.get(svc, "service_id", "")])
}

# ── Rule 6: needs_acceleration on CPU is contradictory ───────────────────
violations contains _viol(6, msg, sprintf("/events/%d/services/%d/steps/%d", [i, j, k])) if {
	some i, j, k
	step := input.events[i].services[j].steps[k]
	is_object(step)
	step.resource_class == "cpu"
	step.needs_acceleration == true
	msg := sprintf("step %q claims needs_acceleration but uses cpu resource class", [object.get(step, "name", "")])
}

# ── Rule 7: download events must not carry AI services ───────────────────
violations contains _viol(7, msg, sprintf("/events/%d", [i])) if {
	some i
	event := input.events[i]
	is_object(event)
	event.event_type == "download"
	_len_or_zero(event, "services") > 0
	msg := sprintf("download event %v must not declare services (transmission only)", [i])
}

# ── Rule 8: download events require ground visibility ────────────────────
violations contains _viol(8, msg, sprintf("/events/%d", [i])) if {
	some i
	event := input.events[i]
	is_object(event)
	event.event_type == "download"
	object.get(event, "ground_visibility", false) != true
	msg := sprintf("download event %v requires ground_visibility (station must be visible for transmission)", [i])
}

# ── Rule 9: every service must have at least one step ────────────────────
violations contains _viol(9, msg, sprintf("/events/%d/services/%d", [i, j])) if {
	some i, j
	svc := input.events[i].services[j]
	is_object(svc)
	_len_or_zero(svc, "steps") == 0
	msg := sprintf("service %q has no steps and cannot produce a workflow", [object.get(svc, "service_id", "")])
}

# ── Rule 10: landscape_type, when present, must be a recognized value ─────
# Optional field: a null/absent value is permitted; only a PRESENT unrecognized
# value denies. is_string/!=null guards avoid treating a normalized null as
# "present" (null is truthy in Rego).
valid_landscape_types := {"ocean", "land"}

# (a) present, string, but not a recognized value.
violations contains _viol(10, msg, sprintf("/events/%d/services/%d", [i, j])) if {
	some i, j
	svc := input.events[i].services[j]
	is_object(svc)
	is_string(svc.landscape_type)
	not svc.landscape_type in valid_landscape_types
	msg := sprintf("service %q has unrecognized landscape_type %q (expected: ocean, land)", [object.get(svc, "service_id", ""), svc.landscape_type])
}

# (b) present, but not a string (raw-JSON-bypass defense-in-depth).
violations contains _viol(10, msg, sprintf("/events/%d/services/%d", [i, j])) if {
	some i, j
	svc := input.events[i].services[j]
	is_object(svc)
	object.get(svc, "landscape_type", null) != null
	not is_string(svc.landscape_type)
	msg := sprintf("service %q has a non-string landscape_type (expected a string: ocean or land)", [object.get(svc, "service_id", "")])
}

# deny is the message projection of violations.
deny contains msg if {
	some v in violations
	msg := v.message
}

allow if count(deny) == 0
