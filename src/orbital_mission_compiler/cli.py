from __future__ import annotations

import argparse
import contextlib
import errno
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from collections.abc import Collection, Iterator
from pathlib import Path

import yaml

from .compiler import (
    ArgoLintUnavailable,
    ARGO_LINT_TIMEOUT_SECONDS,
    DEFAULT_POLICY_BUNDLE,
    DEFAULT_POLICY_DECISION,
    PolicyEngineUnavailableError,
    PolicyViolationError,
    compile_file,
    enforce_policy_or_raise,
    load_mission_plan,
    mission_fingerprint,
    compile_plan_to_intents,
    render_kueue_job,
    render_resource_claim_templates,
    DRA_ROUTE_LABEL,
    kueue_step_projection,
    atomic_write,
    preflight_unique,
    preflight_writable,
    resolve_argo_bin,
    argo_lint_path,
    stale_rendered_artifacts,
    ArtifactOwner,
    _artifact_mission,
    attribute_stale,
    render_workload_priority_classes,
    typed_violations_from_decision,
    write_individual_workflows,
    sanitize_k8s_name,
    ORCHIDE_PRIORITY_CLASS_PREFIX,
)
from .policy import eval_policy

_UNSAFE_SKIP_POLICY_HELP = (
    "DEV ONLY. Skip the policy admission gate and emit artifacts even for a plan the "
    "policy layer would deny. By DEFAULT the compiler is fail-closed: it runs the policy "
    "layer before rendering and produces no artifact for a denied plan. Bypassing the "
    "gate forfeits the pre-uplink guarantee."
)
_POLICY_ENGINE_HELP = (
    "Which policy engine enforces the gate. 'opa' (default) executes the versioned, "
    "independently-auditable Rego bundle -- the authoritative policy-as-code path an "
    "external reviewer runs; it fails closed if opa is unavailable. 'baseline' uses the "
    "proven-equivalent in-process mirror (no opa subprocess), for offline use."
)


# Long enough that a normal concurrent render finishes first, short enough that a
# hung one is reported rather than waited on. Overridable because "normal" depends
# on how much a caller renders at once.
# Long enough to outlast the thing the lock is held across. The gate takes the
# lock before it reads the destination and keeps it through `argo lint`, so a
# wait shorter than the linter's own budget makes a second healthy writer give up
# while the first is still inside its allowance -- contention reported as a
# failure, on the defaults, most of the time. Derived rather than written down
# twice, so raising the lint timeout cannot leave this behind; the margin covers
# the publish that follows the verdict.
_LOCK_PUBLISH_MARGIN_SECONDS = 30.0
_DEFAULT_LOCK_TIMEOUT = float(ARGO_LINT_TIMEOUT_SECONDS) + _LOCK_PUBLISH_MARGIN_SECONDS
# flock failures that mean "no lock is obtainable here", as opposed to "someone
# holds it" or "something went wrong". Everything outside both lists is an error,
# because proceeding unlocked on an unclassified failure is the one outcome that
# silently removes the guarantee.
_LOCK_UNSUPPORTED_ERRNOS = frozenset({
    errno.ENOLCK, errno.EOPNOTSUPP, errno.EINVAL, errno.ENOSYS,
})
# Beyond a day the wait is unbounded in every sense that matters; 1e308 seconds
# passed the finiteness check and is 3e300 years.
_MAX_LOCK_TIMEOUT = 86400.0

_PRUNE_HELP = (
    "Delete artifacts in the output directory that an earlier render of this tool "
    "wrote and this one did not replace. Without it they are reported under "
    "'stale' and left in place: a render writes what the plan describes, it does "
    "not empty the directory, so after a plan shrinks, deploying the directory "
    "would redeploy the workloads the plan no longer asks for. Only files carrying "
    "this tool's own labels are considered."
)

# The Kueue Job carries generateName and no name, which is what lets one rendered
# file be submitted repeatedly as distinct Jobs. kubectl apply needs a name, so
# `apply -f` over this output cannot create the Job.
#
# It does not stop there either. kubectl's apply builder runs with
# ContinueOnError, so it applies every OTHER document -- the ones before the Job
# and the ones after it, including the four cluster-scoped priority classes -- and
# reports the failure at the end with exit 1. Verified with --dry-run=server: two
# named ConfigMaps applied, the generateName one refused, exit 1. So the outcome
# is not "a partial deployment up to the failure": it is the whole set except the
# Job, which is the one document that carries the workload.
#
# `kubectl create -f` takes all of it. Repeat deployments are the awkward case,
# because create is not idempotent for the named documents: apply those and create
# the Job, which is what scripts/validate_live_cluster.sh does.
_KUEUE_DEPLOY_NOTE = (
    "Deploy this output with 'kubectl create -f <dir>': the Job uses generateName, "
    "so 'kubectl apply' cannot create it -- and applies everything else anyway, "
    "leaving the priority classes and claim templates on the cluster without the "
    "workload. To redeploy, apply the named documents (listed under 'apply') and "
    "create the Job (listed under 'create'), since create is not idempotent."
)


# The kind only one renderer emits. Both write ResourceClaimTemplate, so it is not
# a discriminator: attribution has to rest on a kind that is exclusively one
# side's, or the RCT-only scheduler-fallback file is claimed by whichever command
# ran last.
ARGO_EXCLUSIVE_KINDS = {"Workflow"}
KUEUE_EXCLUSIVE_KINDS = {"Job", "WorkloadPriorityClass"}


def _render_scope(source: str | Path) -> frozenset[str]:
    """The missions this render reconciles, taken from the plan.

    Read from the input rather than from what was written, so a revision that
    legitimately renders nothing still has a scope to reconcile against. The
    fingerprint is what the artifacts carry, so that is what the scope holds.
    """
    return frozenset({mission_fingerprint(load_mission_plan(source).mission_id)})


def _report_stale(
    result: dict[str, object], output_dir: str, written: list[Path], prune: bool,
    exclusive_kinds: set[str], *, mission_ids: Collection[str] | None = None,
    include_unmissioned: bool = False,
) -> None:
    stale = stale_rendered_artifacts(
        output_dir, written,
        mission_ids=mission_ids, include_unmissioned=include_unmissioned,
    )
    if not stale:
        return
    mine, unattributable = attribute_stale(stale, exclusive_kinds)
    if unattributable:
        # Reported and never deleted. These hold no kind either renderer owns --
        # the standalone scheduler-fallback template is the real case -- so this
        # command cannot show they are its to remove.
        result["stale_not_ours"] = [str(p) for p in unattributable]
        print(
            f"warning: {len(unattributable)} artifact(s) in {output_dir} are left over "
            f"but carry no object kind this command emits, so they were not removed "
            f"even with --prune. Remove them by hand if they are yours.",
            file=sys.stderr,
        )
    if not mine:
        return
    if prune:
        # A cluster-scoped artifact belongs to no mission, so the mission filter
        # that keeps one mission's --prune away from another's files does not
        # cover it. Two missions rendering into one directory therefore share the
        # priority-class bundle, and the second render removing it is correct for
        # its own desired set while leaving the first mission's Jobs pointing at
        # classes that are no longer there. Correct and silent is the wrong half
        # of that, so it is said out loud.
        shared = [
            p for p in mine
            if _artifact_mission(p).owner is ArtifactOwner.UNMISSIONED
        ]
        if shared:
            print(
                f"warning: removing {len(shared)} cluster-scoped artifact(s) that carry no "
                f"mission: {', '.join(p.name for p in shared)}. Any other mission rendering "
                f"into {output_dir} was relying on them; re-run that render with "
                f"--emit-priority-classes to put them back.",
                file=sys.stderr,
            )
        removed: list[str] = []
        for index, path in enumerate(mine):
            try:
                path.unlink()
            except OSError as exc:
                # Publication has already committed and its backup is gone, so
                # there is nothing to roll back to. Say what was removed and
                # what was not, rather than letting the caller read this as a
                # failed publish.
                raise PruneIncomplete(
                    str(exc), removed, [str(p) for p in mine[index:]]
                ) from exc
            removed.append(str(path))
        result["pruned"] = removed
        return
    result["stale"] = [str(p) for p in mine]
    print(
        f"warning: {len(mine)} artifact(s) in {output_dir} are left over from an "
        f"earlier render and were not replaced; applying the directory would "
        f"redeploy them. Re-run with --prune to remove them.",
        file=sys.stderr,
    )


