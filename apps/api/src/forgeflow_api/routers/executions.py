from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..core import get_or_404
from ..deps import ForgeDep, PrincipalDep, SessionDep
from ..events import event_to_dict
from ..models import Agent, Artifact, Change, Event, Execution, Repository, Task, Workspace
from ..schemas import ExecutionCreate, ExecutionDetail, ExecutionFinish, ExecutionOut, ReproduceIn, ToolCallIn
from ..services import executions as svc
from ..services.insight import reproduce_execution

router = APIRouter(prefix="/executions", tags=["executions"])


@router.post("", response_model=ExecutionOut, status_code=201, summary="Start an execution (agent token required)")
def start(body: ExecutionCreate, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    ex = svc.start_execution(forge, s, p, **body.model_dump())
    s.commit()
    return ex


@router.get("", response_model=list[ExecutionOut])
def list_executions(s: SessionDep, _: PrincipalDep, repository_id: str | None = None, task_id: str | None = None,
                    workspace_id: str | None = None, agent_id: str | None = None, status: str | None = None,
                    limit: int = 100):
    q = select(Execution).order_by(Execution.started_at.desc()).limit(limit)
    for value, model, col in ((repository_id, Repository, Execution.repository_id), (task_id, Task, Execution.task_id),
                              (workspace_id, Workspace, Execution.workspace_id), (agent_id, Agent, Execution.agent_id)):
        if value:
            q = q.where(col == get_or_404(s, model, value).id)
    if status:
        q = q.where(Execution.status == status.upper())
    return s.execute(q).scalars().all()


@router.get("/{ref}", response_model=ExecutionDetail)
def get_execution(ref: str, s: SessionDep, _: PrincipalDep):
    ex = get_or_404(s, Execution, ref, "execution")
    events = s.execute(select(Event).where(Event.execution_id == ex.id).order_by(Event.seq)).scalars().all()
    return ExecutionDetail(
        **ExecutionOut.model_validate(ex).model_dump(),
        tool_calls=sorted(ex.tool_calls, key=lambda c: c.sequence),
        artifacts=s.execute(select(Artifact).where(Artifact.execution_id == ex.id).order_by(Artifact.created_at)
                            ).scalars().all(),
        changes=s.execute(select(Change).where(Change.execution_id == ex.id).order_by(Change.created_at)
                          ).scalars().all(),
        events=[event_to_dict(e) for e in events],
    )


@router.post("/{ref}/tools/{tool}", summary="Call a mediated tool (owning agent only)")
def call_tool(ref: str, tool: str, body: ToolCallIn, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    """Tools: ``read_file {path}``, ``write_file {path, content, encoding?}``, ``delete_file {path}``,
    ``list_files {prefix?}``, ``run_command {argv | command, timeout?}``."""
    ex = get_or_404(s, Execution, ref, "execution")
    result = svc.run_tool(forge, s, p, ex, tool, body.args)
    s.commit()
    return result


@router.post("/{ref}/finish", response_model=ExecutionOut)
def finish(ref: str, body: ExecutionFinish, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    ex = svc.finish_execution(forge, s, p, get_or_404(s, Execution, ref, "execution"), **body.model_dump())
    s.commit()
    return ex


@router.post("/{ref}/reproduce", summary="Replay an execution and report what could and could not be reproduced")
def reproduce(ref: str, body: ReproduceIn, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    report = reproduce_execution(forge, s, p, get_or_404(s, Execution, ref, "execution"), keep=body.keep_workspace)
    s.commit()
    return report
