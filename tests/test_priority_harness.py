"""The live priority harness's own guards, checked without a cluster.

scripts/validate_kueue_priority.sh creates a namespace, queues, a flavor and
cluster-scoped priority classes, so what it refuses to do matters as much as what
it proves. CI does not run it and it needs a live Kueue to get past its
prerequisites, but the checks that run before any of that do not.
"""

import subprocess
from pathlib import Path

import pytest

SCRIPT = Path("scripts/validate_kueue_priority.sh")


def _run(run_id: str) -> subprocess.CompletedProcess:
    """Run the harness with the given RUN_ID and no cluster access.

    KUBECONFIG points nowhere, so anything past the identifier check fails at the
    prerequisite step instead of touching a real cluster.
    """
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)],
        capture_output=True,
        text=True,
        # A refusal exits at once; this bound only matters when the guard is gone,
        # and then a short one turns a ten-minute hang into a prompt failure.
        timeout=20,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "RUN_ID": run_id,
            "KUBECONFIG": "/nonexistent/kubeconfig",
            "HOME": "/nonexistent",
        },
    )


@pytest.mark.parametrize(
    "run_id",
    [
        "UPPER",
        "-leading-hyphen",
        "trailing-hyphen-",
        "has,comma",
        "has=equals",
        "has/slash",
        "has space",
        "multi\nline",
        "a" * 33,
    ],
)
def test_an_unusable_run_id_stops_before_the_cluster_is_touched(run_id):
    """The identifier reaches object names, a label value, a label selector and the
    YAML templates, so one carrying a comma widens what cleanup deletes and one
    carrying a newline breaks the manifest.
    """
    result = _run(run_id)
    assert result.returncode == 2, result.stdout
    assert "RUN_ID is not usable" in result.stderr
    # Nothing past the check ran: no prerequisite report, no creation.
    assert "prerequisites" not in result.stdout


def test_a_usable_run_id_gets_past_the_check():
    """A well-formed identifier is not the thing that stops the run.

    What happens after the check needs a cluster and can take as long as its own
    waits allow, so the run is cut short rather than waited on: getting past the
    check is exactly the absence of its message.
    """
    proc = subprocess.Popen(  # noqa: S603
        ["bash", str(SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={
            "PATH": "/usr/bin:/bin:/usr/local/bin",
            "RUN_ID": "r1785592517",
            "KUBECONFIG": "/nonexistent/kubeconfig",
            "HOME": "/nonexistent",
        },
    )
    try:
        _, err = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        proc.kill()
        _, err = proc.communicate()

    assert "RUN_ID is not usable" not in err


def test_the_generated_default_would_pass_its_own_check():
    """The default is r<epoch><pid>, which has to satisfy the rule it is checked by."""
    import os
    import re
    import time

    generated = f"r{int(time.time())}{os.getpid()}"
    assert re.fullmatch(r"[a-z0-9]([-a-z0-9]*[a-z0-9])?", generated)
    assert len(generated) <= 32

def test_the_preflight_covers_every_class_the_compiler_emits():
    """The run creates one class per tier whether or not the proof reads them back.

    It checked only the two it reads, so the other two were applied over whatever
    already carried those names. A tier added to the mapping has to appear here too,
    which is what this compares.
    """
    import re

    from orbital_mission_compiler.compiler import render_workload_priority_classes

    prefix = "orbital-rtest-"
    emitted = sorted(w["metadata"]["name"] for w in render_workload_priority_classes(prefix=prefix))

    listed = re.search(r'ALL_CLASSES="(.+?)"', SCRIPT.read_text(encoding="utf-8"))
    assert listed, "the harness no longer names the classes it creates"
    checked = sorted(listed.group(1).replace("${CLASS_PREFIX}", prefix).split())

    assert checked == emitted