def _scan_failure_report(exc: OSError, published: list[Path], lint: str | None = None) -> dict:
    """A stale scan that could not run, after the output has already changed.

    Its own reason, because the alternatives both lie. Reported as a publish
    failure it claims a rollback that did not happen -- the manifests are live.
    Left to escape it is a traceback, and the caller learns neither what was
    published nor whether anything was removed.
    """
    report: dict = {
        "status": "error",
        "reason": "stale-scan-failed",
        "output_modified": True,
        "files": [str(p) for p in published],
        "pruned": [],
        "message": (
            "the manifests were published, but the directory could not be read "
            f"back to find artifacts this render replaced: {exc}"
        ),
    }
    if lint is not None:
        report["lint"] = lint
    return report


def _finite_seconds(raw: str) -> float:
    """A timeout argparse's `float` would otherwise accept and the loop cannot use.

    `float("nan")` and `float("inf")` both parse. With nan every comparison against
    the deadline is False, so the wait never ends -- and `min(0.2, max(0.0, nan))`
    is 0.0, so it never sleeps either: an unbounded busy-spin, worse than the
    blocking LOCK_EX this replaced, which at least waited in the kernel. With inf
    it is the same unbounded wait the bound exists to remove.
    """
    try:
        value = float(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{raw!r} is not a number of seconds") from None
    if value != value or value in (float("inf"), float("-inf")):
        raise argparse.ArgumentTypeError(
            f"{raw!r} is not a finite number of seconds, so the wait would never end"
        )
    if value < 0:
        raise argparse.ArgumentTypeError(f"{raw!r} is negative")
    if value > _MAX_LOCK_TIMEOUT:
        raise argparse.ArgumentTypeError(
            f"{raw!r} is longer than a day; a wait that long is not a bound"
        )
    return value


def _absolute_directory(raw: str) -> str:
    """A lock directory both writers can name identically.

    A relative path is resolved against the working directory, and two writers
    that could not agree on a temp directory have no more reason to agree on
    that. It would fail the same silent way the default does: two lock files,
    both writers publishing, nothing recording it.
    """
    if not os.path.isabs(raw):
        raise argparse.ArgumentTypeError(
            f"{raw!r} is relative, so it names a different directory to a writer "
            "started elsewhere; give the shared path in full"
        )
    return raw


def _add_lock_args(p: argparse.ArgumentParser) -> None:
    """Add the output-root lock flag to a subcommand that writes artifacts."""
    p.add_argument(
        "--lock-timeout",
        type=_finite_seconds,
        default=_DEFAULT_LOCK_TIMEOUT,
        help="Seconds to wait for the output directory's publish lock before giving "
        "up. Every command that writes the directory takes the same lock, so a "
        "render cannot replace files another one has staged, linted and is about to "
        "publish. Waiting without a bound would let a hung holder stall this command "
        "indefinitely, so a timeout exits 2 -- the gate could not run -- rather than "
        "reporting a lint failure the linter never gave.",
    )
    p.add_argument(
        "--lock-dir",
        type=_absolute_directory,
        default=None,
        help="Absolute directory holding the publish lock. The default is a fixed "
        "path, which is one directory on a host and two inside two containers that "
        "share only the output volume; pointing both at that volume gives them one "
        "lock file again. Two things it cannot check for you: the writers have to "
        "reach the output directory by the same path, since the lock is named after "
        "that path, and no other user may be able to replace the file -- on the "
        "default that is what the sticky bit is doing.",
    )


def _add_policy_args(p: argparse.ArgumentParser) -> None:
    """Add the shared policy-gate flags to an artifact-producing subcommand."""
    p.add_argument("--unsafe-skip-policy", action="store_true", help=_UNSAFE_SKIP_POLICY_HELP)
    p.add_argument(
        "--policy-engine", choices=("opa", "baseline"), default="opa", help=_POLICY_ENGINE_HELP
    )
    p.add_argument("--bundle", default=DEFAULT_POLICY_BUNDLE, help="OPA policy bundle directory")
    p.add_argument("--decision", default=DEFAULT_POLICY_DECISION, help="OPA decision path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orbital-mission-compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser("compile", help="Compile mission plan to workflow payload")
    compile_p.add_argument("--input", required=True)
    compile_p.add_argument("--output", required=True)
    _add_policy_args(compile_p)
    compile_p.set_defaults(func=cmd_compile)

    render_p = sub.add_parser("render-argo", help="Render individual Argo Workflow manifests")
    render_p.add_argument("--input", required=True)
    render_p.add_argument("--output-dir", required=True)
    render_p.add_argument(
        "--dra-fallback",
        action="store_true",
        help="Wire the accelerator-fallback step's Pod to a DRA firstAvailable "
        "ResourceClaimTemplate via podSpecPatch (scheduler-level GPU->CPU fallback), "
        "and emit that RCT alongside the Workflow as a self-contained multi-doc file. "
        "Off by default (runtime env-var switch). The firstAvailable claim is a "
        "scheduler-route artifact and is not Kueue quota-counted.",
    )
    render_p.add_argument("--prune", action="store_true", help=_PRUNE_HELP)
    render_p.add_argument(
        "--namespace",
        default=None,
        help="Stamp metadata.namespace on the rendered objects. Off by default, so "
        "an ordinary Workflow stays namespace-less and the namespace is chosen at "
        "'argo submit -n' or 'kubectl apply -n' time. --dra-fallback needs one, "
        "because the Workflow and the claim template it references must agree, and "
        "defaults to 'orbital-demo' there.",
    )
    render_p.add_argument(
        "--argo-lint",
        action="store_true",
        help="After rendering, run the official 'argo lint' as a fail-closed gate. "
        "It lints the Argo kinds; every other kind in the directory is checked "
        "only for its apiVersion/kind/metadata envelope, so those specs still "
        "need server-side validation. "
        "Manifests are staged and published only if lint passes, so a rejected "
        "render leaves the output directory unchanged. A lint failure exits 1; "
        "the gate being unable to run at all -- CLI absent, timeout, no manifest "
        "to lint -- exits 2. Off by default, so the CLI stays optional locally.",
    )
    render_p.add_argument(
        "--argo-bin",
        default="argo",
        help="Argo CLI executable used by --argo-lint (name on PATH or a path). "
        "Its version sets the lint semantics applied.",
    )
    render_p.add_argument(
        "--service-account",
        default=None,
        help="Stamp spec.serviceAccountName on the rendered Workflow. Needed when "
        "the multi-doc --dra-fallback bundle is applied with kubectl, since "
        "'argo submit --serviceaccount' cannot be used on it (argo submit drops "
        "the ResourceClaimTemplate document).",
    )
    _add_lock_args(render_p)
    _add_policy_args(render_p)
    render_p.set_defaults(func=cmd_render_argo)

    inspect_p = sub.add_parser("inspect", help="Inspect compiled workflow intents")
    inspect_p.add_argument("--input", required=True)
    inspect_p.set_defaults(func=cmd_inspect)

    kueue_p = sub.add_parser("render-kueue", help="Render Kueue-compatible Job manifests")
    kueue_p.add_argument("--input", required=True)
    kueue_p.add_argument("--output-dir", required=True)
    kueue_p.add_argument("--prune", action="store_true", help=_PRUNE_HELP)
    kueue_p.add_argument("--queue", default="orbital-demo-local")
    kueue_p.add_argument("--namespace", default="orbital-demo")
    kueue_p.add_argument(
        "--dra-fallback",
        action="store_true",
        help="Additionally emit the scheduler-route DRA firstAvailable claim "
        "(accelerator->CPU) for steps that declare a driver-backed "
        "fallback_resource_class. The Job itself still references the 'exactly' "
        "GPU claim, because Kueue rejects a firstAvailable request as "
        "inadmissible and quota-counts only 'exactly'. The firstAvailable "
        "template is therefore for a non-Kueue consumer; 'render-argo "
        "--dra-fallback' emits it wired to a Workflow that uses it.",
    )
    kueue_p.add_argument(
        "--priority-class",
        action="store_true",
        help="Label each Job with kueue.x-k8s.io/priority-class (mission priority -> "
        "ORCHIDE tier -> WorkloadPriorityClass), so priority feeds Kueue queue sorting "
        "and preemption eligibility. The referenced classes must exist -- pair with "
        "--emit-priority-classes and apply them first.",
    )
    kueue_p.add_argument(
        "--emit-priority-classes",
        action="store_true",
        help="Also write the four cluster-scoped WorkloadPriorityClass objects (one per "
        "ORCHIDE tier) to workload-priority-classes.yaml in the output dir.",
    )
    kueue_p.add_argument(
        "--priority-class-prefix",
        default=ORCHIDE_PRIORITY_CLASS_PREFIX,
        help="Name prefix for the WorkloadPriorityClass objects and the Job label "
        f"(default {ORCHIDE_PRIORITY_CLASS_PREFIX!r}); set per-installation to avoid "
        "collisions on the cluster-scoped names.",
    )
    _add_lock_args(kueue_p)
    _add_policy_args(kueue_p)
    kueue_p.set_defaults(func=cmd_render_kueue)

    policy_p = sub.add_parser("policy", help="Evaluate policy pack with OPA if available")
    policy_p.add_argument("--input", required=True)
    policy_p.add_argument("--bundle", default=DEFAULT_POLICY_BUNDLE)
    policy_p.add_argument("--decision", default=DEFAULT_POLICY_DECISION)
    policy_p.set_defaults(func=cmd_policy)

    return parser


def cmd_compile(args: argparse.Namespace) -> None:
    payload = compile_file(
        args.input, args.output, enforce_policy=not args.unsafe_skip_policy,
        policy_engine=args.policy_engine, bundle=args.bundle, decision=args.decision,
    )
    print(json.dumps({"status": "ok", "workflows": len(payload["workflows"])}, indent=2))


def _render_argo(args: argparse.Namespace, output_dir: str | Path) -> list[Path]:
    # args.namespace goes straight through: the writer supplies one for a DRA
    # bundle, whose two documents have to share it, and leaves an ordinary render
    # namespace-less so it is chosen when the manifest is applied.
    return write_individual_workflows(
        args.input, output_dir, enforce_policy=not args.unsafe_skip_policy,
        policy_engine=args.policy_engine, bundle=args.bundle, decision=args.decision,
        dra_fallback=args.dra_fallback, namespace=args.namespace,
        service_account=args.service_account,
    )


def _prune_failure_report(exc: "PruneIncomplete", published: list[Path]) -> dict[str, object]:
    """What a prune that stopped part-way leaves behind.

    Publication has already committed by then, so this is not a failed publish
    and nothing was rolled back. Every command that prunes reports it the same
    way, because the caller has the same problem to act on whichever one they
    ran: new manifests in place, and part of the previous generation still
    there.
    """
    return {
        "status": "error", "reason": "prune-failed",
        "output_modified": True,
        "files": [str(p) for p in published],
        "pruned": exc.removed,
        "not_pruned": exc.remaining,
        "message": str(exc),
    }


def cmd_render_argo(args: argparse.Namespace) -> None:
    if args.argo_lint:
        _render_argo_with_lint_gate(args)
        return
    # The same lock the gate takes. Without it an ungated render can replace files
    # in the directory a gated run has just snapshotted and linted and is about to
    # publish into, and the gate's verdict would then describe a directory that no
    # longer exists.
    #
    # Best-effort here, unlike in the gate. A platform with no flock cannot run the
    # gate either, so there is no gated writer to interleave with, and refusing to
    # render would be a new failure for a command that makes no promise of
    # exclusivity of its own.
    lock_stack = contextlib.ExitStack()
    try:
        lock_stack.enter_context(_publish_lock(Path(args.output_dir), args.lock_timeout, args.lock_dir))
    except PublishLockUnsupported:
        # Nothing on this platform can lock, so nothing is holding the directory.
        pass
    except PublishLockUnavailable as exc:
        # The lock exists and this process cannot open it, which is the case it was
        # added for: a gated run created it, is holding it, and is about to publish
        # into this directory. Writing anyway would replace the files between its
        # snapshot and its publication, so the verdict it reports would describe a
        # directory that no longer exists. An earlier revision caught the parent
        # exception here and carried on, which failed open exactly when it mattered.
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "publish-lock-unavailable",
                    "detail": str(exc),
                },
                indent=2,
            )
        )
        raise SystemExit(2) from exc
    with lock_stack:
        written = _render_argo(args, args.output_dir)
        result: dict[str, object] = {"status": "ok", "files": [str(p) for p in written]}
        try:
            _report_stale(
                result, args.output_dir, written, args.prune, ARGO_EXCLUSIVE_KINDS,
                mission_ids=_render_scope(args.input),
            )
        except PruneIncomplete as exc:
            print(json.dumps(_prune_failure_report(exc, written), indent=2))
            raise SystemExit(2) from exc
        except OSError as exc:
            print(json.dumps(_scan_failure_report(exc, written), indent=2))
            raise SystemExit(2) from exc
    print(json.dumps(result, indent=2))


