"""Provenance tracing, execution reproduction, dashboard aggregates and the repository graph."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from collections import Counter
from typing import Any

from ff_provenance import ProvenanceRef, parse_trailers, trace_line
from ff_sandbox import CommandDenied, confine
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal
from ..core import Forge, ForgeError, NotFound
from ..events import record_event
from ..models import (
    OPEN_MERGE_STATUSES,
    Agent,
    Approval,
    Change,
    Checkpoint,
    Execution,
    Merge,
    Repository,
    RiskAssessment,
    Task,
    Workspace,
)
from .executions import store_artifact
from .registry import repo_path


# ----------------------------------------------------------------- provenance
class DbResolver:
    def __init__(self, s: Session) -> None:
        self.s = s

    def resolve(self, ref: ProvenanceRef, commit_sha: str, path: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        change = self.s.execute(select(Change).where(Change.commit_sha == commit_sha, Change.path == path)
                                ).scalars().first()
        if change:
            out["change"] = {"id": str(change.id), "label": f"{change.change_type} {path} "
                             f"(+{change.additions}/-{change.deletions})", "checkpoint_id": str(change.checkpoint_id)}
        if ref.execution:
            ex = self.s.get(Execution, uuid.UUID(ref.execution))
            if ex:
                out["execution"] = {"id": str(ex.id), "label": f"{str(ex.id)[:8]} {ex.status}",
                                    "model": ex.model, "model_version": ex.model_version,
                                    "started_at": ex.started_at.isoformat()}
        if ref.agent:
            agent = self.s.get(Agent, uuid.UUID(ref.agent))
            if agent:
                out["agent"] = {"id": str(agent.id), "label": agent.name, "model": agent.model}
        if ref.task:
            task = self.s.get(Task, uuid.UUID(ref.task))
            if task:
                out["task"] = {"id": str(task.id), "label": task.title, "status": task.status}
        return out


def trace(forge: Forge, s: Session, repo: Repository, path: str, line: int, ref: str | None = None) -> dict[str, Any]:
    rp = repo_path(repo)
    commit = forge.engine.resolve(rp, ref or repo.default_branch)
    if not commit:
        raise NotFound(f"ref {ref} not found")
    if forge.engine.read_file(rp, commit, path) is None:
        raise NotFound(f"{path} does not exist at {commit[:10]}")
    try:
        lp = trace_line(forge.engine, rp, commit, path, line, DbResolver(s))
    except ValueError as exc:
        raise ForgeError(str(exc)) from exc
    return {**lp.to_dict(), "explanation": lp.explain(), "at": commit}


def file_provenance(forge: Forge, s: Session, repo: Repository, path: str, ref: str | None = None) -> dict[str, Any]:
    rp = repo_path(repo)
    commit = forge.engine.resolve(rp, ref or repo.default_branch)
    if not commit or forge.engine.read_file(rp, commit, path) is None:
        raise NotFound(f"{path} not found at {ref or repo.default_branch}")
    lines = forge.engine.blame(rp, commit, path)
    resolver = DbResolver(s)
    cache: dict[str, dict[str, Any]] = {}
    out = []
    for b in lines:
        if b.commit not in cache:
            info = forge.engine.commit_info(rp, b.commit)
            pref = parse_trailers(info.trailers)
            rec = resolver.resolve(pref, b.commit, path) if pref.is_forgeflow else {}
            cache[b.commit] = {
                "commit": b.commit, "author": info.author, "message": info.message.splitlines()[0],
                "origin": "agent" if pref.is_forgeflow else "human",
                "agent": rec.get("agent", {}).get("label"), "task": rec.get("task", {}).get("label"),
                "execution_id": pref.execution, "task_id": pref.task, "model": pref.model,
            }
        out.append({"line": b.line_no, "content": b.content, **cache[b.commit]})
    return {"path": path, "commit": commit, "lines": out}


# -------------------------------------------------------------- reproduction
def reproduce_execution(forge: Forge, s: Session, p: Principal, ex: Execution, keep: bool = False) -> dict[str, Any]:
    ws = s.get(Workspace, ex.workspace_id)
    assert ws is not None
    repo = ws.repository
    rp = repo_path(repo)
    report: dict[str, Any] = {"execution_id": str(ex.id), "agent": ex.agent.name, "model": ex.model,
                              "model_version": ex.model_version, "steps": []}
    base_ok = bool(forge.engine.resolve(rp, ex.base_commit))
    report["repository_state"] = {"repository": repo.name, "base_commit": ex.base_commit, "available": base_ok}
    if not base_ok:
        report["verdict"] = "FAILED"
        report["not_reproducible"] = ["base commit is no longer present in the repository"]
        return report

    path = forge.settings.scratch_dir / f"repro-{str(ex.id)[:8]}-{uuid.uuid4().hex[:6]}"
    forge.engine.create_detached_worktree(rp, path, ex.base_commit)
    report["workspace"] = {"path": str(path) if p.is_human else None, "kept": keep}
    sandbox = forge.sandbox(ws.permissions)
    diverged_steps = 0
    missing_blobs = 0
    try:
        for call in sorted(ex.tool_calls, key=lambda c: c.sequence):
            step: dict[str, Any] = {"sequence": call.sequence, "tool": call.tool, "original_status": call.status}
            if call.status == "DENIED":
                step.update(action="skipped", note="denied in the original run")
            elif call.tool == "write_file":
                data = forge.store.get_blob(call.input["sha256"])
                if data is None:
                    missing_blobs += 1
                    step.update(action="failed", note="recorded content is missing from artifact storage")
                else:
                    target = confine(path, call.input["path"])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
                    step.update(action="replayed", path=call.input["path"], match=True)
            elif call.tool == "delete_file":
                target = confine(path, call.input["path"])
                if target.exists():
                    target.unlink()
                step.update(action="replayed", path=call.input["path"], match=True)
            elif call.tool == "read_file":
                target = confine(path, call.input["path"])
                now = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
                match = now == (call.output or {}).get("sha256")
                diverged_steps += 0 if match else 1
                step.update(action="verified", path=call.input["path"], match=match,
                            note=None if match else "file content differed from what the agent read")
            elif call.tool == "run_command":
                argv = call.input.get("argv") or []
                try:
                    r = sandbox.run(argv, path, timeout=forge.settings.command_timeout)
                    orig_tests = (call.output or {}).get("tests")
                    new_tests = r.tests.to_dict() if r.tests else None
                    same_tests = (orig_tests or {}).get("passed") == (new_tests or {}).get("passed") and \
                        (orig_tests or {}).get("failed") == (new_tests or {}).get("failed")
                    match = r.exit_code == call.exit_code and same_tests
                    diverged_steps += 0 if match else 1
                    step.update(action="replayed", command=call.command, original_exit=call.exit_code,
                                replay_exit=r.exit_code, original_tests=orig_tests, replay_tests=new_tests, match=match)
                except CommandDenied as exc:
                    diverged_steps += 1
                    step.update(action="failed", command=call.command, note=f"now denied by policy: {exc}")
            else:
                step.update(action="skipped", note="no side effects")
            report["steps"].append(step)

        replay_commit = forge.engine.commit_all(path, f"reproduction of {ex.id}", "ForgeFlow <repro@forgeflow>",
                                                allow_empty=True)
        expected = ex.result_commit
        actual_tree = forge.engine.tree_id(rp, replay_commit)
        expected_tree = forge.engine.tree_id(rp, expected) if expected else None
        differing = []
        if expected and expected_tree != actual_tree:
            differing = [f.path for f in forge.engine.diff(rp, expected, replay_commit).files]
        report["files"] = {"expected_commit": expected, "expected_tree": expected_tree, "actual_tree": actual_tree,
                           "match": expected_tree == actual_tree, "differing_paths": differing}
    finally:
        if not keep:
            forge.engine.remove_worktree(rp, path)
            shutil.rmtree(path, ignore_errors=True)

    current_env = forge.environment(ws.permissions)
    recorded_env = {k: v for k, v in (ex.environment or {}).items() if k != "client"}
    report["environment"] = {
        "recorded": ex.environment, "current": current_env,
        "differences": sorted(k for k in set(recorded_env) | set(current_env)
                              if recorded_env.get(k) != current_env.get(k)),
    }
    report["commands"] = [c.command for c in ex.tool_calls if c.tool == "run_command" and c.command]
    report["reproducible"] = [
        "repository state at the base commit (content-addressed in Git)",
        "every file write, using the exact recorded bytes (content-addressed blobs)",
        "recorded commands, re-executed in the same sandbox type with the same argv",
        "final file tree, compared hash-for-hash with the execution's result commit",
    ]
    report["not_reproducible"] = [
        "model outputs are not regenerated: the agent's recorded actions are replayed, not re-decided",
        "command side effects that depend on time, randomness or the network",
        "untracked/ignored files produced by commands are not part of the compared tree",
    ]
    guarantees = (ex.environment or {}).get("guarantees", {})
    if not guarantees.get("network_enforced"):
        report["not_reproducible"].append("network isolation was not enforced in the original sandbox")
    if not guarantees.get("resource_limits"):
        report["not_reproducible"].append("CPU/memory limits were not enforced (local sandbox)")
    if report["environment"]["differences"]:
        report["not_reproducible"].append("environment differs: " + ", ".join(report["environment"]["differences"]))
    files_match = report.get("files", {}).get("match")
    if missing_blobs:
        verdict = "FAILED"
    elif files_match and not diverged_steps:
        verdict = "REPRODUCED"
    elif files_match:
        verdict = "PARTIAL"
    else:
        verdict = "DIVERGED"
    report["verdict"] = verdict
    report["summary"] = (f"{verdict}: {len(report['steps'])} steps replayed, {diverged_steps} diverged; file tree "
                         f"{'matches' if files_match else 'differs from'} the recorded result")
    art = store_artifact(forge, s, ex, f"reproduction-{uuid.uuid4().hex[:8]}.json", "report",
                         json.dumps(report, indent=2, default=str).encode(), "application/json")
    report["artifact_id"] = str(art.id)
    record_event(s, "reproduce.completed", p.actor, f"Reproduction of execution {str(ex.id)[:8]}: {verdict}",
                 repository_id=ex.repository_id, task_id=ex.task_id, workspace_id=ex.workspace_id,
                 execution_id=ex.id, agent_id=ex.agent_id, subject=("execution", ex.id),
                 payload={"verdict": verdict, "artifact_id": str(art.id)})
    return report


# ------------------------------------------------------------------ dashboard
def dashboard(s: Session) -> dict[str, Any]:
    def count_by(model, col) -> dict[str, int]:
        return dict(s.execute(select(col, func.count()).select_from(model).group_by(col)).all())

    latest_risk: dict[uuid.UUID, RiskAssessment] = {}
    for r in s.execute(select(RiskAssessment).order_by(RiskAssessment.created_at)).scalars():
        latest_risk[r.workspace_id] = r
    live_ws = {w.id for w in s.execute(select(Workspace).where(Workspace.status.notin_(["ABANDONED"]))).scalars()}
    dist = Counter(r.severity for wid, r in latest_risk.items() if wid in live_ws)
    return {
        "counts": {
            "repositories": s.execute(select(func.count()).select_from(Repository)).scalar(),
            "agents": s.execute(select(func.count()).select_from(Agent)).scalar(),
            "tasks": count_by(Task, Task.status),
            "workspaces": count_by(Workspace, Workspace.status),
            "executions": count_by(Execution, Execution.status),
        },
        "active_agents": s.execute(select(Agent).where(Agent.status == "ACTIVE")).scalars().all(),
        "running_tasks": s.execute(select(Task).where(Task.status == "RUNNING").order_by(Task.started_at.desc())
                                   ).scalars().all(),
        "pending_approvals": s.execute(select(Approval).where(Approval.status == "PENDING")
                                       .order_by(Approval.created_at.desc())).scalars().all(),
        "merge_queue": s.execute(select(Merge).where(Merge.status.in_([m.value for m in OPEN_MERGE_STATUSES]))
                                 .order_by(Merge.created_at)).scalars().all(),
        "recent_checkpoints": s.execute(select(Checkpoint).order_by(Checkpoint.created_at.desc()).limit(10)
                                        ).scalars().all(),
        "risk_distribution": {sev: dist.get(sev, 0) for sev in ("LOW", "MEDIUM", "HIGH", "CRITICAL")},
        "recent_executions": s.execute(select(Execution).order_by(Execution.started_at.desc()).limit(10)
                                       ).scalars().all(),
    }


def repository_graph(forge: Forge, s: Session, repo: Repository) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    def node(id_: str, type_: str, label: str, **data: Any) -> None:
        nodes.append({"id": id_, "type": type_, "label": label, "data": data})

    def edge(a: str, b: str, label: str = "") -> None:
        edges.append({"id": f"{a}->{b}", "source": a, "target": b, "label": label})

    rid = f"repository:{repo.id}"
    node(rid, "repository", repo.name, id=str(repo.id), default_branch=repo.default_branch)
    branches = forge.engine.list_branches(repo_path(repo))
    ws_by_branch = {w.branch: w for w in repo.workspaces}
    for name, sha in sorted(branches.items()):
        bid = f"branch:{name}"
        node(bid, "branch", name, sha=sha, default=name == repo.default_branch)
        if name == repo.default_branch or name not in ws_by_branch:
            edge(rid, bid, "branch")
    agents_seen: set[uuid.UUID] = set()
    for t in repo.tasks:
        tid = f"task:{t.id}"
        node(tid, "task", t.title, id=str(t.id), status=t.status, priority=t.priority)
        edge(rid, tid, "task")
        if t.agent_id:
            aid = f"agent:{t.agent_id}"
            if t.agent_id not in agents_seen:
                agents_seen.add(t.agent_id)
                node(aid, "agent", t.agent.name, id=str(t.agent_id), model=t.agent.model, status=t.agent.status)
            edge(tid, aid, "assigned")
    for w in repo.workspaces:
        wid = f"workspace:{w.id}"
        node(wid, "workspace", f"{str(w.id)[:8]}", id=str(w.id), status=w.status, branch=w.branch)
        edge(f"task:{w.task_id}", wid, "workspace")
        if w.branch in branches:
            edge(wid, f"branch:{w.branch}", "branch")
        cps = s.execute(select(Checkpoint).where(Checkpoint.workspace_id == w.id).order_by(Checkpoint.created_at)
                        ).scalars().all()
        for cp in cps:
            cid = f"change:{cp.id}"
            node(cid, "change", cp.message[:48], id=str(cp.id), commit=cp.commit_sha,
                 files=(cp.filesystem or {}).get("changed"), workspace_id=str(w.id))
            edge(wid, cid, "checkpoint")
    for m in s.execute(select(Merge).where(Merge.repository_id == repo.id)).scalars():
        mid = f"merge:{m.id}"
        node(mid, "merge", m.status, id=str(m.id), status=m.status, commit=m.merge_commit,
             workspace_id=str(m.workspace_id))
        edge(f"workspace:{m.workspace_id}", mid, "merge")
        if m.status in ("MERGED", "ROLLED_BACK"):
            edge(mid, f"branch:{m.target_branch}", "into")
    return {"nodes": nodes, "edges": edges}
