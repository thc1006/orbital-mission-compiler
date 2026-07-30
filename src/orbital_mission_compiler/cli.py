from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .compiler import (
    DEFAULT_POLICY_BUNDLE,
    DEFAULT_POLICY_DECISION,
    PolicyEngineUnavailableError,
    PolicyViolationError,
    compile_file,
    enforce_policy_or_raise,
    load_mission_plan,
    compile_plan_to_intents,
    render_kueue_job,
    render_resource_claim_templates,
    DRA_ROUTE_LABEL,
    preflight_unique,
    stale_rendered_artifacts,
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


_PRUNE_HELP = (
    "Delete artifacts in the output directory that an earlier render of this tool "
    "wrote and this one did not replace. Without it they are reported under "
    "'stale' and left in place: a render writes what the plan describes, it does "
    "not empty the directory, so after a plan shrinks 'kubectl apply -f <dir>' "
    "would redeploy the workloads the plan no longer asks for. Only files carrying "
    "this tool's own labels are considered."
)


def _report_stale(result: dict[str, object], output_dir: str, written: list[Path], prune: bool) -> None:
    stale = stale_rendered_artifacts(output_dir, written)
    if not stale:
        return
    if prune:
        for path in stale:
            path.unlink()
        result["pruned"] = [str(p) for p in stale]
        return
    result["stale"] = [str(p) for p in stale]
    print(
        f"warning: {len(stale)} artifact(s) in {output_dir} are left over from an "
        f"earlier render and were not replaced; applying the directory would "
        f"redeploy them. Re-run with --prune to remove them.",
        file=sys.stderr,
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
    render_p.add_argument("--namespace", default="orbital-demo")
    render_p.add_argument(
        "--service-account",
        default=None,
        help="Stamp spec.serviceAccountName on the rendered Workflow. Needed when "
        "the multi-doc --dra-fallback bundle is applied with kubectl, since "
        "'argo submit --serviceaccount' cannot be used on it (argo submit drops "
        "the ResourceClaimTemplate document).",
    )
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


def cmd_render_argo(args: argparse.Namespace) -> None:
    written = write_individual_workflows(
        args.input, args.output_dir, enforce_policy=not args.unsafe_skip_policy,
        policy_engine=args.policy_engine, bundle=args.bundle, decision=args.decision,
        dra_fallback=args.dra_fallback, namespace=args.namespace,
        service_account=args.service_account,
    )
    result: dict[str, object] = {"status": "ok", "files": [str(p) for p in written]}
    _report_stale(result, args.output_dir, written, args.prune)
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
    out_dir.mkdir(parents=True, exist_ok=True)
    # Render everything first, then write: writing as we go leaves a partial set
    # behind when a later intent fails, and a consumer cannot tell that apart
    # from a complete render.
    planned: list[tuple[Path, str]] = []
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

    preflight_unique([path for path, _ in planned])
    written = []
    for out, text in planned:
        out.write_text(text, encoding="utf-8")
        written.append(out)
    result: dict[str, object] = {"status": "ok", "files": [str(p) for p in written]}
    _report_stale(result, args.output_dir, written, args.prune)
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