def _nearest_existing_ancestor(path: Path) -> Path:
    """The closest existing directory at or above ``path``.

    Staging goes here so publishing is a same-filesystem rename, without having
    to create the output directory first: a denied plan or a rejected lint must
    leave a path that did not exist before the command exactly as absent. When
    the output directory does exist this is the directory itself, which is
    deliberate -- an output directory that is a mount point has a parent on a
    different filesystem, and a rename across that boundary cannot work.
    """
    current = path.absolute()
    while not current.is_dir():
        parent = current.parent
        if parent == current:
            break
        current = parent
    return current


class PublishLockUnavailable(Exception):
    """This process cannot take the publish lock for the output directory."""


class PublishLockUnsupported(PublishLockUnavailable):
    """No process on this platform can take the lock, so none is holding it.

    Kept apart from its parent because the two mean opposite things to a writer
    that is not itself a gate. Nothing can lock here, so there is no gated run to
    interleave with and an unlocked write is as safe as it ever was. A lock that
    exists and cannot be opened is the other case entirely: something took it."""


def _load_documents(path: Path, text: str) -> list:
    """Read one file the way the tool that will apply it reads that file.

    kubectl dispatches on CONTENT: NewYAMLOrJSONDecoder calls hasJSONPrefix, which
    trims by Go's unicode.IsSpace -- NBSP included -- and asks whether the first
    byte is `{`. If it is, the file goes to a JSON decoder that reads a STREAM, so
    concatenated objects are several documents; otherwise to the YAML decoder.

    Both details were got wrong once each, in opposite directions, and both are
    now pinned by tests/test_kubectl_parity.py rather than by this docstring.
    """
    if text.startswith("\ufeff"):
        text = text[1:]
    # str.lstrip() strips what Go's unicode.IsSpace strips, which is the set
    # hasJSONPrefix uses. Narrowing it to what json.loads skips moved this away
    # from kubectl rather than toward it.
    stripped = text.lstrip()
    if stripped[:1] == "{":
        try:
            return _json_stream(stripped)
        except json.JSONDecodeError:
            # A YAML flow mapping also opens with `{`, and kubectl reaches it the
            # same way when the JSON decode fails.
            pass
    return list(yaml.safe_load_all(text))


def _json_stream(text: str) -> list:
    """Every JSON value in the text, as kubectl's streaming decoder reads them."""
    decoder = json.JSONDecoder()
    docs: list = []
    index = 0
    while True:
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            return docs
        value, index = decoder.raw_decode(text, index)
        docs.append(value)


def _document_problems(doc: object, where: str) -> list[str]:
    """Why kubectl would refuse this document, or nothing.

    Each rule below is measured against `kubectl apply --dry-run=client
    --validate=strict` in tests/test_kubectl_parity.py. Rules asserted here and
    checked nowhere drifted from kubectl five times.
    """
    if not isinstance(doc, dict):
        return [f"{where}: is a {type(doc).__name__}, not an object"]
    if not isinstance(doc.get("apiVersion"), str) or not doc["apiVersion"]:
        return [f"{where}: has no apiVersion, or one that is not a string"]
    if not isinstance(doc.get("kind"), str) or not doc["kind"]:
        return [f"{where}: has no kind, or one that is not a string"]
    if doc["kind"] == "List":
        # A List carries no metadata of its own and kubectl validates its members,
        # so exempting it wholesale -- as an earlier revision did -- accepted a
        # List of invalid objects, which is the false pass this gate exists to
        # prevent, reached from the other side.
        items = doc.get("items")
        if not isinstance(items, list) or not items:
            return [f"{where}: is a List with no items"]
        problems: list[str] = []
        for i, item in enumerate(items):
            problems += _document_problems(item, f"{where} item {i + 1}")
        return problems
    meta = doc.get("metadata")
    if not isinstance(meta, dict) or not meta:
        return [f"{where}: has no metadata, or one that is not an object"]
    if not meta.get("name") and not meta.get("generateName"):
        # `kubectl apply` reads the live object by name before merging, so a
        # document with metadata but no name cannot be applied. The docstring gave
        # this reason for months while nothing checked it.
        return [f"{where}: has metadata but no name"]
    return []


