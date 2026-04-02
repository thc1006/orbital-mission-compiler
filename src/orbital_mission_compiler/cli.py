from __future__ import annotations

import argparse
import json

from .compiler import compile_file, load_mission_plan, compile_plan_to_intents
from .policy import eval_policy


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="orbital-mission-compiler")
    sub = parser.add_subparsers(dest="command", required=True)

    compile_p = sub.add_parser("compile", help="Compile mission plan to workflow payload")
    compile_p.add_argument("--input", required=True)
    compile_p.add_argument("--output", required=True)

    inspect_p = sub.add_parser("inspect", help="Inspect compiled workflow intents")
    inspect_p.add_argument("--input", required=True)

    policy_p = sub.add_parser("policy", help="Evaluate policy pack with OPA if available")
    policy_p.add_argument("--input", required=True)
    policy_p.add_argument("--bundle", default="configs/policies")
    policy_p.add_argument("--decision", default="data.orbitalmission.allow")

    return parser


def cmd_compile(args):
    payload = compile_file(args.input, args.output)
    print(json.dumps({"status": "ok", "workflows": len(payload["workflows"])}, indent=2))


def cmd_inspect(args):
    plan = load_mission_plan(args.input)
    intents = compile_plan_to_intents(plan)
    data = [i.model_dump(mode="json") for i in intents]
    print(json.dumps(data, indent=2))


def cmd_policy(args):
    plan = load_mission_plan(args.input)
    payload = plan.model_dump(mode="json")
    rc, out = eval_policy(args.bundle, payload, args.decision)
    print(out)
    raise SystemExit(rc if rc in (0, 1) else 0)


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "compile":
        cmd_compile(args)
    elif args.command == "inspect":
        cmd_inspect(args)
    elif args.command == "policy":
        cmd_policy(args)
    else:
        parser.error("unknown command")


if __name__ == "__main__":
    main()
