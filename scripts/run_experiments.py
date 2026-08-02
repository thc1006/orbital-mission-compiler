#!/usr/bin/env python3
"""Run the live experiments, and refuse to file a result that cannot be cited.

An experiment's transcript is the thing a paper cites, so a transcript that does
not say what produced it is not evidence. This runner enforces that rather than
trusting each script to.

Everything here is written against one assumption: **the transcript is written by
the party being audited.** A script can print any string it likes, so a check that
only asks "does this string appear" verifies nothing. Each check below therefore
compares the transcript against something the runner obtained itself, and parses
the transcript's provenance block structurally rather than searching it.

  names HEAD        The `compiler commit:` line must be exactly the commit the
                    runner resolved before starting. Searching the whole
                    transcript for the SHA would accept it appearing in a failure
                    dump, or in a sentence saying it was reverted.

  clean worktree    Read from git by the runner, before AND after the run, and
                    required to agree with what the transcript claims. Before,
                    because a capture from a dirty tree cannot be rebuilt from any
                    commit. After, because the run itself takes time, and the
                    interesting tamper is the one that happens during it.

  own checksum      The script is hashed before the run and again after, both are
                    required to match, and the transcript's `harness sha256:` line
                    must equal them. bash reads a script incrementally, so an edit
                    mid-run executes a hybrid of two versions.

  read environment  A fact the run obtained from what it ran against, matched per
                    experiment: a cluster experiment must record the apiserver
                    version, a timing measurement the CPU. Weakest of the four --
                    it cannot distinguish a version read from one printed -- so it
                    is a floor, not a guarantee.

What this does NOT establish: that the script told the truth about anything else,
that the commit is reachable from a branch, or that no untracked-but-loaded file
(a sitecustomize.py, an ignored config) changed the result. A determined author of
an experiment script can still produce a false transcript. The checks close the
accidents, which is what actually happens.

Usage:
    python3 scripts/run_experiments.py [--list] [--only NAME] [--results-dir DIR]

Exit status: 0 every experiment ran and produced a citable transcript; 1 an
experiment failed; 2 an experiment produced a transcript that cannot be cited,
which is a different problem and is reported separately.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import re
import signal
import subprocess
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class GitUnavailable(RuntimeError):
    """git could not answer. Not the same as git answering 'nothing to report'."""


@dataclass(frozen=True)
class Experiment:
    name: str
    script: Path
    # Files the harness applies that are not the harness: manifest templates, a
    # policy pack, a plan corpus. Digested separately and checked separately,
    # because a harness that accounts only for itself leaves half of what it does
    # outside its own provenance -- an edited template is a different experiment
    # under an unchanged script digest. Globs are expanded against REPO at
    # registration; a pattern matching nothing is a registration error rather than
    # a silently empty check.
    inputs: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    args: tuple[str, ...] = ()
    # Wall-clock bound. An experiment that hangs must not hang the runner: these
    # hold cluster-scoped objects while they run.
    timeout_s: int = 2400
    # Where a citable transcript belongs in the repository, if it belongs anywhere.
    # Filed only after the transcript passes, so this path can never hold one that
    # did not -- which is the whole point of the runner.
    result_path: Path | None = None
    # What "recorded the environment it ran against" means here. Not every
    # experiment has a cluster: a timing measurement's environment is the CPU, and
    # demanding an apiserver version of it would either fail a sound measurement or
    # teach the harness to print a line it does not mean.
    environment_marker: str = r"^[^\S\n]*kube-apiserver[^\S\n]*:[^\S\n]*v\d"
    environment_description: str = "the apiserver version it read from the cluster"


EXPERIMENTS = [
    Experiment(
        name="live-cluster",
        script=Path("scripts/validate_live_cluster.sh"),
    ),
    Experiment(
        # Present only on the branch that adds it; skipped elsewhere rather than
        # failing, so this runner is usable from any branch in the stack.
        name="kueue-priority",
        script=Path("scripts/validate_kueue_priority.sh"),
        result_path=Path(
            "manifests/k8s/kueue/priority-ordering/results/"
            "run-k8s-1.36.3-kueue-0.19.0.txt"
        ),
    ),
    Experiment(
        # No cluster. Its environment is the CPU, because that is what the numbers
        # are a property of: the paper's Table V backing data names a host but not
        # the commit it measured, so a reader re-running it cannot tell a
        # regression from a different codebase.
        name="scaling",
        script=Path("scripts/benchmark_scaling.py"),
        args=("--sizes", "10,50,100,500,1000", "--iterations", "30"),
        environment_marker=r"^[^\S\n]*cpu[^\S\n]*:[^\S\n]*(?!unknown[^\S\n]*$)\S",
        environment_description="the CPU it measured on",
        result_path=Path("docs/experiments/results/scaling.txt"),
    ),
    Experiment(
        # Also on another branch. Its templates are declared: they carry the queue
        # sizing and the two claim shapes, which is where this experiment's meaning
        # lives -- the script only submits them.
        name="dra-unified",
        script=Path("scripts/validate_dra_unified.sh"),
        inputs=("manifests/k8s/kueue/dra-unified/harness-*.yaml",),
        result_path=Path(
            "manifests/k8s/kueue/dra-unified/results/run-k8s-1.36.3-kueue-0.19.0.txt"
        ),
    ),
    Experiment(
        # No cluster, and no host either: this arm counts which plans each layer
        # rejects, not how fast. Its environment is the OPA build, because that is
        # the engine under test and it is resolved from PATH rather than pinned by
        # the commit -- and its inputs are the Rego pack, which is what the policy
        # arm evaluates.
        name="ablation",
        script=Path("scripts/ablation_study.py"),
        inputs=("configs/policies/*.rego",),
        environment_marker=r"^[^\S\n]*opa[^\S\n]*:[^\S\n]*(?!unknown|not on PATH)\S",
        environment_description="the OPA build it evaluated against",
        result_path=Path("docs/experiments/results/ablation.txt"),
    ),
    Experiment(
        # The paper's Section IV evidence. Its inputs are the two plans and the
        # policy pack, because the whole transcript is a policy decision about
        # them: run it against an edited plan and it is a different demonstration.
        name="mcp-agent-demo",
        script=Path("scripts/mcp_agent_demo.py"),
        inputs=(
            "configs/mission_plans/demo_gpu_no_fallback.yaml",
            "configs/mission_plans/demo_gpu_fallback_fixed.yaml",
            "configs/policies/*.rego",
        ),
        environment_marker=r"^[^\S\n]*opa[^\S\n]*:[^\S\n]*(?!unknown|not on PATH)\S",
        environment_description="the OPA build it evaluated against",
        result_path=Path("docs/experiments/results/mcp-agent-demo.txt"),
    ),
]


def _git(*args: str) -> str:
    """Ask git, and refuse to turn a failure into an answer.

    The first version of this returned `.stdout.strip()` and never looked at the
    exit status. git writes to stderr and leaves stdout empty when it fails, so
    every failure -- a repository without .git, a stale worktree pointer, a
    checkout git considers unsafely owned -- came back as the empty string. That
    made `_worktree_is_clean()` return True, and made the resolved commit "", which
    the old substring check then found in every transcript. The gate reported `ok`
    on a transcript whose own text said `compiler commit: unknown`.
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(REPO), *args], capture_output=True, text=True
        )
    except OSError as exc:
        # No git at all. Letting FileNotFoundError escape exited 1, which this
        # module reserves for "an experiment failed"; an unanswerable git is the
        # other outcome.
        raise GitUnavailable(f"git could not be run: {exc}") from exc
    if proc.returncode != 0:
        raise GitUnavailable(
            f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr.strip()}"
        )
    return proc.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _field(transcript: str, label: str) -> str | None:
    r"""The value of one provenance line, or None if it is not there exactly once.

    `[^\S\n]` rather than `\s`, because `\s` matches newlines: the previous
    pattern spanned lines, so a transcript with every label on one line and every
    value on the next satisfied all of them, and an empty value swallowed the
    whole line that followed.

    More than one occurrence is None, not the first. A harness that echoes an
    earlier filed transcript before printing its own provenance -- a
    regression-comparison run, say -- would otherwise be judged on the copy, and
    the runner's own filed results are complete provenance blocks, so the material
    to do it with is lying in the results directory.
    """
    pattern = rf"^[^\S\n]*{re.escape(label)}[^\S\n]*:[^\S\n]*(.*?)[^\S\n]*$"
    found = re.findall(pattern, transcript, re.M)
    return found[0] if len(found) == 1 else None