def _unreadable_documents(directory: Path) -> list[str]:
    """Every reason a staged file would not survive `kubectl apply`, named.

    Checked before the linter rather than inferred from its output afterwards.
    The rules are not this tool's opinion: each was checked against kubectl
    itself, client-side with --validate=strict, on the version this repository is
    validated against.

        document                 apply       create      where the answer comes from
        unparseable YAML         reject      reject      kubectl, decoding
        not a mapping            reject      reject      kubectl, schema validation
        no apiVersion            reject      reject      kubectl, schema validation
        no metadata              reject      reject      apply: client-side, needs a
                                                         name to read the live object;
                                                         create: the API server
        duplicate mapping key    accept      accept      see below

    So this rejects the first four and nothing else.

    A caveat on `no metadata`, because the first version of this table got it
    wrong: `kubectl create --dry-run=client` accepts such a document, which is why
    an earlier revision recorded create as accepting it. That is an artefact of the
    client dry run never contacting the server. `--dry-run=server` answers
    `metadata.name: Required value: name or generateName is required`. Rejecting it
    is right for both verbs.

    On duplicate keys, this deliberately does NOT reject, and the reason is
    narrower than it first looks. kubectl decodes a `-f` file with
    sigs.k8s.io/yaml, which is last-wins, and re-serialises before sending -- so
    the API server never sees the duplicate and the document deploys as the later
    value. But the server DOES reject duplicates when it is given them directly
    (`kubectl create --raw` with `fieldValidation=Strict`: `strict decoding error:
    duplicate field`), and `kubectl apply -k` rejects them client-side through
    kyaml. So "Kubernetes tolerates duplicates" is false; "the path this output is
    applied through tolerates them" is what holds. Refusing them here would still
    fail a manifest that deploys via `-f`, which is the false verdict this gate
    must not give.

    Empty documents are allowed -- a trailing `---` is legal and applies nothing.
    """
    problems: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix not in (".yaml", ".yml", ".json"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError) as exc:
            problems.append(f"{path.name}: cannot be read: {exc}")
            continue
        try:
            docs = _load_documents(path, text)
        except (yaml.YAMLError, json.JSONDecodeError) as exc:
            problems.append(f"{path.name}: cannot be parsed: {exc}")
            continue
        except RecursionError as exc:
            # PyYAML composes recursively, so deep nesting overflows the stack. Not
            # a verdict on the manifest: the gate could not read it. Raised rather
            # than appended, because a problem here exits 1, and 1 means the linter
            # rejected something -- CI would read a crash as a lint failure.
            raise ArgoLintUnavailable(
                f"{path.name} nests too deeply for the parser to read, so the gate "
                f"could not decide whether it is valid: {exc}"
            ) from exc
        except MemoryError as exc:
            raise ArgoLintUnavailable(
                f"{path.name} could not be held in memory to be read, so the gate "
                "could not decide whether it is valid"
            ) from exc
        for index, doc in enumerate(docs):
            if doc is None:
                continue
            problems += _document_problems(doc, f"{path.name} document {index + 1}")
    return problems


def _default_lock_dir() -> str:
    """Where the publish lock lives when the caller does not say.

    A fixed path rather than tempfile.gettempdir(), which honours TMPDIR and so
    hands two renders of one output directory two different lock files. Falls
    back to the temp directory only where the fixed one is unusable, which is
    also where there is no shared location to be had.
    """
    fixed = Path("/tmp")  # noqa: S108 - shared by design; see the caller's O_NOFOLLOW
    if fixed.is_dir() and os.access(fixed, os.W_OK):
        return str(fixed)
    return tempfile.gettempdir()


class _SymlinkedManifest(Exception):
    """A manifest in the destination that is a link to bytes the gate cannot hold."""

    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


def publish_lock_path(out_dir: Path | str, lock_dir: str | None = None) -> Path:
    """Where two renders of this output directory agree the lock is.

    Derived in one place so a caller asking the question and the code taking the
    lock cannot answer it differently. Tests recomputing it from a copy of this
    is how a change of location left four of them passing only because the
    environment happened to agree.
    """
    digest = hashlib.sha256(os.path.realpath(out_dir).encode("utf-8")).hexdigest()[:16]
    return Path(lock_dir or _default_lock_dir()) / f"orbital-publish-{digest}.lock"


@contextlib.contextmanager
def _publish_lock(
    out_dir: Path, lock_timeout: float = _DEFAULT_LOCK_TIMEOUT,
    lock_dir: str | None = None,
) -> Iterator[None]:
    """Serialise publishing into one output directory.

    Two renders publishing at once interleave their files and the directory ends
    up holding some of each, with nothing recording that. The lock lives beside
    the output rather than inside it, so taking it does not create the directory
    a failed run has to leave absent.
    """
    # Keyed by the output path but kept outside it, for two reasons. It has to be
    # somewhere that exists whether or not the output directory does -- anchoring
    # it to the nearest existing ancestor would give two processes different lock
    # files when one of them runs before the directory is created and the other
    # after, which is exactly when they would collide. And a lock file is not
    # something to leave in an operator's output.
    #
    # Not tempfile.gettempdir(), which reads TMPDIR: two renders of the same
    # output directory under different TMPDIR values took two lock files with the
    # same name in different directories and both entered publication at once,
    # measured. The key was already shared; only the namespace was not. A fixed
    # location restores the guarantee on one host.
    #
    # It does not restore it between containers that share only the output volume,
    # because they share no other filesystem and no default can invent one. That
    # is what --lock-dir is for, pointed at the shared volume; nothing here can
    # detect the mismatch, so it is stated rather than guessed at.
    try:
        import fcntl  # Unix-only, and only this feature needs it
    except ImportError as exc:
        # Structured, not a traceback. The gate promises a single JSON document
        # on stdout and exit 2 when it cannot run; a platform without flock is
        # one more way it cannot run, not a different kind of event.
        raise PublishLockUnsupported(
            "the publish lock needs fcntl, which this platform does not provide, "
            "so --argo-lint cannot serialise publishing here"
        ) from exc

    # realpath, not absolute(): absolute() leaves `..` in place and does not
    # resolve symlinks, so /data/out and /data/tmp/../out would take different
    # locks on the same directory -- the case the lock exists for.
    canonical = os.path.realpath(out_dir)
    lock_path = publish_lock_path(out_dir, lock_dir)
    # Openable by whoever can write the output, because that is who has to take it.
    # An earlier revision created it 0600 and never removed it, so once one user had
    # rendered, every other user was refused for good -- flock is released when the
    # descriptor closes, so the file outliving the run says nothing about a holder,
    # and treating "cannot open" as "somebody holds it" turned a race into a lockout.
    #
    # O_NOFOLLOW because the permissive mode is what 0600 was standing in for: the
    # path is predictable and lives in a shared directory, so the open must refuse a
    # symlink someone else planted rather than follow it. The temp directory's sticky
    # bit is what stops another user replacing the file once it exists.
    flags = os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    try:
        handle = os.open(lock_path, flags, 0o666)
    except OSError as exc:
        raise PublishLockUnavailable(
            f"the publish lock at {lock_path} could not be opened, so publishing "
            f"cannot be serialised here: {exc}"
        ) from exc
    try:
        info = os.fstat(handle)
        if not stat.S_ISREG(info.st_mode):
            raise PublishLockUnavailable(
                f"the publish lock at {lock_path} is not a regular file"
            )
        # The mode argument to open() is masked by the process umask, which on a
        # default 022 leaves 0644 -- readable by the next user but not writable, and
        # this is opened O_RDWR, so they still could not take it. Set it explicitly
        # once, and only on the file this process created; if it belongs to someone
        # else it is already whatever they made it and is not ours to change.
        if info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) != 0o666:
            try:
                os.fchmod(handle, 0o666)
            except OSError:  # pragma: no cover - a filesystem that will not take it
                pass
        # Bounded, not blocking. A plain LOCK_EX waits with no upper bound, so a
        # holder that hung -- or one that simply takes longer than anyone is willing
        # to wait -- turns this command into an indefinite stall, and the predictable
        # path means any local user who can open the file can cause it. Failing to
        # obtain exclusivity is a gate that could not run: exit 2 with no verdict and
        # nothing published, never a lint rejection, which would assert something the
        # linter never said.
        started = time.monotonic()
        deadline = started + lock_timeout
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                # Only contention is worth retrying. EWOULDBLOCK/EAGAIN is another
                # holder; ENOLCK, EOPNOTSUPP, EINVAL and friends mean this
                # filesystem cannot take the lock at all -- an NFS mount with no
                # lockd, most concretely -- and retrying for the whole timeout only
                # to report "held by another render" is an assertion, and a false
                # one. That case is what PublishLockUnsupported is for.
                # An allowlist, not a denylist. The first version treated every
                # errno except EAGAIN as "this filesystem cannot lock", which then
                # let the two ungated writers proceed unlocked -- so a transient
                # EIO or ENOMEM on the lock file silently disabled the mutual
                # exclusion this branch is built on, possibly while a gated render
                # was mid-lint holding it.
                if exc.errno in _LOCK_UNSUPPORTED_ERRNOS:
                    raise PublishLockUnsupported(
                        f"the publish lock at {lock_path} cannot be taken on this "
                        f"filesystem ({exc.strerror}), so publishing cannot be "
                        "serialised here"
                    ) from exc
                if exc.errno not in (errno.EWOULDBLOCK, errno.EAGAIN, errno.EINTR):
                    # Not contention, not a filesystem that cannot lock: something
                    # went wrong that neither retrying nor proceeding answers.
                    raise PublishLockUnavailable(
                        f"the publish lock at {lock_path} could not be taken "
                        f"({exc.strerror}); publishing was not attempted"
                    ) from exc
                # EINTR falls through to the deadline check and the sleep with
                # everything else. Skipping both, as an earlier revision did, was
                # an unbounded spin at 100% of a core -- exactly what the timeout
                # exists to prevent, and unreachable on CPython only because PEP
                # 475 retries in C.
                if time.monotonic() >= deadline:
                    raise PublishLockUnavailable(
                        f"the publish lock at {lock_path} is held by another render; "
                        f"waited {time.monotonic() - started:.0f}s of {lock_timeout:.0f}s "
                        f"for the output directory {canonical}. Nothing was linted or "
                        "published."
                    ) from None
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
    finally:
        os.close(handle)


