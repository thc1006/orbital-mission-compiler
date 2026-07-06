package orbitalmission

import rego.v1

default allow := false

deny contains msg if {
  object.get(input, "mission_id", null) == null
  msg := "mission_id must not be empty"
}

deny contains msg if {
  mission_id := object.get(input, "mission_id", "")
  is_string(mission_id)
  trim_space(mission_id) == ""
  msg := "mission_id must not be empty"
}

deny contains msg if {
  count(input.events) == 0
  msg := "mission plan must contain at least one event"
}

deny contains msg if {
  some i
  event := input.events[i]
  event.event_type == "acquisition"
  count(event.services) == 0
  msg := sprintf("acquisition event %v must declare at least one service", [i])
}

# Rule 4: any accelerator-bound step (GPU or FPGA) must declare a CPU
# fallback so the Deferred Phase can reschedule if the accelerator is
# unavailable. The trigger is the resource_class alone; it deliberately
# does NOT depend on needs_acceleration, which is optional and defaults
# to false, so relying on it would let a GPU/FPGA step silently bypass
# this safety check by simply omitting the flag.
_accelerator_bound(step) if step.resource_class == "gpu"
_accelerator_bound(step) if step.resource_class == "fpga"

deny contains msg if {
  some i, j, k
  step := input.events[i].services[j].steps[k]
  _accelerator_bound(step)
  _missing_fallback(step)
  msg := sprintf("accelerator step %q (resource_class %q) must declare fallback_resource_class", [step.name, step.resource_class])
}

# Handle both undefined (raw input) and null (schema-normalized input).
_missing_fallback(step) if not step.fallback_resource_class
_missing_fallback(step) if step.fallback_resource_class == null

# Rule 5: service priority must not be zero (slide 9: priorities are 1-4)
deny contains msg if {
  some i, j
  svc := input.events[i].services[j]
  svc.priority == 0
  msg := sprintf("service %q has zero priority, which is likely a misconfiguration", [svc.service_id])
}

# Rule 6: needs_acceleration on CPU is contradictory
deny contains msg if {
  some i, j, k
  step := input.events[i].services[j].steps[k]
  step.resource_class == "cpu"
  step.needs_acceleration == true
  msg := sprintf("step %q claims needs_acceleration but uses cpu resource class", [step.name])
}

# Rule 7: download events must not carry AI services (slide 9: DOWNLOAD has no WORKFLOW)
deny contains msg if {
  some i
  event := input.events[i]
  event.event_type == "download"
  count(event.services) > 0
  msg := sprintf("download event %v must not declare services (transmission only)", [i])
}

# Rule 8: download events require ground visibility (slide 9: DOWNLOAD VISI=1)
deny contains msg if {
  some i
  event := input.events[i]
  event.event_type == "download"
  not event.ground_visibility
  msg := sprintf("download event %v requires ground_visibility (station must be visible for transmission)", [i])
}

# Rule 9: every service must have at least one step
deny contains msg if {
  some i, j
  svc := input.events[i].services[j]
  count(svc.steps) == 0
  msg := sprintf("service %q has no steps and cannot produce a workflow", [svc.service_id])
}

# Rule 10: landscape_type, when present, must be a recognized value
# (slide 9: O=ocean, L=land). The field is optional, so a null or absent
# value is permitted; only a PRESENT unrecognized value denies.
#
# Two deny clauses give complete, layered coverage of "present unrecognized":
#   (a) a present non-{ocean,land} STRING (e.g. "desert"); and
#   (b) a present NON-string (e.g. a number) -- only reachable on the
#       raw-JSON schema-bypass path, since Pydantic rejects non-strings at
#       Stage 1, but included so the policy layer stays a complete redundant
#       checker for landscape validity on that path (defense-in-depth).
# We guard on is_string()/!=null rather than a bare `svc.landscape_type`,
# because Pydantic serializes an omitted Optional field to JSON null and, in
# Rego, null is truthy -- a bare guard would treat a normalized null as
# "present" and wrongly reject every plan that omits the field.
valid_landscape_types := {"ocean", "land"}

# (a) present, string, but not a recognized value
deny contains msg if {
  some i, j
  svc := input.events[i].services[j]
  is_string(svc.landscape_type)
  not svc.landscape_type in valid_landscape_types
  msg := sprintf("service %q has unrecognized landscape_type %q (expected: ocean, land)", [svc.service_id, svc.landscape_type])
}

# (b) present, but not a string (raw-JSON-bypass defense-in-depth)
deny contains msg if {
  some i, j
  svc := input.events[i].services[j]
  svc.landscape_type != null
  not is_string(svc.landscape_type)
  msg := sprintf("service %q has a non-string landscape_type (expected a string: ocean or land)", [svc.service_id])
}

allow if count(deny) == 0
