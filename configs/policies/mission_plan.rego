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
  not step.fallback_resource_class
  msg := sprintf("GPU step %q should declare fallback_resource_class for local demo reliability", [step.name])
}

allow if count(deny) == 0
