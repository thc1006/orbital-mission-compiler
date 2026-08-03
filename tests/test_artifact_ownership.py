"""Who a file in the output directory belongs to, when the answer is not one mission.

`--prune` deletes, so the question it asks has to be answerable. Inferring the
answer from a fingerprint that is either a mission or `None` cannot distinguish
"no document names a mission" from "some do and some do not", from "two名 disagree",
from "the label is not even a string" -- and the caller that reconciles
cluster-scoped artifacts admits everything that answered `None`.

Each case here was reproduced against the previous model before being written.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from orbital_mission_compiler.compiler import (
    ArtifactOwner,
    _artifact_mission,
    _is_rendered_artifact,
    stale_rendered_artifacts,
)

MANAGED = "app.kubernetes.io/managed-by: orbital-mission-compiler"


def _doc(kind: str, name: str, mission: str | None, raw_label: str | None = None) -> str:
    label = ""
    if raw_label is not None:
        label = f"    orbital/mission-fingerprint:\n{raw_label}\n"
    elif mission is not None:
        label = f"    orbital/mission-fingerprint: {mission}\n"
    return (
        f"apiVersion: v1\nkind: {kind}\nmetadata:\n  name: {name}\n  labels:\n"
        f"    {MANAGED}\n{label}"
    )


def _write(tmp_path: Path, name: str, *docs: str) -> Path:
    path = tmp_path / name
    path.write_text("---\n".join(docs), encoding="utf-8")
    return path


def test_every_document_naming_one_mission_is_that_mission(tmp_path):
    path = _write(tmp_path, "one.yaml", _doc("Job", "a", "aaaa"), _doc("Job", "b", "aaaa"))
    result = _artifact_mission(path)
    assert result.owner is ArtifactOwner.MISSION
    assert result.mission == "aaaa"


def test_no_document_naming_a_mission_is_unmissioned(tmp_path):
    path = _write(tmp_path, "global.yaml", _doc("WorkloadPriorityClass", "w", None))
    assert _artifact_mission(path).owner is ArtifactOwner.UNMISSIONED


def test_one_missioned_document_beside_an_unmissioned_one_is_mixed(tmp_path):
    """The case that lost data.

    `render-kueue` admits unmissioned files into its global reconciliation, and
    this file answered `None` exactly like the cluster-scoped bundle does, so an
    unrelated mission's --prune deleted a Job belonging to someone else.
    """
    path = _write(
        tmp_path, "mixed.yaml",
        _doc("Job", "j", "aaaa"),
        _doc("WorkloadPriorityClass", "w", None),
    )
    assert _artifact_mission(path).owner is ArtifactOwner.MIXED


def test_two_missions_in_one_file_is_mixed(tmp_path):
    path = _write(tmp_path, "two.yaml", _doc("Job", "a", "aaaa"), _doc("Job", "b", "bbbb"))
    assert _artifact_mission(path).owner is ArtifactOwner.MIXED


@pytest.mark.parametrize(
    "raw_label",
    ["      - a list", "      a: mapping", "      "],
    ids=["list", "mapping", "empty"],
)
def test_a_fingerprint_that_is_not_a_name_is_malformed(raw_label, tmp_path):
    """A list used to reach `set()` and raise TypeError: unhashable type.

    That surfaced as a traceback from a command that had usually already
    published, so the caller got no report and no exit code it could branch on.
    """
    path = _write(tmp_path, "bad.yaml", _doc("Job", "j", None, raw_label=raw_label))
    assert _artifact_mission(path).owner is ArtifactOwner.MALFORMED


def test_only_the_unmissioned_state_joins_global_reconciliation(tmp_path):
    """Mixed and malformed files stay, and stay visible.

    Erring toward a file that survives is the right direction for a delete.
    """
    _write(tmp_path, "global.yaml", _doc("WorkloadPriorityClass", "w", None))
    _write(tmp_path, "mixed.yaml", _doc("Job", "j", "aaaa"), _doc("Job", "w", None))
    _write(tmp_path, "malformed.yaml", _doc("Job", "j", None, raw_label="      - a list"))

    stale = stale_rendered_artifacts(tmp_path, [], mission_ids=set(), include_unmissioned=True)

    assert [p.name for p in stale] == ["global.yaml"]


def test_a_symlink_is_never_this_compiler_s_artifact(tmp_path):
    """Classified from the target's bytes, then unlinked as the link.

    `path.is_file()` follows the link, so an operator's symlink pointing at a
    managed file was read as managed and removed by --prune, destroying the link
    and leaving the file it named.
    """
    target = tmp_path / "target.yaml"
    target.write_text(_doc("Job", "j", "aaaa"), encoding="utf-8")
    link = tmp_path / "link.yaml"
    link.symlink_to(target)

    assert _is_rendered_artifact(target)
    assert not _is_rendered_artifact(link)
    assert _artifact_mission(link).owner is not ArtifactOwner.MISSION


def test_prune_does_not_reach_a_symlink(tmp_path):
    """The end of the same story, at the level that does the deleting."""
    out = tmp_path / "out"
    out.mkdir()
    target = tmp_path / "elsewhere.yaml"
    target.write_text(_doc("Job", "j", "aaaa"), encoding="utf-8")
    (out / "link.yaml").symlink_to(target)

    stale = stale_rendered_artifacts(out, [], mission_ids={"aaaa"})

    assert stale == []


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no mkfifo on this platform")
def test_a_named_pipe_is_not_read(tmp_path):
    """Reading it would block while the publish lock is held.

    The old guard got this right through `is_file()`; the replacement has to keep
    it, which is why the check is for a regular file rather than "not a link".
    """
    fifo = tmp_path / "pipe.yaml"
    os.mkfifo(fifo)
    assert stat.S_ISFIFO(fifo.lstat().st_mode)

    assert not _is_rendered_artifact(fifo)