class PublishRolledBackPartially(OSError):
    """Publishing failed and the directory could not be put back as it was.

    Two ways that happens, and both leave the output modified: a file this
    render displaced could not be restored, or a file this render created could
    not be removed again. Carries where the surviving copies are, because for
    the displaced ones the backup is the only place they still exist.
    """

    def __init__(
        self, reason: str, recovery: Path, unrestored: list[str], unremoved: list[str]
    ) -> None:
        parts = []
        if unrestored:
            parts.append(f"{len(unrestored)} displaced file(s) could not be restored")
        if unremoved:
            parts.append(f"{len(unremoved)} newly published file(s) could not be removed")
        super().__init__(
            f"publishing failed ({reason}) and {' and '.join(parts)}; "
            f"the backup is in {recovery}"
        )
        self.recovery = recovery
        self.unrestored = unrestored
        self.unremoved = unremoved


class PruneIncomplete(OSError):
    """Pruning stopped part-way, after publication had already succeeded.

    Publication committed before this ran, so the new manifests are in place and
    what is left is an incomplete removal of the previous generation. Reporting
    it as a failed publish would be wrong twice over: nothing was rolled back,
    and the phase that failed was not the publish.
    """

    def __init__(self, reason: str, removed: list[str], remaining: list[str]) -> None:
        super().__init__(
            f"the manifests were published, but pruning stopped after removing "
            f"{len(removed)} of {len(removed) + len(remaining)} stale artifact(s): {reason}"
        )
        self.removed = removed
        self.remaining = remaining


def _discard_backup(backup_dir: Path, leftover_backups: list[str] | None) -> None:
    """Remove the backup tree, and say so when it cannot be removed.

    ignore_errors=True made this silent, so a publication could report a clean
    directory while the previous generation stayed in a hidden tree inside it --
    old manifests a recursive apply or a scanner can still reach, and storage
    nobody knows to reclaim. The publication itself is complete and correct, so
    this does not fail the command; it names the path instead of hiding it.
    """
    shutil.rmtree(backup_dir, ignore_errors=True)
    if backup_dir.exists() and leftover_backups is not None:
        leftover_backups.append(str(backup_dir))


def _publish(
    staged: list[Path], out_dir: Path, leftover_backups: list[str] | None = None
) -> list[Path]:
    """Move a rendered set into the output directory, all of it or none of it.

    Each rename is atomic on its own, but the set is what a caller applies. A
    failure part-way through would leave the directory holding some files from
    this render and some from the last one, and nothing would say so. Whatever a
    rename displaces is kept aside until the whole set lands, and put back if it
    does not; directories this call created are removed again on the way out.
    """
    created_dirs: list[Path] = []
    probe = out_dir.absolute()
    while not probe.is_dir():
        created_dirs.append(probe)
        probe = probe.parent
    backup_dir = Path(tempfile.mkdtemp(prefix=".orbital-publish-backup-", dir=probe))
    out_dir.mkdir(parents=True, exist_ok=True)

    displaced: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for path in staged:
            target = out_dir / path.name
            if target.exists():
                kept = backup_dir / target.name
                os.replace(target, kept)
                displaced[target] = kept
            os.replace(path, target)
            published.append(target)
    except OSError as exc:
        unrestored: list[str] = []
        unremoved: list[str] = []
        for target in published:
            try:
                target.unlink()
            except OSError:
                # Not suppressed. A file this render created and cannot remove
                # is the directory left modified, exactly as an unrestorable
                # displaced file is; swallowing it here is how the caller came
                # to be told the output was rolled back while a new artifact
                # from the failed set was still sitting in it.
                unremoved.append(str(target))
        for target, kept in displaced.items():
            try:
                os.replace(kept, target)
            except OSError:
                unrestored.append(str(target))
            else:
                # Putting the previous file back is what "removed" was for. A
                # target that failed to unlink and was then overwritten by its
                # own backup holds nothing from this render, so reporting it as
                # left behind would be a claim the directory contradicts.
                unremoved = [u for u in unremoved if u != str(target)]
        if unrestored or unremoved:
            # The backup holds the only remaining copy of the displaced ones, so
            # it stays and the caller is told where. Deleting it here on the way
            # out of a failed rollback is how a previous good artifact would be
            # lost for good, while the command reported the directory as
            # restored.
            raise PublishRolledBackPartially(
                str(exc), backup_dir, unrestored, unremoved
            ) from exc
        for created in created_dirs:
            with contextlib.suppress(OSError):
                created.rmdir()
        _discard_backup(backup_dir, leftover_backups)
        raise
    _discard_backup(backup_dir, leftover_backups)
    return published


def _reconcile_empty_render(
    args: argparse.Namespace, out_dir: Path, lock_stack: contextlib.ExitStack
) -> None:
    """A plan that renders nothing, asked to make the directory match it.

    An empty desired set is a state to reconcile, not a reason to leave the
    previous generation on disk for the next apply to redeploy. No linter runs,
    so the verdict is not-applicable and never passed -- and, for the same
    reason, the Argo binary is not needed to get here.
    """
    try:
        lock_stack.enter_context(_publish_lock(out_dir, args.lock_timeout, args.lock_dir))
    except PublishLockUnavailable as exc:
        print(json.dumps({
            "status": "error", "lint": "not-run", "reason": "publish-lock-unavailable",
            "message": str(exc),
        }, indent=2))
        raise SystemExit(2) from exc
    empty_result: dict[str, object] = {"status": "ok", "lint": "not-applicable", "files": []}
    try:
        _report_stale(
            empty_result, args.output_dir, [], args.prune, ARGO_EXCLUSIVE_KINDS,
            mission_ids=_render_scope(args.input),
        )
    except PruneIncomplete as exc:
        print(json.dumps(_prune_failure_report(exc, []), indent=2))
        raise SystemExit(2) from exc
    except OSError as exc:
        print(json.dumps(_scan_failure_report(exc, []), indent=2))
        raise SystemExit(2) from exc
    print(json.dumps(empty_result, indent=2))


