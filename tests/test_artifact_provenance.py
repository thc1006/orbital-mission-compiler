"""What a rendered file says about who owns it, rather than what is inferred.

Attribution used to be guessed from the kinds a file holds, and ownership from a
mission fingerprint that cluster-scoped artifacts do not carry. Both guesses
failed in ways that were measured:

- the RCT-only scheduler fallback holds no kind unique to either renderer, so the
  renderer that wrote it could not reclaim it;
- the priority-class bundle carries no mission, so a second installation's render
  replaced the first's classes with nothing raised;
- and a mission-scoped --prune deleted a cluster-scoped bundle another mission's
  Jobs still referenced.

So every document says who wrote it, for whom, and in what role.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from orbital_mission_compiler.cli import build_parser, cmd_render_argo, cmd_render_kueue
from orbital_mission_compiler.compiler import (
    ARTIFACT_ROLE_LABEL,
    OWNER_ID_ANNOTATION,
    OWNER_SCOPE_LABEL,
    OWNERSHIP_SCHEMA_LABEL,
    RENDERER_LABEL,
)

PLAN = "configs/mission_plans/demo_gpu_fallback_fixed.yaml"
OTHER_PLAN = "configs/mission_plans/sample_download_only.yaml"
BUNDLE = "workload-priority-classes.yaml"


def _docs(path: Path) -> list[dict]:
    return [d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d]


def _meta(doc: dict) -> tuple[dict, dict]:
    metadata = doc.get("metadata") or {}
    return metadata.get("labels") or {}, metadata.get("annotations") or {}


def _render(command, out: Path, *extra: str, plan: str = PLAN):
    argv = [command, "--input", plan, "--output-dir", str(out), "--policy-engine", "baseline", *extra]
    runner = cmd_render_kueue if command == "render-kueue" else cmd_render_argo
    runner(build_parser().parse_args(argv))


@pytest.mark.parametrize(
    "command,extra,renderer",
    [
        ("render-argo", ["--dra-fallback"], "argo"),
        ("render-kueue", ["--dra-fallback"], "kueue"),
    ],
)
def test_every_document_names_the_renderer_that_wrote_it(
    command, extra, renderer, tmp_path, capsys
):
    """Including the ResourceClaimTemplates, which both renderers emit.

    A kind both can write cannot say whose a file is, which is how the RCT-only
    fallback ended up owned by neither.
    """
    out = tmp_path / "out"
    _render(command, out, *extra)
    capsys.readouterr()

    seen = 0
    for path in sorted(out.glob("*.yaml")):
        for doc in _docs(path):
            labels, _ = _meta(doc)
            assert labels.get(RENDERER_LABEL) == renderer, (path.name, doc.get("kind"), labels)
            assert labels.get(OWNERSHIP_SCHEMA_LABEL), (path.name, labels)
            assert labels.get(ARTIFACT_ROLE_LABEL), (path.name, labels)
            seen += 1
    assert seen, "the render produced nothing to check"


def test_the_priority_class_bundle_is_owned_by_an_installation(tmp_path, capsys):
    """It is cluster-scoped, so a mission cannot be its owner.

    The prefix is what keeps two installations' classes from colliding in one
    cluster, so it is the identity the bundle belongs to.
    """
    out = tmp_path / "out"
    _render("render-kueue", out, "--emit-priority-classes", "--priority-class-prefix", "team-a-")
    capsys.readouterr()

    for doc in _docs(out / BUNDLE):
        labels, annotations = _meta(doc)
        assert labels.get(OWNER_SCOPE_LABEL) == "installation", labels
        assert annotations.get(OWNER_ID_ANNOTATION) == "team-a-", annotations


def test_a_second_installation_may_not_replace_the_first_s_bundle(tmp_path, capsys):
    """The silent overwrite.

    Both bundles are unmissioned, so the ownership check compared `None` with
    `None` and allowed it; the first installation's class names simply vanished
    while its Jobs went on naming them.
    """
    out = tmp_path / "out"
    _render("render-kueue", out, "--emit-priority-classes", "--priority-class-prefix", "team-a-")
    capsys.readouterr()
    before = (out / BUNDLE).read_text(encoding="utf-8")

    with pytest.raises(SystemExit):
        _render("render-kueue", out, "--emit-priority-classes", "--priority-class-prefix", "team-b-")

    assert (out / BUNDLE).read_text(encoding="utf-8") == before
    assert "team-a-" in before


def test_the_same_installation_may_replace_its_own_bundle(tmp_path, capsys):
    """The control: refusing everything would be no ownership check at all."""
    out = tmp_path / "out"
    for _ in range(2):
        _render("render-kueue", out, "--emit-priority-classes", "--priority-class-prefix", "team-a-")
    capsys.readouterr()

    assert "team-a-" in (out / BUNDLE).read_text(encoding="utf-8")


def test_an_ordinary_prune_leaves_the_cluster_scoped_bundle(tmp_path, capsys):
    """A mission-scoped run does not know whether anyone else still needs it.

    It reports the bundle rather than removing it, so the operator learns it is
    there without another mission's Jobs losing the classes they name.
    """
    out = tmp_path / "out"
    _render("render-kueue", out, "--emit-priority-classes")
    capsys.readouterr()
    _render("render-kueue", out, "--prune", plan=OTHER_PLAN)
    report = json.loads(capsys.readouterr().out)

    assert (out / BUNDLE).exists(), "an ordinary --prune must not delete a global artifact"
    assert BUNDLE in json.dumps(report), report


def test_pruning_the_bundle_takes_the_explicit_flag_and_the_owner(tmp_path, capsys):
    """And only from the installation that owns it."""
    out = tmp_path / "out"
    _render("render-kueue", out, "--emit-priority-classes", "--priority-class-prefix", "team-a-")
    capsys.readouterr()

    # Another installation asking for it does not get it, and is told so rather
    # than left to wonder why the directory still has it.
    _render("render-kueue", out, "--prune", "--prune-global",
            "--priority-class-prefix", "team-b-", plan=OTHER_PLAN)
    captured = capsys.readouterr()
    assert (out / BUNDLE).exists(), "another installation may not retire it either"
    assert BUNDLE in json.dumps(json.loads(captured.out).get("stale_other_installation", []))

    _render("render-kueue", out, "--prune", "--prune-global",
            "--priority-class-prefix", "team-a-", plan=OTHER_PLAN)
    capsys.readouterr()
    assert not (out / BUNDLE).exists()


def test_a_renderer_reclaims_its_own_rct_only_artifact(tmp_path, capsys):
    """The fallback nobody could delete.

    `*-scheduler-fallback.yaml` holds only a ResourceClaimTemplate, which both
    renderers emit, so kind-based attribution placed it with neither. Turning
    --dra-fallback off left it in the desired-state directory for good.
    """
    out = tmp_path / "out"
    _render("render-kueue", out, "--dra-fallback")
    capsys.readouterr()
    fallback = [p for p in out.glob("*scheduler-fallback.yaml")]
    assert fallback, sorted(p.name for p in out.iterdir())

    _render("render-kueue", out, "--prune")
    capsys.readouterr()

    assert not [p for p in out.glob("*scheduler-fallback.yaml")]


def test_the_other_renderer_still_does_not_touch_it(tmp_path, capsys):
    """Reclaimable by its writer is not the same as reclaimable by anyone."""
    out = tmp_path / "out"
    _render("render-kueue", out, "--dra-fallback")
    capsys.readouterr()

    _render("render-argo", out, "--prune")
    capsys.readouterr()

    assert [p for p in out.glob("*scheduler-fallback.yaml")]
