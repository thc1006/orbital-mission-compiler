"""Tests for ORCHIDE slide 9 schema alignment.

Each test targets a specific field from the ORCHIDE mission plan table (slide 9).
Fields: DATESZ, ORBIT, EV, DT_EV, INST, TYPE, VISI, WORKFLOW, PRIORITY.
"""

from orbital_mission_compiler.schemas import (
    MissionEvent,
    MissionEventType,
    AIService,
    WorkflowStep,
    ResourceClass,
)
from orbital_mission_compiler.compiler import load_mission_plan


# ── Slide 9: ORBIT field ───────────────────────────────────────────────


def test_mission_event_accepts_orbit():
    """MissionEvent should accept an orbit number (slide 9: ORBIT column)."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        orbit=1,
        instrument="INST_1",
    )
    assert event.orbit == 1


def test_mission_event_orbit_optional():
    """Orbit is optional for backward compatibility with existing plans."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        instrument="INST_1",
    )
    assert event.orbit is None


# ── Slide 9: DT_EV field ──────────────────────────────────────────────


def test_mission_event_accepts_duration():
    """MissionEvent should accept event duration in seconds (slide 9: DT_EV)."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        instrument="INST_1",
        duration_seconds=4.0,
    )
    assert event.duration_seconds == 4.0


def test_mission_event_duration_optional():
    """Duration is optional for backward compatibility."""
    event = MissionEvent(
        timestamp="2029-10-06T00:23:00Z",
        event_type=MissionEventType.ACQUISITION,
        instrument="INST_1",
    )
    assert event.duration_seconds is None


# ── Slide 9: TYPE_D1-D4 (per-service landscape type) ──────────────────


def test_ai_service_accepts_landscape_type():
    """AIService should accept landscape_type (slide 9: TYPE per detector)."""
    svc = AIService(
        service_id="maritime-surveillance",
        priority=1,
        landscape_type="ocean",
        steps=[
            WorkflowStep(name="detect", image="example:latest", resource_class=ResourceClass.CPU),
        ],
    )
    assert svc.landscape_type == "ocean"


def test_ai_service_landscape_type_optional():
    """Landscape type is optional for backward compatibility."""
    svc = AIService(
        service_id="test",
        priority=50,
        steps=[
            WorkflowStep(name="step", image="example:latest"),
        ],
    )
    assert svc.landscape_type is None


# ── Full ORCHIDE-format plan loading ──────────────────────────────────


def test_orchide_format_plan_loads():
    """A plan using ORCHIDE slide 9 fields should load and validate."""
    plan = load_mission_plan("configs/mission_plans/sample_orchide_format.yaml")
    assert plan.mission_id == "mission-orchide-demo"

    acq = plan.events[0]
    assert acq.orbit == 1
    assert acq.duration_seconds == 4.0
    assert acq.event_type == MissionEventType.ACQUISITION

    assert len(acq.services) == 2
    assert acq.services[0].landscape_type == "ocean"
    assert acq.services[1].landscape_type == "ocean"


def test_existing_plans_still_load():
    """Existing sample plans must remain valid after schema expansion."""
    plan_a = load_mission_plan("configs/mission_plans/sample_maritime_surveillance.yaml")
    assert plan_a.mission_id == "mission-alpha"
    assert plan_a.events[0].orbit is None
    assert plan_a.events[0].duration_seconds is None

    plan_b = load_mission_plan("configs/mission_plans/sample_gpu_cpu_fallback.yaml")
    assert plan_b.mission_id == "mission-beta"


# ── an unknown field is an error, not a silent default ───────────────


def test_a_misspelled_field_is_rejected_rather_than_dropped():
    """Pydantic ignores unknown keys by default, so a typo changes the mission
    instead of failing it.

    `execution_mod: parallel` leaves the service sequential and
    `fallback_resource_clas: cpu` leaves a GPU step with no fallback, and the
    plan is still reported schema-valid. The policy layer cannot recover the
    intent either: what it evaluates is the model dump, from which the
    misspelled key is already gone.
    """
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import AIService, MissionPlan, WorkflowStep

    with _pytest.raises(ValidationError, match="execution_mod"):
        AIService(
            service_id="s", priority=50, execution_mod="parallel",
            steps=[WorkflowStep(name="a", image="i")],
        )
    with _pytest.raises(ValidationError, match="fallback_resource_clas"):
        WorkflowStep(name="a", image="i", fallback_resource_clas="cpu")
    with _pytest.raises(ValidationError, match="commandd"):
        WorkflowStep(name="a", image="i", commandd=["sh"])
    # Every required field present, so the only reason to reject is the unknown
    # one. Spelling it `mission_i` instead would drop `mission_id` and raise for
    # a missing required field whether or not extra fields are forbidden.
    good_event = {
        "timestamp": "2026-08-01T00:00:00Z", "event_type": "acquisition",
        "instrument": "cam", "duration_seconds": 60,
        "services": [{"service_id": "s", "priority": 50,
                      "steps": [{"name": "a", "image": "i"}]}],
    }
    MissionPlan.model_validate({"mission_id": "m", "events": [good_event]})  # baseline
    with _pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        MissionPlan.model_validate(
            {"mission_id": "m", "events": [good_event], "mision_notes": "typo"}
        )
    with _pytest.raises(ValidationError, match="extra_forbidden|Extra inputs"):
        MissionPlan.model_validate(
            {"mission_id": "m", "events": [{**good_event, "instrumnet": "cam"}]}
        )


def test_priority_true_is_not_priority_one():
    """YAML reads `yes`/`on`/`true` as booleans and Python reads `True` as 1, so
    an unguarded field turns `priority: yes` into the lowest ORCHIDE tier."""
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import AIService, WorkflowStep

    with _pytest.raises(ValidationError, match="boolean"):
        AIService(service_id="s", priority=True, steps=[WorkflowStep(name="a", image="i")])


def test_a_step_without_an_image_is_not_a_step():
    """Blank, not merely empty: a name of spaces sanitizes to a placeholder and
    an image of spaces reaches the API server as written."""
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import WorkflowStep

    for kwargs in ({"name": "a", "image": ""}, {"name": "a", "image": "   "},
                   {"name": "", "image": "i:1"}, {"name": "  ", "image": "i:1"}):
        with _pytest.raises(ValidationError, match="must not be blank"):
            WorkflowStep(**kwargs)
    WorkflowStep(name="a", image="busybox:1.36")


def test_node_selector_keys_and_values_are_checked_here_not_at_apply():
    """`preferred_node_selector` is copied into a node affinity selector, so a
    malformed key or an over-long value renders cleanly and is refused by the
    API server -- which is the failure this compiler exists to move earlier."""
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import WorkflowStep

    bad = [
        {"bad//prefix/key": "v"},
        {"UPPER/prefix": "v"},
        {"k": "v" * 64},
        {"-leading": "v"},
        {"trailing-": "v"},
        {"k": "not a label value"},
        {"a" * 64: "v"},
    ]
    for selector in bad:
        with _pytest.raises(ValidationError):
            WorkflowStep(name="a", image="i:1", preferred_node_selector=selector)

    for selector in (
        {"accelerator": "nvidia"},
        {"kubernetes.io/arch": "amd64"},
        {"node.example.com/pool": "gpu-a100"},
        {"k": ""},  # an empty value is a legal label value
    ):
        WorkflowStep(name="a", image="i:1", preferred_node_selector=selector)


def test_an_infinite_duration_is_not_a_duration():
    """YAML spells infinity `.inf`, Pydantic accepts it for a float by default,
    and it satisfies `ge=0`.

    It then reaches the timeline analysis, where `start + duration` swallows
    every later event: one infinite acquisition reports a conflict with an event
    five months away and puts a plausible-looking number of seconds on it.
    """
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import MissionEvent

    base = {
        "timestamp": "2026-08-01T00:00:00Z", "event_type": "acquisition",
        "instrument": "cam",
        "services": [{"service_id": "s", "priority": 50,
                      "steps": [{"name": "a", "image": "i:1"}]}],
    }
    MissionEvent.model_validate({**base, "duration_seconds": 60})
    for bad in (float("inf"), float("-inf"), float("nan")):
        with _pytest.raises(ValidationError):
            MissionEvent.model_validate({**base, "duration_seconds": bad})


def test_identifiers_that_name_artifacts_may_not_be_blank():
    """A value of spaces is truthy, so an emptiness check passes it through, and
    it then sanitizes to a placeholder in the name of every rendered object."""
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import AIService, MissionEvent, MissionPlan, WorkflowStep

    with _pytest.raises(ValidationError, match="blank"):
        MissionPlan(mission_id="   ", events=[])
    with _pytest.raises(ValidationError, match="blank"):
        AIService(service_id="   ", priority=50, steps=[WorkflowStep(name="a", image="i:1")])
    with _pytest.raises(ValidationError, match="instrument"):
        MissionEvent.model_validate({
            "timestamp": "2026-08-01T00:00:00Z", "event_type": "acquisition",
            "instrument": "   ", "duration_seconds": 60,
            "services": [{"service_id": "s", "priority": 50,
                          "steps": [{"name": "a", "image": "i:1"}]}],
        })


def test_yaml_merge_overrides_are_not_duplicate_keys():
    """A merge key followed by an explicit key is how YAML says "these defaults,
    but change this one".

    Scanning for duplicates after the merge source is flattened in conflates
    that with a key genuinely written twice, and rejects a document whose
    meaning YAML defines precisely.
    """
    import pytest as _pytest
    import yaml as _yaml

    from orbital_mission_compiler.compiler import _StrictLoader

    def load(text):
        return _yaml.load(text, Loader=_StrictLoader)

    override = "d: &d {image: 'busybox:1.36', resource_class: cpu}\ns:\n  <<: *d\n  image: 'alpine:3.20'\n"
    assert load(override)["s"] == _yaml.safe_load(override)["s"]
    assert load(override)["s"]["image"] == "alpine:3.20", "the explicit key must win"

    sequence = "a: &a {p: 1}\nb: &b {p: 2}\ns:\n  <<: [*a, *b]\n"
    assert load(sequence)["s"] == _yaml.safe_load(sequence)["s"]

    for genuinely_duplicated in ("a: 1\na: 2\n", "a:\n  b: 1\n  b: 2\n",
                                 "d: &d {p: 1}\ns:\n  <<: *d\n  q: 1\n  q: 2\n"):
        with _pytest.raises(_yaml.constructor.ConstructorError, match="duplicate key"):
            load(genuinely_duplicated)


def test_a_key_written_twice_inside_a_merge_source_is_still_a_duplicate():
    """The mapping a `<<:` pulls from is one the author wrote, so a key repeated
    inside it is the same ambiguity as one repeated anywhere else.

    `flatten_mapping` splices a merge source's pairs in without constructing it,
    and a source reached only through `<<:` is nobody's value, so scanning the
    merging mapping alone never looks at it.
    """
    import pytest as _pytest
    import yaml as _yaml

    from orbital_mission_compiler.compiler import _StrictLoader

    def load(text):
        return _yaml.load(text, Loader=_StrictLoader)

    hidden = {
        "inline": "s:\n  <<: {k: 1, k: 2}\n",
        "block": "s:\n  <<: &a\n    k: 1\n    k: 2\n",
        "sequence": "s:\n  <<: [{k: 1, k: 2}]\n",
        "nested": "d: &d\n  <<: {k: 1, k: 2}\ns:\n  <<: *d\n",
        "anchored value": "d: &d\n  k: 1\n  k: 2\ns:\n  <<: *d\n",
    }
    for where, text in hidden.items():
        # It loads under stock PyYAML, quietly keeping the last value -- which
        # is exactly what this loader exists to refuse.
        assert _yaml.safe_load(text)["s"]["k"] == 2, where
        with _pytest.raises(_yaml.constructor.ConstructorError, match="duplicate key"):
            load(text)

    # `<<` twice is a repeated key too, and the later one wins -- the opposite
    # of `<<: [a, b]`, where the earlier does. Same document, two readings.
    with _pytest.raises(_yaml.constructor.ConstructorError, match="duplicate merge key"):
        load("a: &a {k: 1}\nb: &b {k: 2}\ns:\n  <<: *a\n  <<: *b\n")

    # A mapping that merges itself has nothing to resolve, and scanning it
    # would not terminate.
    with _pytest.raises(_yaml.constructor.ConstructorError, match="refers to its own mapping"):
        load("s: &s\n  <<: *s\n  k: 1\n")

    # Still loads: the merge forms a plan may legitimately use.
    for legitimate in ("d: &d {k: 1, j: 9}\ns:\n  <<: *d\n  k: 2\n",
                       "a: &a {k: 1}\nb: &b {j: 2}\ns:\n  <<: [*a, *b]\n",
                       "a: &a {k: 1}\nb: &b\n  <<: *a\n  j: 2\ns:\n  <<: *b\n"):
        assert load(legitimate)["s"] == _yaml.safe_load(legitimate)["s"]


def test_an_inherited_key_overridden_and_then_reused_is_not_a_duplicate():
    """The scan reads each mapping once, and it has to.

    `flatten_mapping` splices a merge source's pairs into the front of the
    mapping that merges it and leaves them there, so a mapping that overrides an
    inherited key really does hold that key twice afterwards. Reading it again
    as some later mapping's merge source reports the override as a duplicate --
    and the pattern that breaks is the one merge keys exist for: shared step
    defaults, specialised once, used by more than one step.
    """
    import yaml as _yaml

    from orbital_mission_compiler.compiler import _StrictLoader

    doc = (
        "base: &base\n"
        "  image: 'busybox:1.36'\n"
        "  resource_class: cpu\n"
        "gpu_defaults: &gpu\n"
        "  <<: *base\n"
        "  resource_class: gpu\n"      # overrides the inherited value
        "step_one:\n"
        "  <<: *gpu\n"
        "  name: detect\n"
        "step_two:\n"                   # second reader of the flattened anchor
        "  <<: *gpu\n"
        "  name: track\n"
    )
    loaded = _yaml.load(doc, Loader=_StrictLoader)
    assert loaded == _yaml.safe_load(doc)
    assert loaded["step_two"]["resource_class"] == "gpu"
    assert loaded["step_two"]["image"] == "busybox:1.36"


def test_a_duplicate_hidden_in_a_merge_source_cannot_downgrade_a_gpu_step(tmp_path):
    """The concrete harm: sharing a step definition through an anchor is exactly
    what merge keys are for, and a second `resource_class` inside that anchor
    turns an accelerated step into a CPU one while the file still reads as GPU.
    """
    import pytest as _pytest
    import yaml as _yaml

    from orbital_mission_compiler.compiler import load_mission_plan

    plan = tmp_path / "plan.yaml"
    plan.write_text(
        "mission_id: m\n"
        "events:\n"
        "  - timestamp: '2026-08-01T00:00:00Z'\n"
        "    event_type: acquisition\n"
        "    instrument: cam\n"
        "    duration_seconds: 60\n"
        "    services:\n"
        "      - service_id: s\n"
        "        priority: 50\n"
        "        steps:\n"
        "          - <<: {name: detect, image: 'busybox:1.36',"
        " resource_class: gpu, resource_class: cpu}\n"
        "            fallback_resource_class: cpu\n",
        encoding="utf-8",
    )
    with _pytest.raises(_yaml.constructor.ConstructorError, match="duplicate key"):
        load_mission_plan(plan)


def test_a_boolean_is_not_an_orbit_a_duration_or_a_timestamp():
    """`orbit: true` is not orbit 1 and `duration_seconds: true` is not a
    one-second acquisition. A number where a date belongs is read as a Unix
    timestamp, so `timestamp: 0` names an artifact after 1970."""
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import MissionEvent

    base = {
        "timestamp": "2026-08-01T00:00:00Z", "event_type": "acquisition",
        "instrument": "cam", "duration_seconds": 60,
        "services": [{"service_id": "s", "priority": 50,
                      "steps": [{"name": "a", "image": "i:1"}]}],
    }
    for patch, expected in (
        ({"orbit": True}, "orbit"),
        ({"duration_seconds": True}, "duration_seconds"),
        ({"timestamp": 0}, "timestamp"),
        ({"timestamp": 1767225600}, "timestamp"),
    ):
        with _pytest.raises(ValidationError, match=expected):
            MissionEvent.model_validate({**base, **patch})
    MissionEvent.model_validate({**base, "orbit": 3, "duration_seconds": 60.5})


def test_a_quoted_number_must_read_as_the_number_it_becomes():
    """`priority: "50"` is how a templated plan writes fifty, so quoting a number
    stays legal. But pydantic coerces a string with Python's numeric grammar,
    which is wider than the one a reader applies: `'1_0'` is ten because Python
    allows underscores inside a literal, and `'6e2'` is six hundred.

    That is the same ambiguity the strict YAML loader refuses a repeated key
    for, so it is refused rather than resolved silently.
    """
    import pytest as _pytest
    from pydantic import ValidationError

    from orbital_mission_compiler.schemas import AIService, MissionEvent

    def event(**over):
        base = {
            "timestamp": "2026-08-01T00:00:00Z", "event_type": "acquisition",
            "instrument": "cam", "duration_seconds": 60,
            "services": [{"service_id": "s", "priority": 50,
                          "steps": [{"name": "a", "image": "i:1"}]}],
        }
        base.update(over)
        return base

    def service(priority):
        return {"service_id": "s", "priority": priority,
                "steps": [{"name": "a", "image": "i:1"}]}

    for field, value in [("orbit", "1_0"), ("duration_seconds", "1_000"),
                         ("duration_seconds", "6e2"), ("orbit", "0x10")]:
        with _pytest.raises(ValidationError):
            MissionEvent.model_validate(event(**{field: value}))
    with _pytest.raises(ValidationError):
        AIService.model_validate(service("1_0"))

    # Unambiguous forms are left alone: there is only one thing they can mean.
    assert MissionEvent.model_validate(event(orbit="1")).orbit == 1
    assert MissionEvent.model_validate(event(duration_seconds="60.5")).duration_seconds == 60.5
    assert MissionEvent.model_validate(event(duration_seconds=" 60 ")).duration_seconds == 60.0
    assert AIService.model_validate(service("50")).priority == 50
    assert AIService.model_validate(service("+50")).priority == 50
    # And a number written as a number is untouched.
    assert MissionEvent.model_validate(event(orbit=5)).orbit == 5
    assert AIService.model_validate(service(50)).priority == 50