def _render_argo_with_lint_gate(args: argparse.Namespace) -> None:
    """Render, lint, and publish only if the linter accepts what it reads.

    "Accepts" is narrower than it sounds, and the narrowness is the honest part.
    Every document in the published set is parsed and checked for the envelope
    kubectl requires -- apiVersion, kind, metadata -- against the parity tests.
    Semantic linting is `argo lint`, which covers Workflow, WorkflowTemplate,
    CronWorkflow and ClusterWorkflowTemplate and silently ignores everything
    else. Measured on v4.0.8: a Job whose `containers` is a string, which kubectl
    refuses outright, lints clean beside a valid Workflow. Kueue Jobs and
    ResourceClaimTemplates in the same directory therefore get the envelope check
    and nothing more, and a set that needs their specs validated needs
    server-side validation as well as this.

    Order matters. Rendering comes first, so a schema or policy failure is
    reported as itself instead of being masked by a missing linter. The CLI is
    resolved before the empty-render check, because a plan is allowed to render
    nothing -- a download-only plan is schema-valid and passes the policy layer --
    and an empty render must not be able to report a lint that never ran.
    """
    out_dir = Path(args.output_dir)
    staging = Path(tempfile.mkdtemp(
        prefix=".argo-lint-staging-", dir=_nearest_existing_ancestor(out_dir)
    ))
    carried: list[Path] = []
    result_stale: dict[str, object] = {}
    lock_stack = contextlib.ExitStack()
    try:
        written = _render_argo(args, staging)

        # Resolved after the prune-only case below and before every other one.
        # A plan is allowed to render nothing, and an empty render must not be
        # able to report a lint that never ran -- but reconciling an empty
        # desired set runs no linter at all, so requiring the binary there made
        # cleanup depend on a tool it never invokes.
        if not written and args.prune:
            _reconcile_empty_render(args, out_dir, lock_stack)
            return

        try:
            resolved = resolve_argo_bin(args.argo_bin)
        except ArgoLintUnavailable as exc:
            print(json.dumps({"status": "error", "lint": "unavailable", "message": str(exc)}, indent=2))
            raise SystemExit(2) from exc

        if not written:
            # A plan may legitimately render nothing, and without --prune that
            # means there is nothing to publish and nothing was verified, which
            # is what exit 2 has always said here. The --prune case was taken
            # above, before the linter was resolved.
            print(json.dumps({
                "status": "error", "lint": "not-run", "reason": "no-manifests",
                "message": "the plan rendered no Argo Workflow, so nothing was linted",
            }, indent=2))
            raise SystemExit(2)

        # Taken before the destination is read, not just before it is written.
        # The verdict is about a directory state, and a state read outside the
        # lock is only what was there at the time of the read: another gated
        # render can publish into the gap, and this run would then commit
        # against a set the linter never saw. Held across the lint so that the
        # state the verdict describes is the state that gets published.
        try:
            lock_stack.enter_context(_publish_lock(out_dir, args.lock_timeout, args.lock_dir))
        except PublishLockUnavailable as exc:
            print(json.dumps({
                "status": "error", "lint": "not-run", "reason": "publish-lock-unavailable",
                "message": str(exc),
            }, indent=2))
            raise SystemExit(2) from exc

        # Lint what the directory will actually hold once this render is done:
        # what is there now, less what --prune is about to remove, plus what
        # this render produces. Staging carries only the last of those, but a
        # file already in the output that this plan no longer produces survives
        # the publish and `kubectl apply -f <dir>` takes it along, so it belongs
        # in the verdict. The copies are dropped again before publishing, so
        # this does not rewrite files the render does not own.
        #
        # Subtracting the prune set matters: carrying a stale file this run is
        # about to delete lets it fail the lint and so block its own removal --
        # `--prune` could not repair the state it exists to repair.
        staged_names = {path.name for path in written}
        try:
            if out_dir.is_dir():
                # Every extension `kubectl apply -f <dir>` consumes, not only
                # .yaml. A leftover invalid workflow saved as .yml would
                # otherwise be applied with the directory while the gate
                # reported it clean.
                # Listed rather than globbed: `Path.glob` swallows the OSError
                # scandir raises, so a destination that cannot be read would
                # come back empty, nothing would be carried, and the gate would
                # lint only its own render and call the directory clean.
                existing_manifests = sorted(
                    q for q in out_dir.iterdir()
                    if q.suffix in (".yaml", ".yml", ".json")
                )
                # Only what --prune will ACTUALLY remove. Subtracting the whole
                # stale candidate set excluded files from the lint that
                # attribution then declined to delete -- so adding --prune turned
                # a correct "lint-failed" into "lint: passed" about a directory
                # kubectl still rejects. The RCT-only scheduler-fallback file is
                # exactly that shape, and by design neither renderer can prune it.
                leaving = (
                    {
                        p.name
                        for p in attribute_stale(
                            stale_rendered_artifacts(
                                out_dir, written, mission_ids=_render_scope(args.input),
                            ),
                            ARGO_EXCLUSIVE_KINDS,
                        )[0]
                    }
                    if args.prune else set()
                )
                for existing in existing_manifests:
                    if existing.name in staged_names or existing.name in leaving:
                        continue
                    if existing.is_symlink():
                        # Refused rather than followed. Both is_file() and copy2()
                        # resolve the link, so the verdict would be about the
                        # target's bytes while the output keeps a link whoever owns
                        # the target can repoint afterwards. The gate exists to say
                        # that what was linted is what gets applied, and about a
                        # symlink it cannot.
                        raise _SymlinkedManifest(str(existing))
                    if not existing.is_file():
                        continue
                    copy = staging / existing.name
                    shutil.copy2(existing, copy)
                    carried.append(copy)
        except _SymlinkedManifest as exc:
            print(json.dumps({
                "status": "error", "lint": "not-run", "reason": "symlinked-manifest",
                "message": (
                    f"{exc.path} is a symbolic link, so the gate cannot promise the "
                    "bytes it lints are the bytes that will be applied. Replace it "
                    "with the file itself, or move it out of the output directory."
                ),
            }, indent=2))
            raise SystemExit(2) from exc
        except OSError as exc:
            # Reading the destination can fail on its own: a manifest removed
            # between the glob and the copy, a directory that became
            # unreadable. Nothing has been published at this point, and this
            # command promises one JSON document rather than a traceback.
            print(json.dumps({
                "status": "error", "lint": "not-run", "reason": "snapshot-failed",
                "message": f"could not read {out_dir} to decide what to lint, so nothing "
                           f"was published: {exc}",
            }, indent=2))
            raise SystemExit(2) from exc

        # Syntax first, and locally. Argo's own signal for an unparseable file is a
        # line of human-readable log, which a release can reword, a locale can
        # translate and a log-format change can move -- and the compensation below
        # depends on matching it exactly. Reading the documents here makes the
        # syntax verdict this tool's own, and leaves Argo the semantic lint it is
        # actually for.
        malformed = _unreadable_documents(staging)
        if malformed:
            print(json.dumps({
                "status": "lint-failed", "files": [],
                "lint_output": "\n".join(malformed),
                "message": f"the manifests this render would leave in {out_dir} include "
                           f"{len(malformed)} document(s) that cannot be read as Kubernetes "
                           f"objects; it was left unchanged",
            }, indent=2))
            raise SystemExit(1)

        rc, output = argo_lint_path(staging, argo_bin=args.argo_bin, resolved=resolved)
        try:
            for copy in carried:
                copy.unlink()
        except OSError as exc:
            # Inside the contract, like everything else this command can fail at.
            # The verdict is already in hand and the output has not been touched,
            # which is a third outcome a caller has to be able to tell from "the
            # linter rejected" and "the linter never answered". Escaping as a
            # traceback tells them none of that.
            # The verdict outranks the cleanup. Exit 1 means the linter rejected
            # something and exit 2 means it never answered, so exiting 2 after a
            # rejection would throw away the one thing the caller most needs and
            # contradict the body of this very report.
            verdict_known = rc != 0
            print(json.dumps({
                "status": "error", "lint": "failed" if verdict_known else "passed",
                "reason": "staging-cleanup-failed", "output_modified": False,
                "message": (
                    f"the lint finished and {out_dir} was left unchanged, but the "
                    f"staged copies in {staging} could not be removed: {exc}"
                ),
            }, indent=2))
            raise SystemExit(1 if verdict_known else 2) from exc
        carried = []
        # A file the CLI cannot parse is logged and skipped, and the run still
        # exits 0 as long as something else in the directory lints -- which is
        # always, because the gate stages its own manifests alongside. So the
        # exit status alone says "these manifests are valid" about a set that
        # contains one the linter never read, and `kubectl apply -f <dir>`
        # would choke on it. Measured on both v4.0.1 and v4.0.8: the file alone
        # exits 1, the file beside a valid one exits 0.
        if rc == 0 and 'msg="yaml file is not valid"' in output:
            rc = 1
        if rc != 0:
            print(json.dumps({
                "status": "lint-failed", "files": [],
                "lint_output": output.strip(),
                "message": f"argo lint rejected the manifests this render would leave in "
                           f"{out_dir}; it was left unchanged",
            }, indent=2))
            raise SystemExit(1)

        # Ownership, publication and the prune all happen under the same lock
        # the snapshot was taken under. Checking ownership outside it only rules
        # out a conflict that existed at the time of the check: another render
        # can create the file in the gap, and the publish would then displace it
        # without looking again. Pruning outside it lets two renders of the same
        # mission delete each other's newly published files.
        leftover_backups: list[str] = []
        try:
            preflight_writable(
                [(out_dir / path.name, path.read_text(encoding="utf-8")) for path in written]
            )
            published = _publish(written, out_dir, leftover_backups)
            # Outside the publish try below. _publish has returned, so the
            # manifests are live; an OSError from the scan reported by that
            # handler asserts a rollback that did not happen.
            try:
                _report_stale(
                    result_stale, args.output_dir, published, args.prune,
                    ARGO_EXCLUSIVE_KINDS, mission_ids=_render_scope(args.input),
                )
            except PruneIncomplete:
                # An OSError subclass, and a different phase: the scan finished
                # and the removals did not. Left to the handler that says so.
                raise
            except OSError as exc:
                print(json.dumps(
                    _scan_failure_report(exc, published, lint="passed"), indent=2
                ))
                raise SystemExit(2) from exc
        except ValueError as exc:
            print(json.dumps({
                "status": "error", "lint": "passed", "reason": "not-owned",
                "message": str(exc),
            }, indent=2))
            raise SystemExit(2) from exc
        except PublishRolledBackPartially as exc:
            print(json.dumps({
                "status": "error", "lint": "passed", "reason": "rollback-incomplete",
                "output_modified": True,
                "recovery_directory": str(exc.recovery),
                "unrestored": exc.unrestored,
                "unremoved_published": exc.unremoved,
                "message": str(exc),
            }, indent=2))
            raise SystemExit(2) from exc
        except PruneIncomplete as exc:
            # Not a publish failure and nothing was rolled back: the manifests
            # are in place and the previous generation is partly gone.
            print(json.dumps(
                {"lint": "passed", **_prune_failure_report(exc, published)}, indent=2
            ))
            raise SystemExit(2) from exc
        except OSError as exc:
            # The leftover backup belongs in this report too. _publish tries to
            # discard it on the failure path as well, and when that also fails a
            # hidden directory holding a complete copy of the previous generation
            # is left inside the caller's output -- while this message asserts the
            # directory was restored to exactly those contents. Saying both is the
            # only accurate answer.
            failed: dict[str, object] = {
                "status": "error", "lint": "passed", "reason": "publish-failed",
                "message": f"the manifests passed lint but could not be published to "
                           f"{out_dir}, which was rolled back to its previous contents: {exc}",
            }
            if leftover_backups:
                failed["backup_not_removed"] = leftover_backups
            print(json.dumps(failed, indent=2))
            raise SystemExit(2) from exc
    except ArgoLintUnavailable as exc:
        print(json.dumps({"status": "error", "lint": "unavailable", "message": str(exc)}, indent=2))
        raise SystemExit(2) from exc
    finally:
        lock_stack.close()
        shutil.rmtree(staging, ignore_errors=True)
    result: dict[str, object] = {
        "status": "ok", "files": [str(p) for p in published], "lint": "passed",
        "lint_output": output.strip(),
        **result_stale,
    }
    if staging.exists():
        # Reported rather than swallowed: the render succeeded, but a staging
        # directory left inside the operator's output is theirs to clean up and
        # they can only do that if they are told.
        result["staging_left_behind"] = str(staging)
        print(f"warning: could not remove the staging directory {staging}", file=sys.stderr)
    if leftover_backups:
        # Same reasoning as the staging directory, and the same non-failure: the
        # manifests are published and correct, so refusing here would tell a caller
        # to redo work that is done. But the previous generation is still on disk
        # inside their output root, where a recursive apply or a scanner can reach
        # it, and only they can decide whether that matters.
        result["backup_not_removed"] = leftover_backups
        for path in leftover_backups:
            print(
                f"warning: the previous manifests are still in {path}; publication "
                "succeeded and this directory is now yours to remove",
                file=sys.stderr,
            )
    print(json.dumps(result, indent=2))


