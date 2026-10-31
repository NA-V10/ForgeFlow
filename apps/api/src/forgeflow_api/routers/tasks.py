from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..core import get_or_404
from ..deps import ForgeDep, PrincipalDep, SessionDep
from ..models import Approval, Change, Checkpoint, Execution, Merge, Repository, Review, RiskAssessment, Task, Workspace
from ..schemas import TaskCreate, TaskDetail, TaskOut, TaskUpdate
from ..services import registry
from .workspaces import ws_out

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    task = registry.create_task(forge, s, p, **body.model_dump())
    s.commit()
    return task


@router.get("", response_model=list[TaskOut])
def list_tasks(s: SessionDep, _: PrincipalDep, repository_id: str | None = None, status: str | None = None,
               agent_id: str | None = None, limit: int = 200):
    q = select(Task).order_by(Task.created_at.desc()).limit(limit)
    if repository_id:
        q = q.where(Task.repository_id == get_or_404(s, Repository, repository_id, "repository").id)
    if status:
        q = q.where(Task.status == status.upper())
    if agent_id:
        from ..models import Agent

        q = q.where(Task.agent_id == get_or_404(s, Agent, agent_id, "agent").id)
    return s.execute(q).scalars().all()


@router.get("/{ref}", response_model=TaskDetail)
def get_task(ref: str, s: SessionDep, p: PrincipalDep):
    t = get_or_404(s, Task, ref, "task")

    def rows(model, order):
        return s.execute(select(model).where(model.task_id == t.id).order_by(order)).scalars().all()

    workspaces = [ws_out(w, p) for w in rows(Workspace, Workspace.created_at)]
    risk = s.execute(select(RiskAssessment).where(RiskAssessment.task_id == t.id)
                     .order_by(RiskAssessment.created_at.desc())).scalars().first()
    return TaskDetail(
        **TaskOut.model_validate(t).model_dump(),
        workspaces=workspaces,
        executions=rows(Execution, Execution.started_at),
        checkpoints=rows(Checkpoint, Checkpoint.created_at),
        changes=rows(Change, Change.created_at),
        reviews=rows(Review, Review.created_at),
        approvals=rows(Approval, Approval.created_at),
        risk=risk,
        merges=rows(Merge, Merge.created_at),
    )


@router.patch("/{ref}", response_model=TaskOut)
def update_task(ref: str, body: TaskUpdate, s: SessionDep, p: PrincipalDep):
    t = get_or_404(s, Task, ref, "task")
    if body.agent_id is not None:
        registry.assign_task(s, p, t, body.agent_id or None)
    if body.priority:
        t.priority = body.priority.upper()
    if body.description is not None:
        t.description = body.description
    if body.status:
        registry.set_task_status(s, t, body.status.upper(), p.actor, f"set by {p.name}")
    s.commit()
    return t
