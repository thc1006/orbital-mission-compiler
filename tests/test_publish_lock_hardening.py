"""What the publish lock promises, in the cases the promise was not kept.

The lock exists so two writers cannot publish into one output directory at
once. Four things stood between that claim and the code:

- when `/tmp` is unusable the default fell back to `tempfile.gettempdir()`,
  which reads TMPDIR -- the split namespace the fixed path was meant to close;
- a directory the operator names is trusted, but `O_NOFOLLOW` stops a symlink,
  not an unlink-and-recreate by another uid between two writers' opens;
- the lock is named after the output path, so one volume mounted at two mount
  points is two locks;
- and the exclusion was only ever measured between two threads of one process,
  while the claim is about separate processes.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from orbital_mission_compiler import cli
from orbital_mission_compiler.cli import (
    PublishLockUnavailable,
    _default_lock_dir,
    build_parser,
    publish_lock_path,
)

_IS_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0


def test_an_unusable_default_refuses_rather_than_reading_tmpdir(monkeypatch, tmp_path):
    """The fallback reintroduced exactly what the fixed path removed.

    In a container with a read-only /tmp, two writers with different TMPDIR
    values took two lock files of the same name in two directories and both
    entered publication. Refusing says which flag fixes it; falling back says
    nothing and proceeds.
    """
    monkeypatch.setattr(cli, "_FIXED_LOCK_DIR", tmp_path / "not-there")

    with pytest.raises(PublishLockUnavailable) as excinfo:
        _default_lock_dir()

    assert "--lock-dir" in str(excinfo.value)


@pytest.mark.skipif(_IS_ROOT, reason="root writes regardless of the mode bits")
def test_a_directory_other_users_can_write_needs_the_sticky_bit(tmp_path):
    """O_NOFOLLOW does not stop unlink-and-recreate.

    Another uid can remove the lock pathname between two writers' opens and
    create its own file there. Each then holds a different inode and both enter
    the critical section. On the default it is /tmp's sticky bit that prevents
    it, and a directory the operator names has to offer the same.
    """
    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o777)
    os.chmod(unsafe, 0o777)

    with pytest.raises(PublishLockUnavailable) as excinfo:
        with cli._publish_lock(tmp_path / "out", 1.0, str(unsafe)):
            pass

    assert "sticky" in str(excinfo.value)

    os.chmod(unsafe, 0o1777)
    with cli._publish_lock(tmp_path / "out", 1.0, str(unsafe)):
        pass


def test_a_private_directory_needs_no_sticky_bit(tmp_path):
    """The control. Most lock directories are not shared with other users."""
    private = tmp_path / "private"
    private.mkdir(mode=0o700)

    with cli._publish_lock(tmp_path / "out", 1.0, str(private)):
        pass


def test_a_lock_key_replaces_the_path_the_name_is_derived_from(tmp_path):
    """One volume reached at two mount points is otherwise two locks.

    The digest is taken from the output path, which is container-local. Whatever
    orchestrates the run knows the volume is the same thing and can say so.
    """
    shared = tmp_path / "locks"
    shared.mkdir()

    at_one_mount = publish_lock_path(tmp_path / "data" / "out", str(shared), "prod-root")
    at_another = publish_lock_path(tmp_path / "mnt" / "out", str(shared), "prod-root")
    without_a_key = publish_lock_path(tmp_path / "data" / "out", str(shared))

    assert at_one_mount == at_another
    assert without_a_key != at_one_mount


def test_the_lock_key_is_a_cli_flag(tmp_path):
    args = build_parser().parse_args([
        "render-argo", "--input", "x", "--output-dir", str(tmp_path),
        "--lock-key", "prod-root",
    ])
    assert args.lock_key == "prod-root"


@pytest.mark.parametrize("value", ["", "   "], ids=["empty", "blank"])
def test_a_lock_key_that_names_nothing_is_refused(value, tmp_path):
    """A key everyone shares is not an identity.

    An empty one would collapse every output directory under one lock dir onto
    the same file, which is not the guarantee anyone asked for.
    """
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "render-argo", "--input", "x", "--output-dir", str(tmp_path),
            "--lock-key", value,
        ])


def test_two_processes_with_different_tmpdirs_still_exclude(tmp_path):
    """The claim is about processes and namespaces, not threads.

    The existing exclusion test runs two threads in one interpreter with the
    default directory monkeypatched, which cannot see a TMPDIR difference at
    all. This spawns real processes with different TMPDIR values and a shared
    --lock-dir, and watches the second give up.
    """
    shared = tmp_path / "locks"
    shared.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    holder_src = tmp_path / "holder.py"
    holder_src.write_text(
        textwrap.dedent(
            f"""
            import sys, time
            sys.path.insert(0, {str(Path(cli.__file__).parents[2])!r})
            from orbital_mission_compiler import cli
            with cli._publish_lock({str(out)!r}, 5.0, {str(shared)!r}):
                print("held", flush=True)
                time.sleep(8)
            """
        ),
        encoding="utf-8",
    )
    first_tmp = tmp_path / "tmp-a"
    second_tmp = tmp_path / "tmp-b"
    for d in (first_tmp, second_tmp):
        d.mkdir()

    holder = subprocess.Popen(
        [sys.executable, str(holder_src)],
        stdout=subprocess.PIPE, text=True,
        env={**os.environ, "TMPDIR": str(first_tmp)},
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "held"
        contender = subprocess.run(
            [sys.executable, "-c", textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {str(Path(cli.__file__).parents[2])!r})
                from orbital_mission_compiler import cli
                try:
                    with cli._publish_lock({str(out)!r}, 1.0, {str(shared)!r}):
                        print("ENTERED")
                except cli.PublishLockUnavailable:
                    print("REFUSED")
                """
            )],
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "TMPDIR": str(second_tmp)},
        )
    finally:
        holder.kill()
        holder.wait(timeout=10)

    assert contender.stdout.strip() == "REFUSED", (contender.stdout, contender.stderr)
