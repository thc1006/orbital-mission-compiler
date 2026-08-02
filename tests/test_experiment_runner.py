"""The runner's citability gate, which is the only reason it exists.

Running an experiment is the easy half. The half that matters is refusing to file
a transcript that cannot be cited, because such a transcript sits in a results
directory looking exactly like a usable one.

Every check here is written against the fact that the transcript is produced by
the party being audited: the runner must compare it to something it obtained
itself, not merely search it for a reassuring string.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The recipe from the importlib docs, "Importing a source file directly". The
# sys.modules registration before exec_module is not optional here: the runner
# uses @dataclass under `from __future__ import annotations`, and dataclasses
# resolves those string annotations by looking the module up in sys.modules.
_spec = importlib.util.spec_from_file_location("_runner", REPO / "scripts" / "run_experiments.py")
runner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = runner
_spec.loader.exec_module(runner)

HEAD = "0123456789abcdef0123456789abcdef01234567"
DIGEST = "a" * 64


@pytest.fixture
def exp() -> "runner.Experiment":
    return runner.Experiment(name="t", script=Path("scripts/run_experiments.py"))


def _transcript(**overrides) -> str:
    parts = {
        "commit": f"  compiler commit: {HEAD}",
        "tree": "  working tree   : clean",
        "checksum": f"  harness sha256 : {DIGEST}",
        "env": "  kube-apiserver : v1.36.3",
    }
    parts.update(overrides)
    return "\n".join(v for v in parts.values() if v is not None)


def _problems(exp, transcript, *, head=HEAD, digest=DIGEST, clean_after=True):
    return runner.citability_problems(transcript, exp, head, digest, clean_after)


def test_a_complete_transcript_is_citable(exp):
    assert _problems(exp, _transcript()) == []


@pytest.mark.parametrize(
    "field,replacement,expected",
    [
        ("commit", None, "no 'compiler commit' line"),
        ("commit", "  compiler commit: " + "b" * 40, "but the run was at"),
        ("commit", "  compiler commit: unknown", "but the run was at"),
        ("tree", None, "no 'working tree' line"),
        ("tree", "  working tree   : DIRTY -- cannot be rebuilt", "reports the working tree as"),
        ("tree", "  working tree   : dirty", "reports the working tree as"),
        ("tree", "  working tree   : unknown", "reports the working tree as"),
        ("checksum", None, "no 'harness sha256' line"),
        ("checksum", "  harness sha256 : " + "f" * 64, "edited while it ran"),
        ("env", None, "the apiserver version"),
        ("env", "  kube-apiserver : unknown", "the apiserver version"),
    ],
    ids=[
        "no-commit", "wrong-commit", "commit-unknown",
        "no-tree-state", "tree-DIRTY", "tree-lowercase-dirty", "tree-unknown",
        "no-checksum", "wrong-checksum",
        "no-environment", "environment-unknown",
    ],
)
def test_each_missing_guarantee_is_reported(exp, field, replacement, expected):
    """One transcript, one guarantee removed at a time.

    Removing them one at a time rather than all together is what shows each check
    is load-bearing on its own: a gate that only fires when everything is missing
    would pass the realistic case, which is a transcript that is complete except
    for the one thing that matters.

    `tree-lowercase-dirty` and `tree-unknown` are here because the first version
    tested `"DIRTY" in transcript`, which accepted every other way of saying the
    same thing and also failed an honest run whose cluster output happened to
    contain the word.
    """
    problems = _problems(exp, _transcript(**{field: replacement}))
    assert any(expected in p for p in problems), problems


def test_the_fields_are_read_as_fields_not_found_as_substrings(exp):
    """A transcript that mentions the values in prose is not a transcript that has them.

    The first version searched the whole transcript for the commit SHA and the
    digest, so a failure dump quoting either -- or a sentence saying the commit was
    reverted -- satisfied the check that exists to establish the opposite.
    """
    prose = (
        f"note: the commit {HEAD} was reverted before this run\n"
        "warning: the working tree may be stale\n"
        f"debug: expected harness sha256 {DIGEST} but verification was skipped\n"
        "TODO: kube-apiserver : v1.99 is untested\n"
    )
    problems = _problems(exp, prose)
    assert len(problems) >= 3, problems


def test_a_tree_dirtied_during_the_run_is_caught(exp):
    """The transcript's own line is printed at the start and cannot know.

    The worktree check used to run only before the experiment, and a long run --
    the priority proof takes twenty minutes -- is exactly when an edit lands.
    """
    problems = _problems(exp, _transcript(), clean_after=False)
    assert any("while the experiment was running" in p for p in problems), problems


def test_git_failing_is_not_an_answer(tmp_path, monkeypatch):
    """A repository git cannot read must not read as a clean one at commit "".

    This is the failure the whole gate turned on. `_git` returned stdout and
    ignored the exit status, so any git failure produced the empty string: the
    worktree looked clean, the resolved commit was "", and the substring search for
    "" matched every transcript. A transcript whose own text said
    `compiler commit: unknown` was filed as a result.
    """
    fake = tmp_path / "norepo"
    (fake / "scripts").mkdir(parents=True)
    script = fake / "scripts" / "x.sh"
    script.write_text(
        "#!/bin/sh\n"
        "echo '  compiler commit: unknown'\n"
        "echo '  working tree   : clean'\n"
        "echo '  kube-apiserver : v1.36.3'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "REPO", fake)
    outcome, detail = runner.run(
        runner.Experiment(name="x", script=Path("scripts/x.sh")), fake / "out"
    )
    assert outcome == "not-citable", (outcome, detail)
    assert "not a git repository" in detail or "failed" in detail


def test_stderr_reaches_the_transcript(tmp_path, monkeypatch):
    """The lines that matter most were the ones being discarded.

    The priority harness names the cluster-scoped objects it could not delete on
    stderr, and the live-cluster script rejects a bad argument there before it has
    printed anything at all. Capturing stdout only turned the second into four
    complaints about an empty transcript and lost the first entirely.
    """
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    script = repo / "scripts" / "x.sh"
    script.write_text("#!/bin/sh\necho 'to stderr, and it matters' >&2\nexit 9\n", encoding="utf-8")
    (repo / ".gitignore").write_text("out/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)

    monkeypatch.setattr(runner, "REPO", repo)
    outcome, detail = runner.run(
        runner.Experiment(name="x", script=Path("scripts/x.sh")), repo / "out"
    )
    kept = (repo / "out" / "x.rejected.txt").read_text(encoding="utf-8")
    assert "to stderr, and it matters" in kept
    # Both problems are reported: the exit status and why it cannot be cited.
    assert outcome == "not-citable" and "exit 9" in detail, (outcome, detail)


def test_a_rejected_run_does_not_leave_the_previous_result_in_place(tmp_path, monkeypatch):
    """Otherwise a regression keeps yesterday's passing transcript on disk."""
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "scripts" / "x.sh").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    # As in the repository: the results directory is ignored, because a runner that
    # dirties the tree makes its own next run uncitable. Without this the run is
    # refused before it starts and this test never reaches what it is about.
    (repo / ".gitignore").write_text("out/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "x"], check=True)

    results = repo / "out"
    results.mkdir()
    stale = results / "x.txt"
    stale.write_text("RESULT: PASS  (from a previous, better day)\n", encoding="utf-8")

    monkeypatch.setattr(runner, "REPO", repo)
    runner.run(runner.Experiment(name="x", script=Path("scripts/x.sh")), results)
    assert not stale.exists(), "a rejected run must not leave the last good result behind"
