"""forgeflow-agent: run one agent on one task against a ForgeFlow API."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys

from ff_agent_sdk import ForgeFlowClient

from .agent import Playbook, PlaybookPlanner, run_agent


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="forgeflow-agent", description=__doc__)
    ap.add_argument("--api", default=os.environ.get("FORGEFLOW_API_URL", "http://localhost:8000"))
    ap.add_argument("--token", default=os.environ.get("FORGEFLOW_AGENT_TOKEN"), help="agent token (ffa_...)")
    ap.add_argument("--task", required=True)
    ap.add_argument("--workspace")
    ap.add_argument("--playbook", help="YAML playbook (scripted agent)")
    ap.add_argument("--claude", action="store_true", help="use the Claude planner (needs the anthropic package)")
    ap.add_argument("--model", default=None)
    ap.add_argument("--validate", help="validation command, e.g. 'pytest -q'")
    ap.add_argument("--no-submit", action="store_true")
    args = ap.parse_args(argv)
    if not args.token:
        ap.error("an agent token is required (--token or FORGEFLOW_AGENT_TOKEN)")
    if bool(args.playbook) == bool(args.claude):
        ap.error("choose exactly one of --playbook or --claude")

    client = ForgeFlowClient(args.api, token=args.token)
    validate = shlex.split(args.validate) if args.validate else None
    if args.playbook:
        pb = Playbook.load(args.playbook)
        planner = PlaybookPlanner(pb)
        validate = validate or pb.validate
        message = pb.message
    else:
        from .claude import DEFAULT_MODEL, ClaudePlanner

        planner = ClaudePlanner(model=args.model or DEFAULT_MODEL)
        message = None
    state = run_agent(client, args.task, planner, workspace_id=args.workspace, validate=validate,
                      submit=not args.no_submit, message=message)
    out = {"execution_id": state["execution_id"], "workspace_id": state["workspace_id"],
           "tests": state.get("tests"), "review_id": (state.get("review") or {}).get("id"),
           "trace": state.get("trace")}
    json.dump(out, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
