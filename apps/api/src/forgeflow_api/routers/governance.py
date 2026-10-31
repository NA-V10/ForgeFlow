from __future__ import annotations

import uuid
from dataclasses import asdict

from ff_policy import PolicyContext, PolicyError, PolicySet
from fastapi import APIRouter
from sqlalchemy import func, select

from ..auth import require_human
from ..core import ForgeError, effective_policies, get_or_404
from ..deps import ForgeDep, PrincipalDep, SessionDep
from ..events import record_event
from ..models import Approval, Policy, Repository, Review, RiskAssessment, Task, Workspace
from ..schemas import (
    ApprovalDecision,
    ApprovalDetail,
    ApprovalOut,
    PolicyCheck,
    PolicyOut,
    PolicyPut,
    ReviewOut,
    RiskAssessmentOut,
)
from ..services import review as svc

router = APIRouter()


# -------------------------------------------------------------------- reviews
@router.post("/workspaces/{ref}/review", response_model=ReviewOut, status_code=201, tags=["reviews"],
             summary="Submit a workspace for review (semantic diff, risk, policy, approvals)")
def submit_review(ref: str, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    review = svc.submit_review(forge, s, p, get_or_404(s, Workspace, ref, "workspace"))
    s.commit()
    return review


@router.get("/reviews", response_model=list[ReviewOut], tags=["reviews"])
def list_reviews(s: SessionDep, _: PrincipalDep, workspace_id: str | None = None, task_id: str | None = None):
    q = select(Review).order_by(Review.created_at.desc())
    if workspace_id:
        q = q.where(Review.workspace_id == get_or_404(s, Workspace, workspace_id).id)
    if task_id:
        q = q.where(Review.task_id == get_or_404(s, Task, task_id).id)
    return s.execute(q).scalars().all()


@router.get("/reviews/{ref}", response_model=ReviewOut, tags=["reviews"])
def get_review(ref: str, s: SessionDep, _: PrincipalDep):
    return get_or_404(s, Review, ref, "review")


@router.post("/workspaces/{ref}/risk", response_model=RiskAssessmentOut, status_code=201, tags=["reviews"],
             summary="Compute a deterministic risk assessment")
def assess(ref: str, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    ra = svc.assess_workspace(forge, s, p, get_or_404(s, Workspace, ref, "workspace"))
    s.commit()
    return ra


@router.get("/risk-assessments", response_model=list[RiskAssessmentOut], tags=["reviews"])
def list_risk(s: SessionDep, _: PrincipalDep, workspace_id: str | None = None, task_id: str | None = None,
              limit: int = 100):
    q = select(RiskAssessment).order_by(RiskAssessment.created_at.desc()).limit(limit)
    if workspace_id:
        q = q.where(RiskAssessment.workspace_id == get_or_404(s, Workspace, workspace_id).id)
    if task_id:
        q = q.where(RiskAssessment.task_id == get_or_404(s, Task, task_id).id)
    return s.execute(q).scalars().all()


# ------------------------------------------------------------------ approvals
@router.get("/approvals", response_model=list[ApprovalOut], tags=["approvals"])
def list_approvals(s: SessionDep, _: PrincipalDep, status: str | None = None, workspace_id: str | None = None,
                   task_id: str | None = None):
    q = select(Approval).order_by(Approval.created_at.desc())
    if status:
        q = q.where(Approval.status == status.upper())
    if workspace_id:
        q = q.where(Approval.workspace_id == get_or_404(s, Workspace, workspace_id).id)
    if task_id:
        q = q.where(Approval.task_id == get_or_404(s, Task, task_id).id)
    return s.execute(q).scalars().all()


@router.get("/approvals/{ref}", response_model=ApprovalDetail, tags=["approvals"],
            summary="Approval with agent, task, action, files, diff, risk, policy reason, tests and evidence")
def get_approval(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep):
    a = get_or_404(s, Approval, ref, "approval")
    return ApprovalDetail(**ApprovalOut.model_validate(a).model_dump(), context=svc.approval_context(forge, s, a))


@router.post("/approvals/{ref}/approve", response_model=ApprovalOut, tags=["approvals"])
def approve(ref: str, body: ApprovalDecision, s: SessionDep, p: PrincipalDep):
    a = svc.decide_approval(s, p, get_or_404(s, Approval, ref, "approval"), True, body.comment)
    s.commit()
    return a


@router.post("/approvals/{ref}/reject", response_model=ApprovalOut, tags=["approvals"])
def reject(ref: str, body: ApprovalDecision, s: SessionDep, p: PrincipalDep):
    a = svc.decide_approval(s, p, get_or_404(s, Approval, ref, "approval"), False, body.comment)
    s.commit()
    return a


# ------------------------------------------------------------------- policies
@router.get("/policies", response_model=list[PolicyOut], tags=["policies"])
def list_policies(s: SessionDep, _: PrincipalDep, all_versions: bool = False):
    q = select(Policy).order_by(Policy.scope, Policy.version.desc())
    rows = s.execute(q).scalars().all()
    if all_versions:
        return rows
    seen, out = set(), []
    for r in rows:
        if r.scope not in seen and r.active:
            seen.add(r.scope)
            out.append(r)
    return out


@router.get("/policies/effective", tags=["policies"], summary="The merged policy set that applies to a repository")
def effective(s: SessionDep, _: PrincipalDep, repository_id: str | None = None):
    rid = get_or_404(s, Repository, repository_id, "repository").id if repository_id else None
    ps = effective_policies(s, rid)
    return {"default": ps.default, "policies": [asdict(p) for p in ps.policies]}


@router.put("/policies/{scope}", response_model=PolicyOut, tags=["policies"],
            summary="Publish a new version of a policy document ('global' or a repository id/name)")
def put_policy(scope: str, body: PolicyPut, s: SessionDep, p: PrincipalDep):
    require_human(p, "change policies")
    if scope != "global":
        scope = str(get_or_404(s, Repository, scope, "repository").id)
    try:
        ps = PolicySet.from_yaml(body.document)
    except PolicyError as exc:
        raise ForgeError(f"invalid policy document: {exc}") from exc
    version = (s.execute(select(func.max(Policy.version)).where(Policy.scope == scope)).scalar() or 0) + 1
    row = Policy(scope=scope, version=version, document=body.document, created_by=p.name)
    s.add(row)
    s.flush()
    record_event(s, "policy.updated", p.actor, f"Policy '{scope}' v{version} published ({len(ps.policies)} rules)",
                 repository_id=None if scope == "global" else uuid.UUID(scope),
                 subject=("policy", row.id), payload={"scope": scope, "version": version,
                                                      "rules": [x.name for x in ps.policies]})
    s.commit()
    return row


@router.post("/policies/check", tags=["policies"], summary="Evaluate an action against the effective policies")
def check(body: PolicyCheck, s: SessionDep, _: PrincipalDep):
    rid = get_or_404(s, Repository, body.repository_id, "repository").id if body.repository_id else None
    decision = effective_policies(s, rid).evaluate(PolicyContext(
        action=body.action, paths=body.paths, agent=body.agent, command=body.command, risk_score=body.risk_score,
        risk_severity=body.risk_severity.upper() if body.risk_severity else None,
    ))
    return decision.to_dict()
