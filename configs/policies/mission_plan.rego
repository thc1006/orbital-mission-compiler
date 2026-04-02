package orbitalmission

default allow := false

allow if {
  input.mission_id != ""
  count(input.events) > 0
  every event in input.events {
    valid_event(event)
  }
}

valid_event(event) if {
  event.timestamp != ""
  event.event_type == "acquisition" or event.event_type == "download"
}
