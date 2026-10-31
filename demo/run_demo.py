"""ForgeFlow end-to-end demo: three agents work concurrently on one repository.

    python demo/run_demo.py                       # embedded API, data in .forgeflow-demo/
    python demo/run_demo.py --api http://localhost:8000   # against a running server (watch the dashboard)
    python demo/run_demo.py --api ... --interactive       # approve in the web UI instead of automatically

Agent A implements authentication, Agent B optimizes database queries, Agent C adds
tests. They run at the same time in separate worktrees through the ForgeFlow tool
API. Nothing below is precomputed: diffs, semantic changes, risk scores, policy
decisions and the semantic conflict between A and B all come from the API.
"""

from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from ff_agent_sdk import ForgeFlowClient
from forgeflow_runtime import Playbook, PlaybookPlanner, run_agent

HERE = Path(__file__).parent
console = Console()
SEV = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "dark_orange", "CRITICAL": "bold red"}

AGENTS = [
    ("agent_auth", "Implement authentication",
     "Issue signed session tokens on login and require them on /orders.", "HIGH", "agent_auth.yaml"),
    ("agent_db", "Optimize database queries",
     "Remove the N+1 query in list_orders, add indexes, hide deactivated users.", "MEDIUM", "agent_db.yaml"),
    ("agent_tests", "Add test coverage",
     "Cover the HTTP layer: health, login and routing.", "LOW", "agent_tests.yaml"),
]


def shop_files() -> dict[str, str]:
    root = HERE / "shop"
    return {p.relative_to(root).as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts
            and ".pytest_cache" not in p.parts}


def unique(human: ForgeFlowClient, path: str, name: str) -> str:
    existing = {x["name"] for x in human.get(path)}
    if name not in existing:
        return name
    return f"{name}-{time.strftime('%H%M%S')}"


def section(title: str) -> None:
    console.print()
    console.print(Rule(f"[bold]{title}", align="left", style="blue"))


def show_merge(m: dict) -> None:
    ev = m["evaluation"]
    icon = {"pass": "[green]✓[/]", "fail": "[red]✗[/]", "warn": "[yellow]![/]", "skip": "[dim]-[/]"}
    console.print(Text.assemble("  ", (m["task"]["title"], "bold"), "  →  ", (m["status"], "bold")))
    for c in ev.get("checks", []):
        console.print(f"     {icon[c['status']]} {c['step']}. {c['name']:<19} {c['summary']}")


