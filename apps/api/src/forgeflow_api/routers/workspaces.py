from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..auth import Principal
from ..core import InvalidState, NotFound, PermissionDenied, get_or_404
from ..deps import ForgeDep, PrincipalDep, SessionDep
from ..models import Agent, Checkpoint, Repository, Task, Workspace
from ..schemas import CheckpointCreate, CheckpointOut, DiffOut, FileChangeOut, WorkspaceCreate, WorkspaceOut
from ..services import workspaces as svc
from ..services.merges import open_changesets

router = APIRouter(tags=["workspaces"])


def ws_out(ws: Workspace, p: Principal) -> WorkspaceOut:
    out = WorkspaceOut.model_validate(ws)
    out.path = ws.path if p.is_human else None  # never disclose host paths to agents
    return out


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, summary="Create an isolated workspace")
def create_workspace(body: WorkspaceCreate, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    ws = svc.create_workspace(forge, s, p, **body.model_dump())
    s.commit()
    return ws_out(ws, p)


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(s: SessionDep, p: PrincipalDep, repository_id: str | None = None, task_id: str | None = None,
                    agent_id: str | None = None, status: str | None = None):
    q = select(Workspace).order_by(Workspace.created_at.desc())
    if repository_id:
        q = q.where(Workspace.repository_id == get_or_404(s, Repository, repository_id, "repository").id)
    if task_id:
        q = q.where(Workspace.task_id == get_or_404(s, Task, task_id, "task").id)
    if agent_id:
        q = q.where(Workspace.agent_id == get_or_404(s, Agent, agent_id, "agent").id)
    if status:
        q = q.where(Workspace.status == status.upper())
    return [ws_out(w, p) for w in s.execute(q).scalars()]


@router.get("/workspaces/{ref}", response_model=WorkspaceOut)
def get_workspace(ref: str, s: SessionDep, p: PrincipalDep):
    return ws_out(get_or_404(s, Workspace, ref, "workspace"), p)


@router.get("/workspaces/{ref}/diff", response_model=DiffOut, summary="Standard and semantic diff")
def diff(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep, semantic: bool = True,
         uncommitted: bool = True):
    """Diff the workspace against its base commit. With ``uncommitted`` (default) the live worktree is included."""
    ws = get_or_404(s, Workspace, ref, "workspace")
    live = uncommitted and ws.status not in ("MERGED", "ABANDONED")
    if live:
        d, sem = svc.worktree_analysis(forge, ws)
    else:
        a = svc.committed_analysis(forge, ws)
        d, sem = a.diff, a.semantic
    return DiffOut(
        base=ws.base_commit, head="WORKTREE" if live else ws.current_commit,
        files=[FileChangeOut(**f.__dict__) for f in d.files], additions=d.additions, deletions=d.deletions,
        patch=d.patch, semantic=sem.to_dict() if semantic else None, summary=sem.summary_text() if semantic else None,
        includes_uncommitted=live,
    )


@router.get("/workspaces/{ref}/conflicts", summary="Semantic conflicts with other open workspaces")
def conflicts(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep):
    from ff_merge import analyze_range
    from ff_semantic import detect_semantic_conflicts

    ws = get_or_404(s, Workspace, ref, "workspace")
    rp = svc.repo_path(ws.repository)
    if ws.current_commit == ws.base_commit:
        return {"workspace_id": str(ws.id), "conflicts": []}
    mine = analyze_range(forge.engine, rp, ws.base_commit, ws.current_commit).changeset(
        forge.engine, rp, f"{ws.agent.name if ws.agent else 'workspace'} ({str(ws.id)[:8]})")
    out = []
    for other in open_changesets(forge, s, ws):
        for c in detect_semantic_conflicts(other.changeset, mine):
            out.append({"with": other.name, **c.to_dict()})
    return {"workspace_id": str(ws.id), "conflicts": out}


@router.get("/workspaces/{ref}/file", summary="Read a file from the live workspace")
def read_file(ref: str, path: str, s: SessionDep, _: PrincipalDep):
    from ff_sandbox import BoundaryViolation, confine

    ws = get_or_404(s, Workspace, ref, "workspace")
    try:
        target = confine(svc.ws_path(ws), path)
    except BoundaryViolation as exc:
        raise PermissionDenied(str(exc)) from exc
    if not target.is_file():
        raise NotFound(f"{path} not found")
    return {"path": path, "content": target.read_bytes().decode("utf-8", "replace")}


@router.post("/workspaces/{ref}/abandon", response_model=WorkspaceOut)
def abandon(ref: str, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    ws = get_or_404(s, Workspace, ref, "workspace")
    if p.type == "agent" and ws.agent_id != p.agent_id:
        raise PermissionDenied("agents may only abandon their own workspaces")
    svc.abandon_workspace(forge, s, p, ws)
    s.commit()
    return ws_out(ws, p)


# ---------------------------------------------------------------- checkpoints
@router.post("/workspaces/{ref}/checkpoints", response_model=CheckpointOut, status_code=201, tags=["workspaces"])
def create_checkpoint(ref: str, body: CheckpointCreate, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    ws = get_or_404(s, Workspace, ref, "workspace")
    if p.type == "agent" and ws.agent_id != p.agent_id:
        raise PermissionDenied("agents may only checkpoint their own workspaces")
    cp = svc.create_checkpoint(forge, s, p.actor, ws, body.message, created_by=p.name)
    if cp is None:
        raise InvalidState("nothing to checkpoint: the workspace has no uncommitted changes")
    s.commit()
    return cp


@router.get("/checkpoints", response_model=list[CheckpointOut])
def list_checkpoints(s: SessionDep, _: PrincipalDep, workspace_id: str | None = None, task_id: str | None = None):
    q = select(Checkpoint).order_by(Checkpoint.created_at)
    if workspace_id:
        q = q.where(Checkpoint.workspace_id == get_or_404(s, Workspace, workspace_id, "workspace").id)
    if task_id:
        q = q.where(Checkpoint.task_id == get_or_404(s, Task, task_id, "task").id)
    return s.execute(q).scalars().all()


@router.get("/checkpoints/{ref}", response_model=CheckpointOut)
def get_checkpoint(ref: str, s: SessionDep, _: PrincipalDep):
    return get_or_404(s, Checkpoint, ref, "checkpoint")


@router.post("/checkpoints/{ref}/restore", response_model=WorkspaceOut)
def restore_checkpoint(ref: str, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    ws = svc.restore_checkpoint(forge, s, p, get_or_404(s, Checkpoint, ref, "checkpoint"))
    s.commit()
    return ws_out(ws, p)
