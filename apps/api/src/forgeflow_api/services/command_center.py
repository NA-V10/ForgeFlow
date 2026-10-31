"""Command-center views: the ranked "needs you" inbox and per-workspace agent threads."""

from __future__ import annotations

import uuid
from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Approval, Event, Execution, Merge, RiskAssessment, Task, Workspace

_PRIORITY_BY_SEVERITY = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 2}
GATE_STEPS = 7


def _latest_risk(s: Session) -> dict[uuid.UUID, RiskAssessment]:
    out: dict[uuid.UUID, RiskAssessment] = {}
    for r in s.execute(select(RiskAssessment).order_by(RiskAssessment.created_at)).scalars():
        out[r.workspace_id] = r
    return out


def _agent(ws: Workspace | None) -> dict[str, Any] | None:
    if ws is None or ws.agent is None:
        return None
    return {"id": str(ws.agent.id), "name": ws.agent.name, "model": ws.agent.model}


def inbox(s: Session) -> list[dict[str, Any]]:
    """Everything waiting on a human, ranked deterministically.

    P0: critical risk or a merge conflict. P1: high risk, semantic-conflict sign-off, blocked merges,
    failed agent runs, blocked tasks. P2: everything else. Within a priority, the item that has
    waited longest comes first.
    """
    risk = _latest_risk(s)
    items: list[dict[str, Any]] = []

    def add(kind: str, priority: int, ws: Workspace | None, title: str, reason: str, created, href: str,
            needs: str, ref: str, **extra: Any) -> None:
        r = risk.get(ws.id) if ws else None
        items.append({
            "id": f"{kind}:{ref}", "kind": kind, "priority": f"P{priority}", "title": title, "reason": reason,
            "needs": needs, "href": href, "created_at": created, "agent": _agent(ws),
            "workspace_id": str(ws.id) if ws else None, "task_id": str(ws.task_id) if ws else None,
            "branch": ws.branch if ws else None,
            "risk": {"score": r.score, "severity": r.severity} if r else None, **extra,
        })

    for a in s.execute(select(Approval).where(Approval.status == "PENDING")).scalars():
        ws = a.workspace
        r = risk.get(ws.id)
        p = _PRIORITY_BY_SEVERITY[r.severity] if r else 2
        if a.kind == "semantic_conflict":
            p = min(p, 1)
        add("approval", p, ws, ws.task.title, a.reason, a.created_at, f"/approvals/{a.id}", "approve", str(a.id),
            approval_id=str(a.id), approval_kind=a.kind)

    merged_tasks: set[uuid.UUID] = set()
    for m in s.execute(select(Merge).where(Merge.status.in_(["CONFLICT", "BLOCKED", "READY"]))).scalars():
        ws = m.workspace
        merged_tasks.add(ws.task_id)
        reasons = (m.evaluation or {}).get("reasons") or []
        when = m.evaluated_at or m.created_at
        common = dict(merge_id=str(m.id), merge_status=m.status)
        if m.status == "CONFLICT":
            add("merge", 0, ws, ws.task.title, reasons[0] if reasons else "merge conflict", when,
                f"/workspaces/{ws.id}", "resolve", str(m.id), **common)
        elif m.status == "BLOCKED":
            add("merge", 1, ws, ws.task.title, reasons[0] if reasons else "merge blocked", when,
                f"/workspaces/{ws.id}", "investigate", str(m.id), **common)
        else:
            add("merge", 2, ws, ws.task.title, "all checks passed; ready to merge", when,
                f"/workspaces/{ws.id}", "merge", str(m.id), **common)

    for ws in s.execute(select(Workspace).where(Workspace.status == "FAILED")).scalars():
        ex = s.execute(select(Execution).where(Execution.workspace_id == ws.id)
                       .order_by(Execution.started_at.desc())).scalars().first()
        add("execution", 1, ws, ws.task.title, ex.error if ex and ex.error else "agent run failed",
            ex.finished_at if ex and ex.finished_at else ws.updated_at,
            f"/executions/{ex.id}" if ex else f"/workspaces/{ws.id}", "investigate", str(ex.id if ex else ws.id))

    for t in s.execute(select(Task).where(Task.status == "BLOCKED")).scalars():
        if t.id in merged_tasks:
            continue
        ws = s.execute(select(Workspace).where(Workspace.task_id == t.id)
                       .order_by(Workspace.created_at.desc())).scalars().first()
        add("task", 1, ws, t.title, "task is blocked", t.started_at or t.created_at, f"/tasks/{t.id}",
            "investigate", str(t.id))

    items.sort(key=lambda i: (i["priority"], i["created_at"]))
    return items


def threads(s: Session, limit: int = 60, include_closed: bool = True) -> list[dict[str, Any]]:
    """One summary per workspace: the agent's current state, progress and what it is waiting for."""
    q = select(Workspace).order_by(Workspace.updated_at.desc()).limit(limit)
    if not include_closed:
        q = q.where(Workspace.status.notin_(["MERGED", "ABANDONED"]))
    risk = _latest_risk(s)
    pending = Counter(a.workspace_id for a in s.execute(select(Approval).where(Approval.status == "PENDING")).scalars())
    out = []
    for ws in s.execute(q).scalars():
        ex = s.execute(select(Execution).where(Execution.workspace_id == ws.id)
                       .order_by(Execution.started_at.desc())).scalars().first()
        merge = s.execute(select(Merge).where(Merge.workspace_id == ws.id)
                          .order_by(Merge.created_at.desc())).scalars().first()
        last = s.execute(select(Event).where(Event.workspace_id == ws.id)
                         .order_by(Event.seq.desc()).limit(1)).scalars().first()

        execution = None
        if ex is not None:
            calls = sorted(ex.tool_calls, key=lambda c: c.sequence)
            tests = (ex.summary or {}).get("tests")
            if tests is None:
                tests = next(((c.output or {}).get("tests") for c in reversed(calls) if (c.output or {}).get("tests")),
                             None)
            last_tool = None
            if calls:
                c = calls[-1]
                last_tool = {"tool": c.tool, "target": c.command or (c.input or {}).get("path"), "status": c.status}
            execution = {
                "id": str(ex.id), "status": ex.status, "model": ex.model, "started_at": ex.started_at,
                "finished_at": ex.finished_at, "tool_calls": len(calls),
                "files": len({f for c in calls for f in (c.files_affected or []) if c.status != "DENIED"}),
                "denied": sum(1 for c in calls if c.status == "DENIED"), "last_tool": last_tool, "tests": tests,
            }

        gate = None
        if merge is not None:
            checks = (merge.evaluation or {}).get("checks", [])
            passed = GATE_STEPS if merge.status in ("MERGED", "ROLLED_BACK") else sum(
                1 for c in checks if c.get("status") == "pass")
            gate = {"passed": passed, "total": GATE_STEPS, "status": merge.status, "merge_id": str(merge.id),
                    "merged_at": merge.merged_at}

        r = risk.get(ws.id)
        out.append({
            "workspace_id": str(ws.id), "status": ws.status, "branch": ws.branch,
            "repository_id": str(ws.repository_id),
            "task": {"id": str(ws.task.id), "title": ws.task.title, "status": ws.task.status,
                     "priority": ws.task.priority},
            "agent": {**_agent(ws), "kind": ws.agent.kind} if ws.agent else None,
            "execution": execution, "gate": gate,
            "risk": {"score": r.score, "severity": r.severity} if r else None,
            "pending_approvals": pending.get(ws.id, 0),
            "last_event": {"type": last.type, "message": last.message, "created_at": last.created_at} if last else None,
            "updated_at": ws.updated_at,
        })
    return out
