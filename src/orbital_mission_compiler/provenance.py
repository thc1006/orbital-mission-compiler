"""What a measurement can be attributed to, printed by the measurement itself.

Every experiment harness in this repository has to answer the same questions before
its output can be cited: which commit, whether the tree it came from was clean,
which copy of the harness ran, which interpreter, and which copy of the compiler
that interpreter actually imported. `scripts/run_experiments.py` refuses to file a
transcript that does not answer them.

They were answered three times, in three files, in three slightly different ways --
which is how the shared subtlety got fixed once and stayed broken twice. `_git`
originally returned `proc.stdout` and discarded the exit status, so every git
failure produced the empty string: the commit printed as "unknown", which is loud,
and the tree printed as "clean", which is silent and indistinguishable from a real
clean tree. A transcript carries that unverifiable "clean" wherever it is pasted.

One implementation, imported by all of them.
"""

from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
from pathlib import Path

__all__ = ["git_state", "file_digest", "inputs_digest", "emit"]


def git_state(repo: Path) -> tuple[str, str]:
    """The commit and the worktree state, as three distinguishable outcomes.

    Returns:
        `(commit, tree)`. `commit` is the full object name or "unknown"; `tree` is
        "clean", a DIRTY notice, or an explicit "git could not answer".

    "git could not answer" is kept separate from "clean" on purpose. No .git
    directory, a stale worktree pointer, a checkout git considers unsafely owned,
    an artifact tarball with .git stripped -- all of these once read as a clean
    tree at commit "", and the substring check downstream then matched every
    transcript.
    """

    def _git(*args: str) -> str | None:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), *args], capture_output=True, text=True
            )
        except OSError:
            return None
        return proc.stdout.strip() if proc.returncode == 0 else None

    head = _git("rev-parse", "HEAD") or "unknown"
    status = _git("status", "--porcelain")
    if status is None:
        tree = "unknown -- git could not answer, so this capture cannot be rebuilt"
    elif status:
        tree = "DIRTY -- this measurement cannot be rebuilt from a commit"
    else:
        tree = "clean"
    return head, tree


def file_digest(path: Path) -> str:
    """The plain sha256 of one file, or "unreadable".

    Deliberately plain: this is what `sha256sum <harness>` prints, so an operator
    can check the `harness sha256:` line in a transcript without knowing anything
    about this module.
    """
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return "unreadable"


def inputs_digest(*paths: Path) -> str:
    """A digest over the templates, policies or plans a harness applies.

    Reported SEPARATELY from the harness digest rather than folded into it. A
    combined figure would be the more obvious design, and it is the wrong one
    twice over: it would silently invalidate every transcript already on disk, and
    it would stop matching `sha256sum <harness>`, which is the only check anyone
    can run without this file in front of them.

    What it fixes is real, though. A harness that digests only itself leaves the
    manifests it applies -- half of what the run does -- outside its own
    provenance, so an edited template is a different experiment under an unchanged
    digest.

    The per-file hashes are combined with the BASENAME rather than the path, so
    the digest identifies the inputs and not where the checkout happens to live: a
    figure that changes when the repository is cloned to another directory cannot
    be compared across the two runs it exists to compare.
    """
    parts = sorted(f"{file_digest(Path(p))}  {Path(p).name}" for p in paths)
    return hashlib.sha256(("\n".join(parts) + "\n").encode("utf-8")).hexdigest()


def _cpu_model() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except (OSError, ValueError):
        # ValueError covers UnicodeDecodeError, which is not an OSError and would
        # otherwise end a run over a cosmetic line.
        pass
    return "unknown"


def emit(
    entry_point: Path,
    *,
    repo: Path | None = None,
    inputs: tuple[Path, ...] = (),
    environment: tuple[tuple[str, str], ...] = (),
    include_host: bool = True,
) -> None:
    """Print the provenance and environment blocks to stdout.

    Args:
        entry_point: The script being run; its parent's parent is the repository
            unless `repo` says otherwise.
        repo: The repository to read the commit and worktree state from.
        inputs: Additional files the run applies, folded into the digest.
        environment: Extra `(label, value)` lines for the environment block --
            what the result is a property of, such as an apiserver version.
        include_host: Whether to print the CPU, core count and platform. A timing
            measurement is a property of the host; a cluster result is not.
    """
    here = repo if repo is not None else Path(entry_point).resolve().parent.parent
    head, tree = git_state(here)

    # Which copy of the compiler these numbers are about. The commit above names
    # the tree the script lives in; this names the tree that ran. Nothing here sets
    # PYTHONPATH, so the module resolves to whatever is installed -- which on the
    # development host is a different checkout at a different commit.
    try:
        import orbital_mission_compiler.compiler as _compiler

        module_path = _compiler.__file__
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        module_path = f"unresolved ({exc})"

    print("=== provenance ===")
    print(f"  compiler commit: {head}")
    print(f"  working tree   : {tree}")
    print(f"  harness sha256 : {file_digest(Path(entry_point))}")
    if inputs:
        print(f"  inputs sha256  : {inputs_digest(*inputs)}")
        print(f"  harness inputs : {' '.join(Path(p).name for p in inputs)}")
    print(f"  interpreter    : {sys.executable}")
    print(f"  compiler module: {module_path}")
    print(f"  python         : {platform.python_version()}")
    print("=== environment ===")
    if include_host:
        print(f"  cpu            : {_cpu_model()}")
        print(f"  cpu count      : {os.cpu_count()}")
        print(f"  platform       : {platform.platform()}")
    for label, value in environment:
        print(f"  {label:<15}: {value}")
    print()