def resolve_inputs(exp: Experiment) -> list[Path]:
    """The files behind an experiment's declared input patterns, sorted.

    Sorted because glob order is filesystem order and the digest has to agree
    across two machines holding the same files. Missing patterns are returned as
    an empty list and reported by the caller: a pattern that matches nothing would
    otherwise produce the digest of no files, which is a fixed value that every
    such experiment would agree on.
    """
    found: list[Path] = []
    for pattern in exp.inputs:
        found.extend(sorted(REPO.glob(pattern)))
    return sorted(set(found))


def inputs_digest(paths: Iterable[Path]) -> str:
    """A digest over the harness's inputs, by basename rather than by path.

    Kept in step with `orbital_mission_compiler.provenance.inputs_digest`, which is
    what the harnesses print. It is duplicated rather than imported on purpose:
    this runner is the auditor, and an auditor that imports its verification from
    the tree it audits verifies that the tree agrees with itself.
    """
    parts = sorted(f"{_sha256(p)}  {p.name}" for p in paths)
    return hashlib.sha256(("\n".join(parts) + "\n").encode("utf-8")).hexdigest()


def citability_problems(
    transcript: str,
    exp: Experiment,
    head: str,
    digest: str,
    clean_after: bool,
    inputs_sha: str | None = None,
) -> list[str]:
    """What stops this transcript being usable as evidence. Empty means nothing does."""
    problems: list[str] = []

    claimed_commit = _field(transcript, "compiler commit")
    if claimed_commit is None:
        problems.append("has no 'compiler commit' line")
    elif claimed_commit != head:
        problems.append(
            f"names commit {claimed_commit[:12] or '(empty)'}, but the run was at {head[:12]}"
        )

    claimed_tree = _field(transcript, "working tree")
    if claimed_tree is None:
        problems.append("has no 'working tree' line")
    elif claimed_tree != "clean":
        problems.append(f"reports the working tree as {claimed_tree!r}")

    if not clean_after:
        # The tree was clean when the run started; something changed it while the
        # run was in flight, which the transcript's own line -- printed at the
        # start -- cannot know about.
        problems.append("the worktree was modified while the experiment was running")

    claimed_digest = _field(transcript, "harness sha256")
    if claimed_digest is None:
        problems.append("has no 'harness sha256' line")
    elif claimed_digest != digest:
        problems.append(
            "the harness on disk does not match the one the transcript names, so "
            "the script was edited while it ran"
        )

    if exp.inputs:
        claimed_inputs = _field(transcript, "inputs sha256")
        if inputs_sha is None:
            # The patterns matched nothing on disk, so there is nothing to compare
            # against. Reported rather than passed over: an experiment that
            # declares templates and finds none is not one whose templates are
            # unchanged.
            problems.append(
                "declares harness inputs, but none of the patterns matched a file "
                f"({', '.join(exp.inputs)})"
            )
        elif claimed_inputs is None:
            problems.append(
                "has no 'inputs sha256' line, so the templates it applied are "
                "outside its provenance"
            )
        elif claimed_inputs != inputs_sha:
            problems.append(
                "the harness inputs on disk do not match the ones the transcript "
                "names, so a template was edited while it ran"
            )

    if not re.search(exp.environment_marker, transcript, re.M):
        problems.append(f"does not record {exp.environment_description}")

    module = _field(transcript, "compiler module")
    if module is None:
        problems.append("has no 'compiler module' line, so it does not say which copy ran")
    elif not module.startswith(str(REPO) + os.sep):
        problems.append(
            f"ran a compiler from {module}, which is not in this repository -- the "
            "commit it names describes a different tree"
        )

    return problems


