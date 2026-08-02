#!/usr/bin/env python3
"""Run the live experiments, and refuse to file a result that cannot be cited.

An experiment's transcript is the thing a paper cites, so a transcript that does
not say what produced it is not evidence. This runner enforces that rather than
trusting each script to: it checks the worktree before the run, and checks the
transcript afterwards, and only writes the result file when both hold.

The four conditions, and why each one is disqualifying rather than cosmetic:

  clean worktree    A capture from a dirty tree cannot be rebuilt from any commit.
                    Checked before the run as well as read out of the transcript,
                    so a script that forgets to report it cannot pass by silence.

  names HEAD        A transcript that names no commit, or names one that is not
                    the commit it ran at, describes code nobody can retrieve.

  own checksum      The commit pins the script only if the script that ran is the
                    committed one. `bash <(...)` and an edit mid-run both break
                    that, and neither shows up in the commit.

  read environment  Versions typed into a header afterwards are a claim about the
                    cluster. Versions the run read from the cluster are evidence
                    from it. Only the second can be checked by re-running.

Usage:
    python3 scripts/run_experiments.py [--list] [--only NAME] [--results-dir DIR]

Exit status: 0 every experiment ran and produced a citable transcript; 1 an
experiment failed; 2 an experiment produced a transcript that cannot be cited,
which is a different problem and is reported separately.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Experiment:
    name: str
    script: Path
    env: dict[str, str] = field(default_factory=dict)
    # Wall-clock bound. An experiment that hangs must not hang the runner: these
    # hold cluster-scoped objects while they run.
    timeout_s: int = 2400


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
    ),
]


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True
    ).stdout.strip()


def _worktree_is_clean() -> bool:
    return not _git("status", "--porcelain")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def citability_problems(transcript: str, script: Path, head: str) -> list[str]:
    """What stops this transcript being usable as evidence. Empty means nothing does."""
    problems: list[str] = []

    if not re.search(rf"\b{re.escape(head)}\b", transcript):
        problems.append(f"does not name the commit it ran at ({head[:12]})")

    if "working tree" not in transcript:
        problems.append("does not say whether the working tree was clean")
    elif "DIRTY" in transcript:
        problems.append("ran from a dirty tree, so it cannot be rebuilt from a commit")

    digest = _sha256(REPO / script)
    if digest not in transcript:
        problems.append(
            "does not carry the checksum of the script that ran, so the commit "
            "does not pin what was executed"
        )

    # Read from the cluster, not written by hand afterwards. Any one of these is
    # enough to show the run asked rather than assumed.
    if not re.search(r"kube-apiserver\s*:\s*v\d", transcript):
        problems.append("does not record the apiserver version it read from the cluster")

    return problems


def run(exp: Experiment, results_dir: Path) -> tuple[str, str]:
    """Returns (outcome, detail). Outcome is one of ok / failed / not-citable / skipped."""
    if not (REPO / exp.script).exists():
        return "skipped", f"{exp.script} is not on this branch"

    if not _worktree_is_clean():
        # Checked before spending the cluster time, and separately from the
        # transcript's own claim: a script that forgot to report the state cannot
        # pass by staying quiet.
        return "not-citable", "the worktree is dirty; commit or stash before running"

    head = _git("rev-parse", "HEAD")
    env = {**os.environ, **exp.env}
    try:
        proc = subprocess.run(
            ["bash", str(REPO / exp.script)],
            cwd=REPO, env=env, capture_output=True, text=True, timeout=exp.timeout_s,
        )
    except subprocess.TimeoutExpired:
        return "failed", f"did not finish within {exp.timeout_s}s"

    transcript = proc.stdout
    problems = citability_problems(transcript, exp.script, head)

    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"{exp.name}.txt"
    if problems:
        # Written where it can be read, but not where results are kept: filing it
        # as a result is what would make it look citable.
        rejected = results_dir / f"{exp.name}.rejected.txt"
        rejected.write_text(transcript, encoding="utf-8")
        return "not-citable", "; ".join(problems) + f" (transcript kept at {rejected})"

    if proc.returncode != 0:
        out.write_text(transcript, encoding="utf-8")
        return "failed", f"exit {proc.returncode}; transcript at {out}"

    out.write_text(transcript, encoding="utf-8")
    return "ok", str(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="Show the registered experiments and exit")
    ap.add_argument("--only", help="Run one experiment by name")
    ap.add_argument("--results-dir", default="out/experiments", help="Where transcripts are written")
    args = ap.parse_args()

    if args.list:
        for exp in EXPERIMENTS:
            present = "present" if (REPO / exp.script).exists() else "absent on this branch"
            print(f"{exp.name:16} {exp.script}  ({present})")
        return 0

    chosen = [e for e in EXPERIMENTS if not args.only or e.name == args.only]
    if args.only and not chosen:
        print(f"no experiment named {args.only!r}", file=sys.stderr)
        return 1

    results_dir = REPO / args.results_dir
    worst = 0
    for exp in chosen:
        print(f"=== {exp.name} ===", flush=True)
        outcome, detail = run(exp, results_dir)
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
