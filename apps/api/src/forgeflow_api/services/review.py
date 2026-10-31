"""Review submission, risk assessment and human approvals."""

from __future__ import annotations

from typing import Any

from ff_merge import RangeAnalysis, Requirement
from ff_policy import PolicyContext, PolicyDecision
from ff_risk import RiskFile, RiskInput, RiskResult, TestEvidence, assess_risk
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, require_human
from ..core import Forge, ForgeError, InvalidState, PermissionDenied, effective_policies
from ..db import utcnow
from ..events import Actor, record_event
from ..models import (
    Approval,
    ApprovalStatus,
    Checkpoint,
    Execution,
    Review,
    RiskAssessment,
    Workspace,
    WorkspaceStatus,
)
from .registry import set_task_status
from .workspaces import committed_analysis, transition, ws_path


def latest_tests(s: Session, ws: Workspace) -> dict[str, Any] | None:
    for ex in s.execute(select(Execution).where(Execution.workspace_id == ws.id)
                        .order_by(Execution.started_at.desc())).scalars():
        tests = (ex.summary or {}).get("tests")
        if tests:
            return tests
    return None


def compute_risk(s: Session, ws: Workspace, analysis: RangeAnalysis,
                 conflicts: list[dict] | None = None) -> RiskResult:
    tests = latest_tests(s, ws)
    return assess_risk(RiskInput(
        files=[RiskFile(f.path, f.status, f.additions, f.deletions) for f in analysis.diff.files],
        semantic_changes=[c.to_dict() for c in analysis.semantic.changes],
        tests=TestEvidence(tests["passed"], tests["failed"], tests.get("errors", 0)) if tests else None,
        conflicts=conflicts or [],
    ))


def save_risk(s: Session, ws: Workspace, risk: RiskResult, actor: Actor) -> RiskAssessment:
    ra = RiskAssessment(workspace_id=ws.id, task_id=ws.task_id, head_commit=ws.current_commit, score=risk.score,
                        severity=risk.severity, reasons=risk.reasons,
                        signals=[{"name": x.name, "points": x.points, "reason": x.reason} for x in risk.signals])
    s.add(ra)
    s.flush()
    record_event(s, "risk.assessed", actor, f"Risk {risk.score}/100 {risk.severity} for '{ws.task.title}'",
                 repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, agent_id=ws.agent_id,
                 subject=("risk_assessment", ra.id), payload={"score": risk.score, "severity": risk.severity,
                                                              "reasons": risk.reasons})
    return ra


def assess_workspace(forge: Forge, s: Session, p: Principal, ws: Workspace) -> RiskAssessment:
    if ws.current_commit == ws.base_commit:
        raise InvalidState("workspace has no committed changes")
    return save_risk(s, ws, compute_risk(s, ws, committed_analysis(forge, ws)), p.actor)


def evaluate_merge_policy(s: Session, ws: Workspace, analysis: RangeAnalysis, risk: RiskResult) -> PolicyDecision:
    return effective_policies(s, ws.repository_id).evaluate(PolicyContext(
        action="merge", paths=[f.path for f in analysis.diff.files],
        agent=ws.agent.name if ws.agent else None, risk_score=risk.score, risk_severity=risk.severity,
    ))


def ensure_approvals(s: Session, ws: Workspace, requirements: list[Requirement], actor: Actor, *,
                     review: Review | None = None, merge_id=None) -> list[Approval]:
    """Create pending approvals for requirements that do not yet have one for the current head."""
    out = []
    existing = s.execute(select(Approval).where(Approval.workspace_id == ws.id,
                                                Approval.status != ApprovalStatus.STALE.value)).scalars().all()
    by_key = {a.requirement_key: a for a in existing}
    for a in existing:
        if a.head_commit != ws.current_commit:
            a.status = ApprovalStatus.STALE.value
            by_key.pop(a.requirement_key, None)
    for r in requirements:
        a = by_key.get(r.key)
        if a is None:
            a = Approval(workspace_id=ws.id, task_id=ws.task_id, review_id=review.id if review else None,
                         merge_id=merge_id, requirement_key=r.key, kind=r.kind, reason=r.reason,
                         head_commit=ws.current_commit, details={**r.details, "approvals_required":
                                                                 r.approvals_required})
            s.add(a)
            s.flush()
            record_event(s, "approval.requested", actor, f"Approval requested for '{ws.task.title}': {r.reason}",
                         repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id,
                         agent_id=ws.agent_id, subject=("approval", a.id),
                         payload={"requirement": r.key, "kind": r.kind, "reason": r.reason})
        elif merge_id and a.merge_id is None:
            a.merge_id = merge_id
        out.append(a)
    return out


def approval_map(s: Session, ws: Workspace) -> dict[str, str]:
    rows = s.execute(select(Approval).where(Approval.workspace_id == ws.id,
                                            Approval.head_commit == ws.current_commit)).scalars().all()
    return {a.requirement_key: a.status for a in rows if a.status != ApprovalStatus.STALE.value}