def _dirt(ignoring: set[str]) -> list[str]:
    """Working-tree entries, minus the ones this runner filed itself.

    A filed result is a change to the tree, and the dirty check is the first thing
    every experiment does -- so filing one made the NEXT experiment uncitable, in
    the same invocation, including experiments that file nothing at all. The
    documented `python3 scripts/run_experiments.py` filed the first result and then
    rejected the rest with the runner's loudest outcome, self-inflicted.

    Only paths this process has just written are forgiven, and only those: a file
    that was already dirty when the run began still stops it.
    """
    entries = []
    for line in _git("status", "--porcelain").splitlines():
        # `XY PATH`: two status columns and a space. Renames are `XY OLD -> NEW`;
        # the whole entry is kept for reporting and the path is only used to match.
        path = line[3:].strip().strip('"')
        if not any(path == ig or path.startswith(ig.rstrip("/") + "/") for ig in ignoring):
            entries.append(path)
    return entries


def run(exp: Experiment, results_dir: Path, filed: set[str] | None = None) -> tuple[str, str]:
    """Returns (outcome, detail). Outcome is one of ok / failed / not-citable / skipped."""
    filed = filed if filed is not None else set()
    script = REPO / exp.script
    if not script.exists():
        return "skipped", f"{exp.script} is not on this branch"

    try:
        dirty = _dirt(filed)
        if dirty:
            return "not-citable", (
                "the worktree is dirty; commit or stash before running "
                f"({len(dirty)} entr{'y' if len(dirty) == 1 else 'ies'}, e.g. {dirty[0]})"
            )
        head = _git("rev-parse", "HEAD")
    except GitUnavailable as exc:
        # Not "clean" and not "unknown commit": simply not answerable, so nothing
        # produced here could be cited even if the experiment succeeded.
        return "not-citable", str(exc)
    if not re.fullmatch(r"[0-9a-f]{40}", head):
        return "not-citable", f"git returned an unusable commit: {head!r}"

    digest_before = _sha256(script)
    inputs_before = resolve_inputs(exp)
    inputs_sha_before = inputs_digest(inputs_before) if inputs_before else None
    # PYTHONPATH points at THIS repository, ahead of anything installed. Without
    # it the scaling benchmark imported orbital_mission_compiler from whichever
    # checkout happened to be on sys.path -- a different tree, at a different
    # commit, with uncommitted changes -- while its transcript said "clean" and
    # every citability check passed. The numbers were about another repository.
    env = {**os.environ, "PYTHONPATH": f"{REPO / 'src'}:{REPO}", **exp.env}
    argv = (
        ["bash", str(script), *exp.args]
        if script.suffix == ".sh"
        else [sys.executable, str(script), *exp.args]
    )
    # stderr is folded into the transcript. Keeping it separate discarded exactly
    # the lines that matter: the priority harness names the cluster-scoped objects
    # it failed to delete on stderr, and validate_live_cluster.sh rejects a bad
    # argument there before printing anything at all -- which used to surface as
    # four provenance complaints about an empty transcript.
    #
    # A new session, so a timeout can kill the whole process group. subprocess
    # kills only the direct child, which for a shell harness leaves its kubectl
    # waits alive and its EXIT trap unrun -- the teardown that removes
    # cluster-scoped objects.
    # Popen rather than run(), because run()'s timeout path calls process.kill(),
    # which signals one pid. A shell harness leaves its kubectl waits and its EXIT
    # trap -- the teardown that removes cluster-scoped objects -- to a grandchild
    # that survives and reparents. start_new_session gives the child its own
    # process group so killpg can reach all of it, and without the killpg below
    # that flag only made things worse: it also detaches the tree from the
    # terminal, so an operator's Ctrl-C no longer reaches it either.
    proc = subprocess.Popen(
        argv, cwd=REPO, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
    )
    try:
        transcript = proc.communicate(timeout=exp.timeout_s)[0] or ""
        returncode = proc.returncode
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        try:
            transcript = proc.communicate(timeout=10)[0] or ""
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            transcript = proc.communicate()[0] or ""
        returncode = -1
        results_dir.mkdir(parents=True, exist_ok=True)
        kept = results_dir / f"{exp.name}.timed-out.txt"
        kept.write_text(transcript, encoding="utf-8")
        return "failed", (
            f"did not finish within {exp.timeout_s}s; partial transcript at {kept}. "
            "Its teardown may not have run -- check for leftover objects."
        )

    try:
        clean_after = not _dirt(filed)
    except GitUnavailable as exc:
        return "not-citable", f"could not re-check the worktree after the run: {exc}"
    digest_after = _sha256(script)
    inputs_after = resolve_inputs(exp)
    inputs_sha_after = inputs_digest(inputs_after) if inputs_after else None

    problems = citability_problems(
        transcript, exp, head, digest_before, clean_after, inputs_sha_before
    )
    if digest_before != digest_after:
        problems.append("the harness changed on disk while it was running")
    # The same check the harness digest gets, for the same reason: a template
    # edited mid-run means the documents applied early and the documents applied
    # late came from two different experiments. The set is compared too, so a
    # template ADDED or removed during the run is caught -- the digest alone would
    # miss neither, but the message should say which happened.
    if inputs_sha_before != inputs_sha_after:
        problems.append(
            "the harness inputs changed on disk while it was running "
            f"({len(inputs_before)} file(s) before, {len(inputs_after)} after)"
        )

    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{exp.name}.txt"
    if problems:
        rejected = results_dir / f"{exp.name}.rejected.txt"
        rejected.write_text(transcript, encoding="utf-8")
        # The previous run's result is removed. Leaving it is how a regression
        # keeps a passing transcript on disk while only the console says otherwise.
        out.unlink(missing_ok=True)
        detail = "; ".join(problems) + f" (transcript kept at {rejected})"
        if returncode != 0:
            detail = f"exit {returncode}, and " + detail
        return "not-citable", detail

    out.write_text(transcript, encoding="utf-8")
    if returncode != 0:
        return "failed", f"exit {returncode}; transcript at {out}"

    if exp.result_path is not None:
        # The transcript verbatim, with nothing written around it. A preamble
        # summarising the environment is exactly the hand-authored claim the
        # checks above exist to replace, and it goes stale the moment the run
        # changes underneath it.
        target = REPO / exp.result_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(transcript, encoding="utf-8")
        filed.add(str(exp.result_path))
        return "ok", f"{out} -> filed at {exp.result_path} (commit it to keep the tree clean)"
    return "ok", str(out)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--list", action="store_true", help="Show the registered experiments and exit")
    # Repeatable. Filing a result dirties the tree, and only the paths filed by
    # THIS invocation are forgiven -- which is the right rule, and it made three
    # separate `--only` runs reject each other's output: the first filed a
    # transcript and the next two refused to start because of it. Several names in
    # one invocation is what `_dirt`'s forgiveness was built for.
    ap.add_argument(
        "--only",
        action="append",
        metavar="NAME",
        help="Run one experiment by name; repeat to run several in one invocation",
    )
    ap.add_argument(
        "--results-dir",
        default="out/experiments",
        help="Where transcripts are written. Keep it inside a gitignored directory: "
        "a runner that dirties the tree makes its own next run uncitable.",
    )
    args = ap.parse_args()

    if args.list:
        for exp in EXPERIMENTS:
            present = "present" if (REPO / exp.script).exists() else "absent on this branch"
            print(f"{exp.name:16} {exp.script}  ({present})")
        return 0

    wanted = set(args.only or ())
    chosen = [e for e in EXPERIMENTS if not wanted or e.name in wanted]
    # Every name is checked, not just whether anything matched. A typo alongside
    # three good names would otherwise run the three and say nothing about the
    # fourth, and the missing transcript reads as an experiment that failed.
    unknown = sorted(wanted - {e.name for e in EXPERIMENTS})
    if unknown:
        print(
            f"no experiment named {', '.join(repr(u) for u in unknown)} "
            f"(known: {', '.join(e.name for e in EXPERIMENTS)})",
            file=sys.stderr,
        )
        return 1

    results_dir = REPO / args.results_dir
    # What this invocation has filed, so a later experiment is not rejected for a
    # change this runner made a moment earlier.
    filed: set[str] = set()
    try:
        filed.add(str((results_dir).relative_to(REPO)))
    except ValueError:
        pass  # a results directory outside the repository cannot dirty it
    worst = 0
    for exp in chosen:
        print(f"=== {exp.name} ===", flush=True)
        outcome, detail = run(exp, results_dir, filed)
        print(f"  {outcome}: {detail}", flush=True)
        if outcome == "failed":
            worst = max(worst, 1)
        elif outcome == "not-citable":
            # Deliberately louder than a failure. A failed experiment is a result;
            # an uncitable transcript is a result that looks like one and is not.
            worst = max(worst, 2)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
