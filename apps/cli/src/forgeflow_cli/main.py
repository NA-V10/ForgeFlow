"""forge: the ForgeFlow command line.

Talks to the ForgeFlow API (``FORGEFLOW_API_URL``, default http://localhost:8000).
Every command accepts ``--json`` for machine-readable output.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console, Group
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from ff_agent_sdk import ForgeFlowClient, ForgeFlowError

app = typer.Typer(help="ForgeFlow: agent-native version control and delivery.", no_args_is_help=True,
                  rich_markup_mode="rich", pretty_exceptions_enable=False)
repo_app = typer.Typer(help="Repositories", no_args_is_help=True)
agent_app = typer.Typer(help="Agents", no_args_is_help=True)
task_app = typer.Typer(help="Tasks", no_args_is_help=True)
ws_app = typer.Typer(help="Workspaces", no_args_is_help=True)
cp_app = typer.Typer(help="Checkpoints", no_args_is_help=True)
policy_app = typer.Typer(help="Policies", no_args_is_help=True)
app.add_typer(repo_app, name="repo")
app.add_typer(agent_app, name="agent")
app.add_typer(task_app, name="task")
app.add_typer(ws_app, name="workspace")
app.add_typer(cp_app, name="checkpoint")
app.add_typer(policy_app, name="policy")

console = Console()
err = Console(stderr=True)
JsonOpt = Annotated[bool, typer.Option("--json", help="Output JSON")]

SEVERITY_STYLE = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "dark_orange", "CRITICAL": "bold red"}
STATUS_STYLE = {
    "PENDING": "grey62", "RUNNING": "cyan", "BLOCKED": "red", "REVIEW": "magenta", "COMPLETED": "green",
    "FAILED": "red", "CANCELLED": "grey50", "CREATED": "grey62", "CHECKPOINTED": "blue", "MERGED": "green",
    "ABANDONED": "grey50", "SUCCESS": "green", "READY": "bold green", "REQUIRES_APPROVAL": "yellow",
    "CONFLICT": "bold red", "QUEUED": "grey62", "APPROVED": "green", "REJECTED": "red", "STALE": "grey50",
    "ROLLED_BACK": "dark_orange", "ACTIVE": "cyan", "IDLE": "grey62", "OPEN": "magenta",
}


# ------------------------------------------------------------------- config
def config_path() -> Path:
    base = Path(os.environ.get("FORGEFLOW_CONFIG_DIR", Path.home() / ".forgeflow"))
    return base / "config.json"


def load_config() -> dict[str, Any]:
    p = config_path()
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def save_config(cfg: dict[str, Any]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


_client_override: ForgeFlowClient | None = None


def client(token: str | None = None) -> ForgeFlowClient:
    if _client_override is not None and token is None:
        return _client_override
    cfg = load_config()
    url = os.environ.get("FORGEFLOW_API_URL") or cfg.get("api_url") or "http://localhost:8000"
    tok = token or os.environ.get("FORGEFLOW_TOKEN") or cfg.get("token")
    if _client_override is not None:
        return ForgeFlowClient(client=_client_override.http, token=tok)
    return ForgeFlowClient(url, token=tok)


def emit(data: Any, as_json: bool, render) -> None:
    if as_json:
        sys.stdout.write(json.dumps(data, indent=2, default=str) + "\n")
    else:
        render(data)


def st(value: str | None) -> Text:
    return Text(value or "-", style=STATUS_STYLE.get(value or "", ""))


def short(value: str | None, n: int = 8) -> str:
    return (value or "-")[:n]


def call(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except ForgeFlowError as exc:
        err.print(f"[bold red]error[/] [{exc.status} {exc.code}] {exc.message}")
        if exc.details.get("reasons"):
            for r in exc.details["reasons"]:
                err.print(f"  • {r}")
        raise typer.Exit(1) from exc
    except OSError as exc:
        err.print(f"[bold red]error[/] cannot reach the ForgeFlow API: {exc}")
        raise typer.Exit(2) from exc


def table(title: str, columns: list[str]) -> Table:
    t = Table(title=title, title_justify="left", title_style="bold", header_style="bold dim", box=None,
              pad_edge=False, show_edge=False)
    for c in columns:
        t.add_column(c)
    return t


# --------------------------------------------------------------------- init
@app.command()
def init(api_url: Annotated[str, typer.Option(help="ForgeFlow API URL")] = "http://localhost:8000",
         token: Annotated[str | None, typer.Option(help="Admin/human token (omit in dev auth mode)")] = None,
         as_json: JsonOpt = False):
    """Configure the CLI and check connectivity."""
    cfg = load_config()
    cfg["api_url"] = api_url
    if token:
        cfg["token"] = token
    save_config(cfg)
    settings = call(lambda: ForgeFlowClient(api_url, token=cfg.get("token")).get("/settings"))

    def render(s):
        console.print(Panel.fit(
            f"[bold]ForgeFlow[/] connected at {api_url}\n"
            f"principal  {s['principal']['type']}:{s['principal']['name']}\n"
            f"database   {s['database']}   events {s['event_bus']}   artifacts {s['artifact_store']}\n"
            f"sandbox    {s['sandbox']['sandbox']} (network: {s['sandbox']['network_policy']}, "
            f"{'enforced' if s['sandbox']['guarantees'].get('network_enforced') else 'not enforced'})\n"
            f"config     {config_path()}", border_style="green"))
    emit(settings, as_json, render)


# -------------------------------------------------------------- repositories
@repo_app.command("create")
def repo_create(name: str,
                source: Annotated[str | None, typer.Option("--from", help="Import an existing Git repo (path/URL)")] = None,
                description: str = "",
                test_command: Annotated[str | None, typer.Option(help="Command run on the merged tree")] = None,
                require_tests: bool = False, as_json: JsonOpt = False):
    """Register a repository (new, or imported with --from)."""
    settings: dict[str, Any] = {}
    if test_command:
        settings["test_command"] = test_command
    if require_tests:
        settings["require_tests"] = True
    if source and Path(source).exists():
        source = str(Path(source).resolve())
    r = call(client().post, "/repositories", {"name": name, "description": description, "source_url": source,
                                              "settings": settings})
    emit(r, as_json, lambda r: console.print(
        f"[green]✓[/] repository [bold]{r['name']}[/] ({short(r['id'])}) on {r['default_branch']} @ {short(r['head'], 10)}"))


@repo_app.command("list")
def repo_list(as_json: JsonOpt = False):
    rows = call(client().get, "/repositories")

    def render(rows):
        t = table("Repositories", ["ID", "NAME", "BRANCH", "HEAD", "TEST COMMAND"])
        for r in rows:
            t.add_row(short(r["id"]), r["name"], r["default_branch"], short(r["head"], 10),
                      r["settings"].get("test_command", "-"))
        console.print(t)
    emit(rows, as_json, render)


# -------------------------------------------------------------------- agents
@agent_app.command("create")
def agent_create(name: str, model: str = "unspecified", model_version: str | None = None,
                 kind: str = "external", provider: str | None = None, description: str = "",
                 as_json: JsonOpt = False):
    """Register an agent. The token is stored in the local CLI config."""
    a = call(client().post, "/agents", {"name": name, "model": model, "model_version": model_version,
                                        "kind": kind, "provider": provider, "description": description})
    cfg = load_config()
    cfg.setdefault("agent_tokens", {})[a["name"]] = a["token"]
    save_config(cfg)

    def render(a):
        console.print(f"[green]✓[/] agent [bold]{a['name']}[/] ({short(a['id'])}) model {a['model']}")
        console.print(f"  token saved to {config_path()} (shown once): [dim]{a['token'][:12]}…[/]")
    emit(a, as_json, render)


@agent_app.command("list")
def agent_list(as_json: JsonOpt = False):
    rows = call(client().get, "/agents")

    def render(rows):
        t = table("Agents", ["ID", "NAME", "KIND", "MODEL", "STATUS"])
        for a in rows:
            t.add_row(short(a["id"]), a["name"], a["kind"], f"{a['model']} {a['model_version'] or ''}".strip(),
                      st(a["status"]))
        console.print(t)
    emit(rows, as_json, render)


@agent_app.command("start")
def agent_start(agent: str, task: Annotated[str, typer.Option("--task", help="Task id")],
                playbook: Annotated[Path | None, typer.Option(help="YAML playbook (scripted agent)")] = None,
                claude: Annotated[bool, typer.Option("--claude", help="Use the Claude planner")] = False,
                model: str | None = None, workspace: str | None = None,
                validate: Annotated[str | None, typer.Option(help="Validation command")] = None,
                submit: bool = True, as_json: JsonOpt = False):
    """Run an agent on a task through the ForgeFlow tool API."""
    import shlex

    from forgeflow_runtime import Playbook, PlaybookPlanner, run_agent

    token = load_config().get("agent_tokens", {}).get(agent) or os.environ.get("FORGEFLOW_AGENT_TOKEN")
    if not token:
        err.print(f"[red]no token for agent {agent}[/]; create it with `forge agent create` or set FORGEFLOW_AGENT_TOKEN")
        raise typer.Exit(1)
    if bool(playbook) == claude:
        err.print("[red]choose exactly one of --playbook or --claude[/]")
        raise typer.Exit(1)
    if playbook:
        pb = Playbook.load(playbook)
        planner, message, checks = PlaybookPlanner(pb), pb.message, pb.validate
    else:
        from forgeflow_runtime.claude import DEFAULT_MODEL, ClaudePlanner

        planner, message, checks = ClaudePlanner(model=model or DEFAULT_MODEL), None, None
    checks = shlex.split(validate) if validate else checks
    with console.status(f"[cyan]{agent}[/] working on task {short(task)}…"):
        state = call(run_agent, client(token), task, planner, workspace_id=workspace, validate=checks,
                     submit=submit, message=message)
    out = {"execution_id": state["execution_id"], "workspace_id": state["workspace_id"], "tests": state.get("tests"),
           "review_id": (state.get("review") or {}).get("id"), "trace": state.get("trace")}

    def render(o):
        tests = o["tests"]
        console.print(f"[green]✓[/] execution {short(o['execution_id'])} in workspace {short(o['workspace_id'])}")
        console.print(f"  steps: {' → '.join(o['trace'])}")
        if tests:
            console.print(f"  tests: [green]{tests['passed']} passed[/], "
                          f"[{'red' if tests['failed'] else 'dim'}]{tests['failed']} failed[/]")
        if o["review_id"]:
            console.print(f"  submitted for review {short(o['review_id'])}")
    emit(out, as_json, render)


# --------------------------------------------------------------------- tasks
@task_app.command("create")
def task_create(title: str, repo: Annotated[str, typer.Option("--repo", "-r", help="Repository id or name")],
                description: str = "", agent: str | None = None, priority: str = "MEDIUM",
                as_json: JsonOpt = False):
    t = call(client().post, "/tasks", {"repository_id": repo, "title": title, "description": description,
                                       "agent_id": agent, "priority": priority})
    emit(t, as_json, lambda t: console.print(
        f"[green]✓[/] task [bold]{short(t['id'])}[/] {t['title']} "
        f"(base {short(t['base_commit'], 10)}{', agent ' + t['agent']['name'] if t['agent'] else ''})"))


@task_app.command("list")
def task_list(repo: Annotated[str | None, typer.Option("--repo", "-r")] = None, status: str | None = None,
              as_json: JsonOpt = False):
    rows = call(client().get, "/tasks", repository_id=repo, status=status)

    def render(rows):
        t = table("Tasks", ["ID", "TITLE", "STATUS", "PRIORITY", "AGENT", "CREATED"])
        for r in rows:
            t.add_row(short(r["id"]), r["title"], st(r["status"]), r["priority"],
                      r["agent"]["name"] if r["agent"] else "-", r["created_at"][:19].replace("T", " "))
        console.print(t)
    emit(rows, as_json, render)


@task_app.command("show")
def task_show(task_id: str, as_json: JsonOpt = False):
    t = call(client().get, f"/tasks/{task_id}")

    def render(t):
        head = Text.assemble((t["title"], "bold"), "  ", st(t["status"]), f"  {t['priority']}")
        lines = [head, Text(f"id {t['id']}   base {short(t['base_commit'], 10)}   agent "
                            f"{t['agent']['name'] if t['agent'] else '-'}", style="dim")]
        if t["description"]:
            lines.append(Text(t["description"]))
        console.print(Panel(Group(*lines), border_style="blue"))
        tree = Tree("[bold]provenance")
        for w in t["workspaces"]:
            wn = tree.add(Text.assemble("workspace ", (short(w["id"]), "bold"), " ", st(w["status"]),
                                        f"  {w['branch']}"))
            for e in [e for e in t["executions"] if e["workspace_id"] == w["id"]]:
                tests = (e["summary"] or {}).get("tests")
                wn.add(Text.assemble("execution ", (short(e["id"]), "bold"), " ", st(e["status"]),
                                     f"  {e['model']}  {len((e['summary'] or {}).get('files', []))} files"
                                     + (f"  tests {tests['passed']}✓ {tests['failed']}✗" if tests else "")))
            for c in [c for c in t["checkpoints"] if c["workspace_id"] == w["id"]]:
                wn.add(f"checkpoint {short(c['id'])} {short(c['commit_sha'], 10)}  {c['message']}")
            for m in [m for m in t["merges"] if m["workspace"]["id"] == w["id"]]:
                wn.add(Text.assemble("merge ", (short(m["id"]), "bold"), " ", st(m["status"])))
        console.print(tree)
        if t["risk"]:
            r = t["risk"]
            console.print(Text.assemble("risk ", (f"{r['score']}/100 {r['severity']}",
                                                  SEVERITY_STYLE[r["severity"]])))
        for a in t["approvals"]:
            console.print(Text.assemble("approval ", (short(a["id"]), "bold"), " ", st(a["status"]),
                                        f"  {a['reason']}"))
    emit(t, as_json, render)


# ---------------------------------------------------------------- workspaces
@ws_app.command("create")
def ws_create(task: Annotated[str, typer.Option("--task", "-t")], agent: str | None = None, as_json: JsonOpt = False):
    w = call(client().post, "/workspaces", {"task_id": task, "agent_id": agent})
    emit(w, as_json, lambda w: console.print(
        f"[green]✓[/] workspace [bold]{short(w['id'])}[/] on {w['branch']} @ {short(w['base_commit'], 10)}\n"
        f"  {w.get('path') or ''}"))


@ws_app.command("list")
def ws_list(repo: Annotated[str | None, typer.Option("--repo", "-r")] = None, status: str | None = None,
            as_json: JsonOpt = False):
    rows = call(client().get, "/workspaces", repository_id=repo, status=status)

    def render(rows):
        t = table("Workspaces", ["ID", "TASK", "AGENT", "STATUS", "BASE", "HEAD"])
        for w in rows:
            t.add_row(short(w["id"]), w["task"]["title"], w["agent"]["name"] if w["agent"] else "-", st(w["status"]),
                      short(w["base_commit"], 10), short(w["current_commit"], 10))
        console.print(t)
    emit(rows, as_json, render)


@ws_app.command("show")
def ws_show(workspace: str, as_json: JsonOpt = False):
    w = call(client().get, f"/workspaces/{workspace}")
    emit(w, as_json, lambda w: console.print(Panel(
        f"[bold]{w['task']['title']}[/]  {w['status']}\n"
        f"id        {w['id']}\nagent     {w['agent']['name'] if w['agent'] else '-'}\nbranch    {w['branch']}\n"
        f"base      {w['base_commit']}\nhead      {w['current_commit']}\npath      {w.get('path') or '(hidden)'}\n"
        f"perms     {json.dumps(w['permissions'])}", border_style="blue")))


# ---------------------------------------------------------------------- diff
def render_semantic(sem: dict[str, Any]) -> None:
    console.print("[bold]Semantic changes:[/]")
    for domain, items in sem["domains"].items():
        console.print(f"\n[bold cyan]{domain}[/]")
        for i in items:
            console.print(f"  - {i}")


@app.command()
def diff(workspace: str, semantic: Annotated[bool, typer.Option("--semantic", help="Show the AST-level diff")] = False,
         committed: Annotated[bool, typer.Option(help="Only committed changes")] = False, as_json: JsonOpt = False):
    """Show the workspace diff against its base commit."""
    d = call(client().get, f"/workspaces/{workspace}/diff", semantic=str(semantic).lower(),
             uncommitted=str(not committed).lower())

    def render(d):
        console.print(f"[dim]{short(d['base'], 10)} → {short(d['head'], 10)}"
                      f"{' (includes uncommitted)' if d['includes_uncommitted'] else ''}[/]")
        for f in d["files"]:
            console.print(f"  {f['status']} {f['path']}  [green]+{f['additions']}[/] [red]-{f['deletions']}[/]")
        console.print(f"  [bold]{len(d['files'])} files[/], [green]+{d['additions']}[/] [red]-{d['deletions']}[/]\n")
        if semantic and d["semantic"]:
            render_semantic(d["semantic"])
        else:
            console.print(Syntax(d["patch"] or "(no changes)", "diff", theme="ansi_dark", word_wrap=False))
    emit(d, as_json, render)


# ---------------------------------------------------------------- checkpoints
@cp_app.command("create")
def cp_create(workspace: str, message: Annotated[str | None, typer.Option("-m", "--message")] = None,
              as_json: JsonOpt = False):
    c = call(client().post, f"/workspaces/{workspace}/checkpoints", {"message": message})
    emit(c, as_json, lambda c: console.print(
        f"[green]✓[/] checkpoint [bold]{short(c['id'])}[/] {short(c['commit_sha'], 10)} — {c['message']} "
        f"({c['filesystem'].get('changed')} files)"))


@cp_app.command("list")
def cp_list(workspace: str, as_json: JsonOpt = False):
    rows = call(client().get, "/checkpoints", workspace_id=workspace)

    def render(rows):
        t = table("Checkpoints", ["ID", "COMMIT", "MESSAGE", "FILES", "CREATED"])
        for c in rows:
            t.add_row(short(c["id"]), short(c["commit_sha"], 10), c["message"],
                      str(c["filesystem"].get("changed", "-")), c["created_at"][:19].replace("T", " "))
        console.print(t)
    emit(rows, as_json, render)


@cp_app.command("restore")
def cp_restore(checkpoint: str, as_json: JsonOpt = False):
    w = call(client().post, f"/checkpoints/{checkpoint}/restore")
    emit(w, as_json, lambda w: console.print(
        f"[green]✓[/] workspace {short(w['id'])} restored to {short(w['current_commit'], 10)}"))


# ------------------------------------------------------- review & approvals
@app.command()
def review(workspace: str, as_json: JsonOpt = False):
    """Submit a workspace for review: semantic diff, risk, policy, approvals."""
    r = call(client().post, f"/workspaces/{workspace}/review")
    approvals = call(client().get, "/approvals", workspace_id=workspace, status="PENDING")

    def render(r):
        stats = r["diff_stats"]
        console.print(f"[green]✓[/] review {short(r['id'])}: {stats['files']} files "
                      f"[green]+{stats['additions']}[/] [red]-{stats['deletions']}[/]")
        render_semantic(r["semantic_diff"])
        console.print(f"\npolicy: {r['policy']['effect']}")
        for a in approvals:
            console.print(f"  [yellow]approval required[/] {short(a['id'])}: {a['reason']}")
    emit({**r, "pending_approvals": approvals}, as_json, render)


@app.command()
def approvals(status: str = "PENDING", as_json: JsonOpt = False):
    """List approval requests."""
    rows = call(client().get, "/approvals", status=status)

    def render(rows):
        t = table("Approvals", ["ID", "TASK", "KIND", "STATUS", "REASON"])
        for a in rows:
            t.add_row(short(a["id"]), a["task"]["title"], a["kind"], st(a["status"]), a["reason"])
        console.print(t)
    emit(rows, as_json, render)


def _decide(approval_id: str, approve: bool, comment: str | None, as_json: bool):
    a = call(client().post, f"/approvals/{approval_id}/{'approve' if approve else 'reject'}", {"comment": comment})
    emit(a, as_json, lambda a: console.print(
        f"[{'green' if approve else 'red'}]{'✓ approved' if approve else '✗ rejected'}[/] {short(a['id'])}: {a['reason']}"))


@app.command()
def approve(approval_id: str, comment: Annotated[str | None, typer.Option("-m", "--comment")] = None,
            as_json: JsonOpt = False):
    """Approve a pending approval request (human principals only)."""
    _decide(approval_id, True, comment, as_json)


@app.command()
def reject(approval_id: str, comment: Annotated[str | None, typer.Option("-m", "--comment")] = None,
           as_json: JsonOpt = False):
    """Reject a pending approval request (human principals only)."""
    _decide(approval_id, False, comment, as_json)


@app.command()
def risk(workspace: str, as_json: JsonOpt = False):
    """Compute the deterministic risk score for a workspace."""
    r = call(client().post, f"/workspaces/{workspace}/risk")

    def render(r):
        style = SEVERITY_STYLE[r["severity"]]
        lines = [Text(f"{r['score']} / 100", style="bold"), Text(r["severity"], style=style), Text(""), Text("Reasons:")]
        lines += [Text(f"- {x}") for x in r["reasons"]] or [Text("- no risk signals", style="dim")]
        console.print(Panel(Group(*lines), title="risk", border_style=style.split()[-1]))
    emit(r, as_json, render)


# ------------------------------------------------------------------ policies
@policy_app.command("check")
def policy_check(action: str, path: Annotated[list[str] | None, typer.Option("--path", "-p")] = None,
                 repo: Annotated[str | None, typer.Option("--repo", "-r")] = None, agent: str | None = None,
                 command: str | None = None, risk_score: int | None = None, as_json: JsonOpt = False):
    """Evaluate an action against the effective policies."""
    d = call(client().post, "/policies/check", {"action": action, "paths": path or [], "repository_id": repo,
                                                 "agent": agent, "command": command, "risk_score": risk_score})

    def render(d):
        style = {"ALLOW": "green", "DENY": "bold red", "REQUIRE_APPROVAL": "yellow"}[d["effect"]]
        console.print(Text(d["effect"], style=style))
        for r in d["reasons"]:
            console.print(f"  - {r}")
    emit(d, as_json, render)


@policy_app.command("show")
def policy_show(repo: Annotated[str | None, typer.Option("--repo", "-r")] = None, as_json: JsonOpt = False):
    d = call(client().get, "/policies/effective", repository_id=repo)

    def render(d):
        t = table(f"Effective policies (default: {d['default']})", ["NAME", "EFFECT", "ACTIONS", "PATHS", "RISK"])
        for p in d["policies"]:
            t.add_row(p["name"], p["effect"], ", ".join(p["actions"]) or "*", ", ".join(p["paths"]) or "*",
                      str(p["min_risk"] or p["severity"] or "-"))
        console.print(t)
    emit(d, as_json, render)


@policy_app.command("set")
def policy_set(file: Path, scope: Annotated[str, typer.Option(help="'global' or a repository id/name")] = "global",
               as_json: JsonOpt = False):
    """Publish a new version of a YAML policy document."""
    p = call(client().request, "PUT", f"/policies/{scope}", json={"document": file.read_text(encoding="utf-8")})
    emit(p, as_json, lambda p: console.print(f"[green]✓[/] policy {p['scope']} v{p['version']} published"))


# --------------------------------------------------------------------- merge
def render_merge(m: dict[str, Any]) -> None:
    ev = m["evaluation"]
    console.print(Text.assemble("merge ", (short(m["id"]), "bold"), "  ", st(m["status"]),
                                f"  {m['task']['title']} → {m['target_branch']}"))
    icons = {"pass": "[green]✓[/]", "fail": "[red]✗[/]", "warn": "[yellow]![/]", "skip": "[dim]–[/]"}
    for c in ev.get("checks", []):
        console.print(f"  {icons[c['status']]} {c['step']}. {c['name']:<20} {c['summary']}")
    for c in ev.get("semantic_conflicts", []):
        console.print(f"  [red]semantic conflict[/] {c['severity']} {c['conflict_type']}: {c['explanation']}")
    for c in ev.get("advisory_conflicts", []):
        console.print(f"  [yellow]potential conflict[/] with {c['with']}: {c['explanation']}")
    if ev.get("reasons"):
        console.print("[bold]Reasons:[/]")
        for r in ev["reasons"]:
            console.print(f"  - {r}")
    if m.get("merge_commit"):
        console.print(f"[green]merged as {m['merge_commit'][:10]}[/]")


@app.command()
def merge(workspace: str, dry_run: Annotated[bool, typer.Option("--dry-run", help="Evaluate only")] = False,
          as_json: JsonOpt = False):
    """Run the merge gate and merge the workspace if it is READY."""
    with console.status("running merge gate (base, conflicts, semantics, policy, risk, tests, approvals)…"):
        m = call(client().post, "/merges", {"workspace_id": workspace, "execute": not dry_run})
    emit(m, as_json, render_merge)
    if m["status"] not in ("MERGED", "READY"):
        raise typer.Exit(3)


@app.command("queue")
def merge_queue(repo: Annotated[str | None, typer.Option("--repo", "-r")] = None, as_json: JsonOpt = False):
    """Show the merge queue."""
    rows = call(client().get, "/merges", repository_id=repo)

    def render(rows):
        t = table("Merge queue", ["#", "ID", "TASK", "STATUS", "RISK", "COMMIT"])
        for m in rows:
            r = (m["evaluation"] or {}).get("risk") or {}
            t.add_row(str(m["position"] or "-"), short(m["id"]), m["task"]["title"], st(m["status"]),
                      f"{r.get('score', '-')} {r.get('severity', '')}".strip(), short(m["merge_commit"], 10))
        console.print(t)
    emit(rows, as_json, render)


@app.command()
def rollback(merge_id: str, reason: Annotated[str | None, typer.Option("-m", "--reason")] = None,
             as_json: JsonOpt = False):
    """Revert a completed merge on its target branch."""
    m = call(client().post, f"/merges/{merge_id}/rollback", {"reason": reason})
    emit(m, as_json, lambda m: console.print(f"[green]✓[/] rolled back with {short(m['revert_commit'], 10)}"))


@app.command()
def reproduce(execution_id: str, keep: bool = False, as_json: JsonOpt = False):
    """Replay an execution and report what could and could not be reproduced."""
    with console.status("replaying execution…"):
        r = call(client().post, f"/executions/{execution_id}/reproduce", {"keep_workspace": keep})

    def render(r):
        style = {"REPRODUCED": "green", "PARTIAL": "yellow", "DIVERGED": "red", "FAILED": "bold red"}[r["verdict"]]
        console.print(Text(r["verdict"], style=style), r.get("summary", ""))
        rs = r["repository_state"]
        console.print(f"repository {rs['repository']} @ {short(rs['base_commit'], 10)}")
        for s in r["steps"]:
            mark = "[green]✓[/]" if s.get("match", True) and s["action"] != "failed" else "[red]✗[/]"
            console.print(f"  {mark} {s['sequence']:>3} {s['tool']:<12} {s.get('path') or s.get('command') or ''}"
                          f" [dim]{s.get('note') or ''}[/]")
        if "files" in r:
            console.print(f"file tree: {'[green]match[/]' if r['files']['match'] else '[red]differs[/]'}")
        console.print("[bold]Reproducible:[/]")
        for x in r["reproducible"]:
            console.print(f"  + {x}")
        console.print("[bold]Not reproducible:[/]")
        for x in r["not_reproducible"]:
            console.print(f"  - {x}")
    emit(r, as_json, render)


@app.command()
def trace(location: Annotated[str, typer.Argument(help="path:line")], repo: Annotated[str, typer.Option("--repo", "-r")],
          rev: str | None = None, as_json: JsonOpt = False):
    """Why does this line exist? line → commit → change → execution → agent → task → model."""
    path, _, line = location.rpartition(":")
    t = call(client().get, f"/repositories/{repo}/provenance", path=path, line=int(line), rev=rev)

    def render(t):
        console.print(Syntax(t["content"], "python", theme="ansi_dark", line_numbers=False))
        tree = Tree(f"[bold]{path}:{line}[/] ({t['origin']})")
        node = tree
        for c in t["chain"][1:]:
            node = node.add(f"[bold]{c['type']}[/] {c.get('label') or c.get('id')}")
        console.print(tree)
    emit(t, as_json, render)


@app.command()
def events(follow: Annotated[bool, typer.Option("--follow", "-f", help="Stream live events")] = False,
           limit: int = 30, type: str | None = None, as_json: JsonOpt = False):
    """Show the audit log (optionally follow it live over WebSocket)."""
    rows = call(client().get, "/events", limit=limit, type=type)
    rows.reverse()

    def line(e):
        return f"[dim]{e['created_at'][11:19]}[/] [cyan]{e['type']:<22}[/] {e['message']}"
    if as_json and not follow:
        emit(rows, True, None)
        return
    for e in rows:
        console.print(line(e)) if not as_json else print(json.dumps(e))
    if follow:
        import websockets.sync.client as wsc

        cfg = load_config()
        base = (os.environ.get("FORGEFLOW_API_URL") or cfg.get("api_url") or "http://localhost:8000")
        url = base.replace("http", "ws", 1).rstrip("/") + "/api/v1/ws/events?backfill=0"
        if cfg.get("token"):
            url += f"&token={cfg['token']}"
        with wsc.connect(url) as ws:
            for msg in ws:
                e = json.loads(msg)
                if type and not e["type"].startswith(type):
                    continue
                console.print(line(e)) if not as_json else print(json.dumps(e), flush=True)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):  # Windows consoles default to a legacy code page
            stream.reconfigure(encoding="utf-8", errors="replace")
    app()


if __name__ == "__main__":
    main()
