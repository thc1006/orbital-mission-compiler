from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

from .compiler import (
    PolicyViolationError,
    compile_file,
    enforce_policy_or_raise,
    load_mission_plan,
    compile_plan_to_intents,
    render_kueue_job,
    render_resource_claim_templates,
    write_individual_workflows,
    sanitize_k8s_name,
)
from .policy import eval_policy

_UNSAFE_SKIP_POLICY_HELP = (
    "DEV ONLY. Skip the policy admission gate and emit artifacts even for a plan the "
    "policy layer would deny. By DEFAULT the compiler is fail-closed: it runs the policy "
    "layer (in-process OPA-equivalent baseline) before rendering and produces no artifact "
    "for a denied plan. Bypassing the gate forfeits the pre-uplink guarantee."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orbital-mission-compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser("compile", help="Compile mission plan to workflow payload")
    compile_p.add_argument("--input", required=True)
    compile_p.add_argument("--output", required=True)
    compile_p.add_argument("--unsafe-skip-policy", action="store_true", help=_UNSAFE_SKIP_POLICY_HELP)
    compile_p.set_defaults(func=cmd_compile)

    render_p = sub.add_parser("render-argo", help="Render individual Argo Workflow manifests")
    render_p.add_argument("--input", required=True)
    render_p.add_argument("--output-dir", required=True)
    render_p.add_argument("--unsafe-skip-policy", action="store_true", help=_UNSAFE_SKIP_POLICY_HELP)
    render_p.set_defaults(func=cmd_render_argo)

    inspect_p = sub.add_parser("inspect", help="Inspect compiled workflow intents")
    inspect_p.add_argument("--input", required=True)
    inspect_p.set_defaults(func=cmd_inspect)

    kueue_p = sub.add_parser("render-kueue", help="Render Kueue-compatible Job manifests")
    kueue_p.add_argument("--input", required=True)
    kueue_p.add_argument("--output-dir", required=True)
    kueue_p.add_argument("--queue", default="orbital-demo-local")
    kueue_p.add_argument("--namespace", default="orbital-demo")
    kueue_p.add_argument(
        "--dra-fallback",
        action="store_true",
        help="Render a DRA firstAvailable claim (scheduler-level accelerator->CPU "
        "fallback) for steps that declare a driver-backed fallback_resource_class, "
        "instead of the runtime env-var switch. Requires the CPU DRA driver; the "
        "resulting claim is not Kueue quota-counted (only 'exactly' claims are).",
    )
    kueue_p.add_argument("--unsafe-skip-policy", action="store_true", help=_UNSAFE_SKIP_POLICY_HELP)
    kueue_p.set_defaults(func=cmd_render_kueue)

    policy_p = sub.add_parser("policy", help="Evaluate policy pack with OPA if available")
    policy_p.add_argument("--input", required=True)
    policy_p.add_argument("--bundle", default="configs/policies")
    policy_p.add_argument("--decision", default="data.orbitalmission")
    policy_p.set_defaults(func=cmd_policy)

    return parser


def cmd_compile(args: argparse.Namespace) -> None:
    payload = compile_file(args.input, args.output, enforce_policy=not args.unsafe_skip_policy)
    print(json.dumps({"status": "ok", "workflows": len(payload["workflows"])}, indent=2))


def cmd_render_argo(args: argparse.Namespace) -> None:
    written = write_individual_workflows(
        args.input, args.output_dir, enforce_policy=not args.unsafe_skip_policy
    )
    print(json.dumps({"status": "ok", "files": [str(p) for p in written]}, indent=2))


def cmd_inspect(args: argparse.Namespace) -> None:
    plan = load_mission_plan(args.input)
    intents = compile_plan_to_intents(plan)
    data = [i.model_dump(mode="json") for i in intents]
    print(json.dumps(data, indent=2))


def cmd_render_kueue(args: argparse.Namespace) -> None:
    plan = load_mission_plan(args.input)
    if not args.unsafe_skip_policy:
        enforce_policy_or_raise(plan)
    intents = compile_plan_to_intents(plan)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for intent in intents:
        templates = render_resource_claim_templates(
            intent, namespace=args.namespace, dra_fallback=args.dra_fallback
        )
        job = render_kueue_job(
            intent,
            queue_name=args.queue,
            namespace=args.namespace,
            dra_fallback=args.dra_fallback,
        )
        docs = templates + [job]
        safe_name = sanitize_k8s_name(intent.workflow_name)
        out = out_dir / f"{safe_name}-kueue.yaml"
        out.write_text(yaml.safe_dump_all(docs, sort_keys=False), encoding="utf-8")
        written.append(str(out))
    print(json.dumps({"status": "ok", "files": written}))


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
    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
        # Non-decision query (custom --decision) — nothing to gate on; report success.
        raise SystemExit(0)
    denied = False
    if isinstance(value, dict):
        if "allow" in value:
            denied = not bool(value["allow"])
        elif "deny" in value:
            denied = len(value.get("deny") or []) > 0
    elif isinstance(value, bool):
        denied = not value
    if denied:
        deny = value.get("deny", []) if isinstance(value, dict) else []
        print(
            json.dumps({"status": "denied", "violations": deny}),
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
        print(
            json.dumps(
                {
                    "status": "denied",
                    "error": str(exc),
                    "violations": exc.violations,
                    "hint": "re-run with --unsafe-skip-policy to bypass the gate (dev only)",
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
