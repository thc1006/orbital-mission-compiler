from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from .compiler import (
    compile_file,
    load_mission_plan,
    compile_plan_to_intents,
    render_kueue_job,
    write_individual_workflows,
    sanitize_k8s_name,
)
from .policy import eval_policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orbital-mission-compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser("compile", help="Compile mission plan to workflow payload")
    compile_p.add_argument("--input", required=True)
    compile_p.add_argument("--output", required=True)
    compile_p.set_defaults(func=cmd_compile)

    render_p = sub.add_parser("render-argo", help="Render individual Argo Workflow manifests")
    render_p.add_argument("--input", required=True)
    render_p.add_argument("--output-dir", required=True)
    render_p.set_defaults(func=cmd_render_argo)

    inspect_p = sub.add_parser("inspect", help="Inspect compiled workflow intents")
    inspect_p.add_argument("--input", required=True)
    inspect_p.set_defaults(func=cmd_inspect)

    kueue_p = sub.add_parser("render-kueue", help="Render Kueue-compatible Job manifests")
    kueue_p.add_argument("--input", required=True)
    kueue_p.add_argument("--output-dir", required=True)
    kueue_p.add_argument("--queue", default="orbital-demo-local")
    kueue_p.add_argument("--namespace", default="orbital-demo")
    kueue_p.set_defaults(func=cmd_render_kueue)

    policy_p = sub.add_parser("policy", help="Evaluate policy pack with OPA if available")
    policy_p.add_argument("--input", required=True)
    policy_p.add_argument("--bundle", default="configs/policies")
    policy_p.add_argument("--decision", default="data.orbitalmission")
    policy_p.set_defaults(func=cmd_policy)

    return parser


def cmd_compile(args):
    payload = compile_file(args.input, args.output)
    print(json.dumps({"status": "ok", "workflows": len(payload["workflows"])}, indent=2))


def cmd_render_argo(args):
    written = write_individual_workflows(args.input, args.output_dir)
    print(json.dumps({"status": "ok", "files": [str(p) for p in written]}, indent=2))


def cmd_inspect(args):
    plan = load_mission_plan(args.input)
    intents = compile_plan_to_intents(plan)
    data = [i.model_dump(mode="json") for i in intents]
    print(json.dumps(data, indent=2))


def cmd_render_kueue(args):
    plan = load_mission_plan(args.input)
    intents = compile_plan_to_intents(plan)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for intent in intents:
        job = render_kueue_job(intent, queue_name=args.queue, namespace=args.namespace)
        safe_name = sanitize_k8s_name(intent.workflow_name)
        out = out_dir / f"{safe_name}-kueue.yaml"
        out.write_text(yaml.safe_dump(job, sort_keys=False), encoding="utf-8")
        written.append(str(out))
    print(json.dumps({"status": "ok", "files": written}))


def cmd_policy(args):
    plan = load_mission_plan(args.input)
    payload = plan.model_dump(mode="json")
    rc, out = eval_policy(args.bundle, payload, args.decision)
    print(out)
    raise SystemExit(rc if rc in (0, 1, 2) else 0)


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