def run(human: ForgeFlowClient, make_agent_client, interactive: bool, check: bool) -> dict:
    section("1. Repository")
    repo_name = unique(human, "/repositories", "demo-shop")
    repo = human.post("/repositories", {
        "name": repo_name, "description": "Demo order-management web app",
        "initial_files": shop_files(), "settings": {"test_command": "pytest -q -p no:cacheprovider"},
    })
    console.print(f"  registered [bold]{repo['name']}[/] @ {repo['head'][:10]}  (tests: pytest on every merge)")

    section("2. Agents and tasks")
    work = []
    for base_name, title, desc, prio, playbook in AGENTS:
        name = unique(human, "/agents", base_name)
        agent = human.post("/agents", {"name": name, "model": "scripted-playbook", "kind": "scripted",
                                       "model_version": Playbook.load(HERE / "playbooks" / playbook).model_version,
                                       "description": f"Simulated agent: {title}"})
        task = human.post("/tasks", {"repository_id": repo["id"], "title": title, "description": desc,
                                     "priority": prio, "agent_id": agent["id"]})
        work.append({"agent": agent, "task": task, "playbook": playbook, "title": title})
        console.print(f"  {agent['name']:<14} → task {task['id'][:8]}  {title}  [{prio}]")

    section("3. Agents run concurrently in isolated workspaces")

    def go(w):
        pb = Playbook.load(HERE / "playbooks" / w["playbook"])
        client = make_agent_client(w["agent"]["token"])
        state = run_agent(client, w["task"]["id"], PlaybookPlanner(pb), validate=pb.validate, message=pb.message)
        return w, state

    t0 = time.monotonic()
    with ThreadPoolExecutor(len(work)) as pool:
        results = list(pool.map(go, work))
    console.print(f"  all agents finished in {time.monotonic() - t0:.1f}s")
    for w, state in results:
        w["workspace_id"] = state["workspace_id"]
        w["execution_id"] = state["execution_id"]
        tests = state.get("tests") or {}
        console.print(f"  {w['agent']['name']:<14} workspace {state['workspace_id'][:8]}  "
                      f"execution {state['execution_id'][:8]}  tests {tests.get('passed', 0)}✓ "
                      f"{tests.get('failed', 0)}✗  → {'review' if state.get('review') else 'not submitted'}")

    section("4. Semantic diffs and risk")
    for w in work:
        d = human.get(f"/workspaces/{w['workspace_id']}/diff")
        risk = human.get("/risk-assessments", workspace_id=w["workspace_id"])[0]
        lines = [Text(f"{len(d['files'])} files, +{d['additions']} -{d['deletions']}", style="dim")]
        for domain, items in d["semantic"]["domains"].items():
            lines.append(Text(domain, style="bold cyan"))
            lines += [Text(f"  - {i}") for i in items[:6]]
            if len(items) > 6:
                lines.append(Text(f"  … {len(items) - 6} more", style="dim"))
        lines.append(Text.assemble("risk ", (f"{risk['score']}/100 {risk['severity']}", SEV[risk["severity"]])))
        lines += [Text(f"  · {r}", style="dim") for r in risk["reasons"]]
        from rich.console import Group
        console.print(Panel(Group(*lines), title=f"{w['agent']['name']}: {w['title']}", title_align="left",
                            border_style="blue"))

    section("5. Cross-workspace semantic conflict check (before anything merges)")
    a = work[0]
    conflicts = human.get(f"/workspaces/{a['workspace_id']}/conflicts")["conflicts"]
    for c in conflicts:
        console.print(f"  [yellow]{c['severity']} {c['conflict_type']}[/] with {c['with']}: {c['explanation']}")
    if not conflicts:
        console.print("  none detected")

    section("6. Merge queue")
    merges = {}
    for w in work:
        merges[w["agent"]["name"]] = human.post("/merges", {"workspace_id": w["workspace_id"]})
    for w in work:
        show_merge(merges[w["agent"]["name"]])

    def approve_all(workspace_id: str) -> None:
        pending = human.get("/approvals", workspace_id=workspace_id, status="PENDING")
        if not pending:
            return
        if interactive:
            console.print(f"  [yellow]waiting for {len(pending)} approval(s) in the dashboard…[/]")
            while human.get("/approvals", workspace_id=workspace_id, status="PENDING"):
                time.sleep(2)
            return
        for p in pending:
            human.post(f"/approvals/{p['id']}/approve", {"comment": "approved by demo reviewer"})
            console.print(f"  [green]approved[/] ({p['kind']}) {p['reason']}")

    section("7. Merging: tests first, then database, then authentication")
    order = [work[2], work[1], work[0]]
    final = {}
    for w in order:
        m = human.post(f"/merges/{merges[w['agent']['name']]['id']}/evaluate")
        show_merge(m)
        for c in m["evaluation"].get("semantic_conflicts", []):
            console.print(Panel(
                f"[bold]{c['conflict_type']}[/] ({c['severity']})\n"
                f"symbols: {', '.join(c['affected_symbols'])}\nfiles:   {', '.join(c['affected_files'])}\n\n"
                f"{c['explanation']}", title="semantic conflict detected", border_style="red"))
        if m["status"] == "REQUIRES_APPROVAL":
            approve_all(w["workspace_id"])
        if m["status"] in ("READY", "REQUIRES_APPROVAL"):
            m = human.post(f"/merges/{m['id']}/execute")
        final[w["agent"]["name"]] = m
        console.print(f"  [bold]{w['title']}[/]: {m['status']}"
                      + (f" as {m['merge_commit'][:10]}" if m.get("merge_commit") else ""))

    section("8. Provenance: why does this line exist?")
    blame = human.get(f"/repositories/{repo['id']}/blame", path="app/auth.py")
    line = next(l for l in blame["lines"] if l["content"].startswith("def issue_token"))
    trace = human.get(f"/repositories/{repo['id']}/provenance", path="app/auth.py", line=line["line"])
    console.print(f"  app/auth.py:{line['line']}  [bold]{trace['content'].strip()}[/]")
    for c in trace["chain"][2:]:
        console.print(f"    ← {c['type']:<10} {c.get('label') or c.get('id')}")

    section("9. Audit")
    verify = human.get("/events/verify")
    console.print(f"  audit chain: {'valid' if verify['valid'] else 'BROKEN'} ({verify['checked']} events)")
    t = Table(box=None, header_style="bold dim")
    for col in ("agent", "task", "merge", "risk"):
        t.add_column(col)
    for w in work:
        m = final[w["agent"]["name"]]
        r = (m["evaluation"] or {}).get("risk") or {}
        t.add_row(w["agent"]["name"], w["title"], m["status"], f"{r.get('score', '-')} {r.get('severity', '')}")
    console.print(t)

    result = {"repository": repo, "work": work, "merges": final, "conflicts_before": conflicts,
              "audit": verify}
    if check:
        auth_merge = final[work[0]["agent"]["name"]]
        problems = []
        if any(m["status"] != "MERGED" for m in final.values()):
            problems.append(f"not all merged: { {k: v['status'] for k, v in final.items()} }")
        sem = auth_merge["evaluation"].get("semantic_conflicts", [])
        if not any(c["conflict_type"] == "signature_change" and "find_user" in c["affected_symbols"] for c in sem):
            problems.append(f"expected a find_user signature_change conflict, got {sem}")
        if not verify["valid"]:
            problems.append("audit chain invalid")
        if problems:
            raise SystemExit("demo check failed: " + "; ".join(problems))
        console.print("\n[bold green]demo checks passed[/]")
    return result


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--api", help="ForgeFlow API URL (default: run an embedded API)")
    ap.add_argument("--token", help="human/admin token for the API (dev auth mode needs none)")
    ap.add_argument("--data-dir", default=".forgeflow-demo", help="data directory for the embedded API")
    ap.add_argument("--interactive", action="store_true", help="wait for approvals in the dashboard")
    ap.add_argument("--check", action="store_true", help="verify the expected outcomes and exit non-zero otherwise")
    args = ap.parse_args(argv)

    with ExitStack() as stack:
        if args.api:
            human = ForgeFlowClient(args.api, token=args.token)

            def make_agent_client(token: str) -> ForgeFlowClient:
                return ForgeFlowClient(args.api, token=token)
        else:
            from fastapi.testclient import TestClient

            from forgeflow_api.config import Settings
            from forgeflow_api.main import create_app

            http = stack.enter_context(TestClient(create_app(Settings(data_dir=Path(args.data_dir)))))
            human = ForgeFlowClient(client=http)

            def make_agent_client(token: str) -> ForgeFlowClient:
                return ForgeFlowClient(client=http, token=token)

        console.print(Panel.fit("[bold]ForgeFlow demo[/]: three agents, one repository, one merge gate",
                                border_style="green"))
        run(human, make_agent_client, args.interactive, args.check)
    return 0


if __name__ == "__main__":
    sys.exit(main())