def cmd_inspect(args: argparse.Namespace) -> None:
    plan = load_mission_plan(args.input)
    intents = compile_plan_to_intents(plan)
    data = [i.model_dump(mode="json") for i in intents]
    print(json.dumps(data, indent=2))


def cmd_render_kueue(args: argparse.Namespace) -> None:
    plan = load_mission_plan(args.input)
    if not args.unsafe_skip_policy:
        enforce_policy_or_raise(
            plan, engine=args.policy_engine, bundle=args.bundle, decision=args.decision
        )
    intents = compile_plan_to_intents(plan)
    out_dir = Path(args.output_dir)
    # Render everything first, then write: writing as we go leaves a partial set
    # behind when a later intent fails, and a consumer cannot tell that apart
    # from a complete render.
    planned: list[tuple[Path, str]] = []
    projections: list[dict[str, object]] = []
    dropped_total = 0
    if args.emit_priority_classes:
        wpc = render_workload_priority_classes(prefix=args.priority_class_prefix)
        planned.append(
            (out_dir / "workload-priority-classes.yaml", yaml.safe_dump_all(wpc, sort_keys=False))
        )
    for intent in intents:
        templates = render_resource_claim_templates(
            intent, namespace=args.namespace, dra_fallback=args.dra_fallback
        )
        job = render_kueue_job(
            intent,
            queue_name=args.queue,
            namespace=args.namespace,
            dra_fallback=args.dra_fallback,
            priority_class=args.priority_class,
            priority_class_prefix=args.priority_class_prefix,
        )
        # From the renderer, which selected the step, rather than recomputed by
        # name here: two steps may share a name, and this would then report
        # nothing dropped while one of them is silently absent from the Job.
        projection = kueue_step_projection(intent)
        if projection is not None:
            dropped_total += len(projection["steps_not_in_job"])
            projections.append(projection)
        safe_name = sanitize_k8s_name(intent.workflow_name)
        # Kueue admission rejects a firstAvailable claim, so the Job is admitted on
        # the exactly claim and never references the firstAvailable one. Keeping
        # both in a single file invites the reading that the admitted Job falls
        # back, and applying that file creates a claim template nothing consumes.
        # The scheduler-route claim goes to its own file, for a plain Pod or an
        # Argo render to reference.
        scheduler_route = [
            t for t in templates
            if t["metadata"].get("labels", {}).get(DRA_ROUTE_LABEL) == "scheduler"
        ]
        kueue_route = [t for t in templates if t not in scheduler_route]
        planned.append((
            out_dir / f"{safe_name}-kueue.yaml",
            yaml.safe_dump_all(kueue_route + [job], sort_keys=False),
        ))
        if scheduler_route:
            planned.append((
                out_dir / f"{safe_name}-scheduler-fallback.yaml",
                yaml.safe_dump_all(scheduler_route, sort_keys=False),
            ))

    # The same lock render-argo takes on the same directory. Without it the gate's
    # guarantee stopped at the Argo commands: this one could write into an output
    # root between the gate's snapshot and its publish, so the directory a caller
    # ends up with was not the directory that was linted. A lock held by only some
    # of a directory's writers is not a lock on the directory.
    lock_stack = contextlib.ExitStack()
    try:
        lock_stack.enter_context(_publish_lock(out_dir, args.lock_timeout, args.lock_dir))
    except PublishLockUnsupported:
        # No fcntl at all. render-kueue has no lint verdict to protect, so it keeps
        # working here rather than refusing on a platform that cannot serialise --
        # unlike the gate, whose whole claim rests on the lock.
        pass
    except PublishLockUnavailable as exc:
        print(json.dumps({
            "status": "error", "reason": "publish-lock-unavailable", "message": str(exc),
        }, indent=2))
        raise SystemExit(2) from exc
    leftover_backups: list[str] = []
    stale_result: dict[str, object] = {}
    with lock_stack:
        try:
            preflight_unique([path for path, _ in planned])
            preflight_writable(planned)
        except ValueError as exc:
            # The gate answers the same condition with a structured exit 2. Here it
            # was an uncaught ValueError: a traceback on stderr, nothing on stdout,
            # and exit 1 -- which in this CLI is what a policy denial returns, so a
            # caller keying on the exit code could not tell them apart.
            print(json.dumps({
                "status": "error", "reason": "not-owned", "message": str(exc),
            }, indent=2))
            raise SystemExit(2) from exc
        # Staged, then published as a set. Each atomic_write is atomic on its own,
        # but the set is what a caller deploys: a failure on the third of four
        # files left the directory holding some manifests from this render and
        # some from the last, with nothing saying so. The Job and the classes it
        # references are exactly such a set -- a Job from the new render beside
        # priority classes from the old one names values that have moved.
        staging = Path(tempfile.mkdtemp(
            prefix=".kueue-render-staging-", dir=_nearest_existing_ancestor(out_dir)
        ))
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            staged: list[Path] = []
            for out, text in planned:
                staged_file = staging / out.name
                atomic_write(staged_file, text)
                staged.append(staged_file)
            try:
                written = _publish(staged, out_dir, leftover_backups)
            except PublishRolledBackPartially as exc:
                print(json.dumps({
                    "status": "error", "reason": "rollback-incomplete",
                    "output_modified": True,
                    "recovery_directory": str(exc.recovery),
                    "unrestored": exc.unrestored,
                    "unremoved_published": exc.unremoved,
                    "message": str(exc),
                }, indent=2))
                raise SystemExit(2) from exc
            except OSError as exc:
                failed: dict[str, object] = {
                    "status": "error", "reason": "publish-failed",
                    "message": f"the manifests could not be published to {out_dir}, which "
                               f"was rolled back to its previous contents: {exc}",
                }
                if leftover_backups:
                    # See the gate's handler: a rollback that left a second copy of
                    # the previous generation behind must say so, or the message
                    # asserting a restore is only half the story.
                    failed["backup_not_removed"] = leftover_backups
                print(json.dumps(failed, indent=2))
                raise SystemExit(2) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if staging.exists():
            # As the gate reports it: a staging directory left inside the caller's
            # output holds a second copy of every manifest, and `kubectl create -R`
            # submits each one twice.
            staging_left = str(staging)
            print(f"warning: could not remove the staging directory {staging}", file=sys.stderr)
        else:
            staging_left = ""
        # Pruning stays inside the lock, with the publish it belongs to. The gate's
        # own note says why -- "pruning outside it lets two renders of the same
        # mission delete each other's newly published files" -- and this command
        # was doing exactly that: it released the lock after publishing and pruned
        # afterwards, so a gated render could pass its lint, publish, and have its
        # files deleted by this one, while both reported success.
        try:
            _report_stale(
                stale_result, args.output_dir, written, args.prune,
                KUEUE_EXCLUSIVE_KINDS, mission_ids=_render_scope(args.input),
                include_unmissioned=True,
            )
        except PruneIncomplete as exc:
            print(json.dumps(_prune_failure_report(exc, written), indent=2))
            raise SystemExit(2) from exc
        except OSError as exc:
            print(json.dumps(_scan_failure_report(exc, written), indent=2))
            raise SystemExit(2) from exc
    result: dict[str, object] = {"status": "ok", "files": [str(p) for p in written]}
    result.update(stale_result)
    if staging_left:
        result["staging_left_behind"] = staging_left
    # Which verb each file takes, so a caller does not have to open them to find
    # out. A file holding any document without metadata.name cannot be applied.
    apply_files: list[str] = []
    create_files: list[str] = []
    for path, text in planned:
        docs = [d for d in yaml.safe_load_all(text) if d]
        # `all()` over no documents is True, which would put a file holding nothing
        # in the group whose meaning is "every document here has a name". kubectl
        # answers `error: no objects passed to apply` for such a directory, so the
        # vacuous case belongs on the other side. A document that is not a mapping
        # has no metadata to ask about and is not applyable either.
        named = bool(docs) and all(
            isinstance(d, dict) and (d.get("metadata") or {}).get("name") for d in docs
        )
        (apply_files if named else create_files).append(str(path))
    result["apply"] = apply_files
    result["create"] = create_files
    result["deploy"] = _KUEUE_DEPLOY_NOTE
    if projections:
        # Not "ok". A caller keying on status would otherwise treat a one-step
        # admission probe as the whole service, apply it alongside the Argo
        # render, and run that step twice.
        result["status"] = "projected"
        result["complete_service"] = False
        # A Kueue Job runs one container, so a multi-step service is admitted as
        # its primary step. Reporting it here keeps "the render succeeded" from
        # reading as "the service was rendered whole".
        result["step_projection"] = projections
        print(
            f"warning: the Kueue Job is a standalone workload that runs one container, so "
            f"{dropped_total} step(s) across {len(projections)} service(s) are not in it. It "
            f"demonstrates Kueue admission for the primary step; it does not admit or gate the "
            f"Argo Workflow, which is what runs the full sequence -- applying both artifacts "
            f"runs that step twice. See 'step_projection'.",
            file=sys.stderr,
        )
    if leftover_backups:
        result["backup_not_removed"] = leftover_backups
        for backup in leftover_backups:
            print(
                f"warning: the previous manifests are still in {backup}; publication "
                "succeeded and this directory is now yours to remove",
                file=sys.stderr,
            )
    print(json.dumps(result))