def submit_review(forge: Forge, s: Session, p: Principal, ws: Workspace) -> Review:
    if p.type == "agent" and ws.agent_id != p.agent_id:
        raise PermissionDenied("agents may only submit their own workspaces")
    if ws.status not in (WorkspaceStatus.CHECKPOINTED.value, WorkspaceStatus.REVIEW.value):
        raise InvalidState(f"workspace is {ws.status}; it must be CHECKPOINTED to submit for review")
    if forge.engine.has_uncommitted_changes(ws_path(ws)):
        raise InvalidState("workspace has uncommitted changes; create a checkpoint first")
    if ws.current_commit == ws.base_commit:
        raise ForgeError("workspace has no changes to review")
    actor = p.actor
    analysis = committed_analysis(forge, ws)
    risk = compute_risk(s, ws, analysis)
    ra = save_risk(s, ws, risk, actor)
    policy = evaluate_merge_policy(s, ws, analysis, risk)
    for old in s.execute(select(Review).where(Review.workspace_id == ws.id, Review.status == "OPEN")).scalars():
        old.status = "SUPERSEDED"
    review = Review(
        workspace_id=ws.id, task_id=ws.task_id, base_commit=ws.base_commit, head_commit=ws.current_commit,
        diff_stats={"files": len(analysis.diff.files), "additions": analysis.diff.additions,
                    "deletions": analysis.diff.deletions},
        semantic_diff=analysis.semantic.to_dict(), policy=policy.to_dict(), submitted_by=p.name,
    )
    s.add(review)
    s.flush()
    requirements = [Requirement(key=f"policy:{m.policy}", kind="policy", reason=m.reason,
                                approvals_required=m.approvals,
                                details={"effect": m.effect, "paths": m.matched_paths})
                    for m in policy.requirements]
    approvals = ensure_approvals(s, ws, requirements, actor, review=review)
    transition(s, ws, WorkspaceStatus.REVIEW, actor, "submitted for review")
    if ws.task.status != "REVIEW":
        set_task_status(s, ws.task, "REVIEW", actor)
    record_event(s, "review.submitted", actor,
                 f"'{ws.task.title}' submitted for review: {len(analysis.diff.files)} files, risk {risk.score} "
                 f"{risk.severity}, {len(approvals)} approval(s) required",
                 repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, agent_id=ws.agent_id,
                 subject=("review", review.id),
                 payload={"risk": {"score": risk.score, "severity": risk.severity}, "policy": policy.effect,
                          "risk_assessment_id": str(ra.id), "approvals": [str(a.id) for a in approvals],
                          "summary": analysis.semantic.domains()})
    return review


def decide_approval(s: Session, p: Principal, approval: Approval, approve: bool, comment: str | None = None
                    ) -> Approval:
    require_human(p, "approve or reject changes")
    if approval.status != ApprovalStatus.PENDING.value:
        raise InvalidState(f"approval is already {approval.status}")
    ws = s.get(Workspace, approval.workspace_id)
    assert ws is not None
    if approval.head_commit != ws.current_commit:
        approval.status = ApprovalStatus.STALE.value
        record_event(s, "approval.stale", p.actor, "Approval became stale: workspace changed since it was requested",
                     repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id,
                     subject=("approval", approval.id))
        s.commit()
        raise InvalidState("workspace changed since this approval was requested; re-submit for review")
    approval.status = (ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED).value
    approval.decided_by = p.name
    approval.decided_at = utcnow()
    approval.comment = comment
    record_event(s, "approval.granted" if approve else "approval.rejected", p.actor,
                 f"{p.name} {'approved' if approve else 'rejected'} '{ws.task.title}': {approval.reason}"
                 + (f" — {comment}" if comment else ""),
                 repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, agent_id=ws.agent_id,
                 subject=("approval", approval.id), payload={"requirement": approval.requirement_key,
                                                             "comment": comment})
    if not approve and ws.task.status in ("REVIEW", "RUNNING"):
        set_task_status(s, ws.task, "BLOCKED", p.actor, f"approval rejected: {approval.reason}")
    return approval


def approval_context(forge: Forge, s: Session, approval: Approval) -> dict[str, Any]:
    """Everything a human needs to decide: agent, task, action, files, diff, risk, policy, tests, evidence."""
    ws = s.get(Workspace, approval.workspace_id)
    assert ws is not None
    analysis = committed_analysis(forge, ws) if ws.current_commit != ws.base_commit else None
    risk = s.execute(select(RiskAssessment).where(RiskAssessment.workspace_id == ws.id)
                     .order_by(RiskAssessment.created_at.desc())).scalars().first()
    executions = s.execute(select(Execution).where(Execution.workspace_id == ws.id)
                           .order_by(Execution.started_at)).scalars().all()
    checkpoints = s.execute(select(Checkpoint).where(Checkpoint.workspace_id == ws.id)
                            .order_by(Checkpoint.created_at)).scalars().all()
    patch = analysis.diff.patch if analysis else ""
    return {
        "agent": {"id": str(ws.agent.id), "name": ws.agent.name, "model": ws.agent.model} if ws.agent else None,
        "task": {"id": str(ws.task.id), "title": ws.task.title, "status": ws.task.status,
                 "priority": ws.task.priority},
        "workspace": {"id": str(ws.id), "status": ws.status, "branch": ws.branch, "base_commit": ws.base_commit,
                      "head_commit": ws.current_commit},
        "action": approval.action,
        "files": [{"path": f.path, "status": f.status, "additions": f.additions, "deletions": f.deletions}
                  for f in analysis.diff.files] if analysis else [],
        "diff": patch[:200_000],
        "diff_truncated": len(patch) > 200_000,
        "semantic": analysis.semantic.to_dict() if analysis else None,
        "risk": {"score": risk.score, "severity": risk.severity, "reasons": risk.reasons, "signals": risk.signals,
                 "head_commit": risk.head_commit} if risk else None,
        "policy_reason": approval.reason,
        "requirement": approval.requirement_key,
        "tests": latest_tests(s, ws),
        "evidence": {
            "executions": [{"id": str(e.id), "status": e.status, "model": e.model, "model_version": e.model_version,
                            "commands": (e.summary or {}).get("commands", []),
                            "tool_calls": (e.summary or {}).get("tool_calls"),
                            "denied": (e.summary or {}).get("denied"),
                            "sandbox": (e.environment or {}).get("sandbox")} for e in executions],
            "checkpoints": [{"id": str(c.id), "commit": c.commit_sha, "message": c.message} for c in checkpoints],
        },
    }
