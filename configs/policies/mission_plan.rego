package orbitalmission

import rego.v1

default allow := false

deny contains msg if {
  input.mission_id == ""
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

deny contains msg if {
  some i, j, k
  step := input.events[i].services[j].steps[k]
  step.resource_class == "gpu"
  step.needs_acceleration == true
  _missing_fallback(step)
  msg := sprintf("GPU step %q with needs_acceleration should declare fallback_resource_class", [step.name])
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

# Rule 10: landscape_type must be a recognized value (slide 9: O=ocean, L=land)
valid_landscape_types := {"ocean", "land"}

deny contains msg if {
  some i, j
  svc := input.events[i].services[j]
  svc.landscape_type
  not svc.landscape_type in valid_landscape_types
  msg := sprintf("service %q has unrecognized landscape_type %q (expected: ocean, land)", [svc.service_id, svc.landscape_type])
}

allow if count(deny) == 0