def cmd_policy(args: argparse.Namespace) -> None:
    """Evaluate the OPA policy and gate on its DECISION, not just whether OPA ran.

    OPA's ``eval`` returns exit 0 whenever evaluation *succeeds*, even when the
    plan is denied (``allow: false`` / non-empty ``deny``). This command parses the
    decision and exits non-zero on denial, so it is a usable admission gate in CI
    and scripts -- not merely a "did OPA run" smoke.
    """
    plan = load_mission_plan(args.input)
    payload = plan.model_dump(mode="json")
    rc, out = eval_policy(args.bundle, payload, args.decision)
    print(out)
    # OPA unavailable (rc=2) or evaluation error (rc=1): cannot render a decision.
    if rc != 0:
        raise SystemExit(rc)
    try:
        value = json.loads(out)["result"][0]["expressions"][0]["value"]
    except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        # An undefined or unparseable result is not an allow: this command is the
        # standalone gate, so it must not report success for a decision it could
        # not read. Exit 2 keeps "no usable decision" distinct from "denied" (1).
        print(
            json.dumps({"status": "error", "reason": "undecidable", "error": str(exc)}),
            file=sys.stderr,
        )
        raise SystemExit(2)
    try:
        # Same strict parser the artifact gate uses, so the standalone command
        # cannot admit a plan the compile/render path would reject.
        typed = typed_violations_from_decision(value)
    except PolicyEngineUnavailableError as exc:
        print(
            json.dumps({"status": "error", "reason": "policy_engine_unavailable", "error": str(exc)}),
            file=sys.stderr,
        )
        raise SystemExit(2)
    if typed:
        # Report the typed violations the policy already computed (rule_id,
        # severity tier, provenance, JSON-Pointer path), not the plain-string
        # deny projection, so CI and other consumers can act on the category
        # rather than parse the message.
        print(
            json.dumps({"status": "denied", "violations": typed}),
            file=sys.stderr,
        )
        raise SystemExit(1)
    raise SystemExit(0)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except PolicyViolationError as exc:
        # Fail closed: a denied plan produces no artifact and a non-zero exit.
        # Emit the TYPED violations (rule/severity/provenance/path/message) so a
        # consumer can triage without re-parsing prose.
        print(
            json.dumps(
                {
                    "status": "denied",
                    "error": str(exc),
                    "violations": exc.violations,
                    "messages": exc.messages,
                    "hint": "re-run with --unsafe-skip-policy to bypass the gate (dev only)",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    except PolicyEngineUnavailableError as exc:
        # Fail closed on an engine that cannot render a decision (never silently
        # downgrade or skip). Distinct exit code from a policy denial.
        print(
            json.dumps(
                {
                    "status": "error",
                    "reason": "policy_engine_unavailable",
                    "error": str(exc),
                    "hint": "install opa, or pass --policy-engine=baseline (dev only)",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
