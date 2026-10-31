from __future__ import annotations

from fastapi import APIRouter

from ..core import InvalidState, get_or_404
from ..deps import ForgeDep, PrincipalDep, SessionDep
from ..models import Merge, Repository, Workspace
from ..schemas import MergeCreate, MergeOut, RollbackIn
from ..services import merges as svc

router = APIRouter(prefix="/merges", tags=["merges"])


def _out(m: Merge, position: int | None = None) -> MergeOut:
    out = MergeOut.model_validate(m)
    out.position = position
    return out


@router.post("", response_model=MergeOut, status_code=201,
             summary="Queue a workspace for merge and run the merge gate")
def create_merge(body: MergeCreate, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    """Runs: verify base → textual conflicts → semantic conflicts → policies → risk → tests → approvals.
    With ``execute=true`` the merge is performed when the decision is READY."""
    ws = get_or_404(s, Workspace, body.workspace_id, "workspace")
    m = svc.enqueue_merge(forge, s, p, ws)
    s.flush()
    if body.execute:
        try:
            svc.execute_merge(forge, s, p, m)
        except InvalidState:
            s.commit()
            s.refresh(m)
            return _out(m)
    else:
        svc.evaluate_merge(forge, s, p.actor, m)
    s.commit()
    return _out(m)


@router.get("", response_model=list[MergeOut], summary="Merge queue (open merges have a position)")
def list_merges(s: SessionDep, _: PrincipalDep, repository_id: str | None = None, open_only: bool = False):
    rid = get_or_404(s, Repository, repository_id, "repository").id if repository_id else None
    rows = svc.queue_view(s, rid)
    return [_out(r["merge"], r["position"]) for r in rows if not open_only or r["position"]]


@router.get("/{ref}", response_model=MergeOut)
def get_merge(ref: str, s: SessionDep, _: PrincipalDep):
    return _out(get_or_404(s, Merge, ref, "merge"))


@router.post("/{ref}/evaluate", response_model=MergeOut, summary="Re-run the merge gate")
def evaluate(ref: str, forge: ForgeDep, s: SessionDep, p: PrincipalDep, run_tests: bool = True):
    m = get_or_404(s, Merge, ref, "merge")
    if m.status in ("MERGED", "ROLLED_BACK"):
        raise InvalidState(f"merge is {m.status}")
    svc.evaluate_merge(forge, s, p.actor, m, run_tests=run_tests)
    s.commit()
    return _out(m)


@router.post("/{ref}/execute", response_model=MergeOut, summary="Merge if (and only if) the gate returns READY")
def execute(ref: str, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    m = svc.execute_merge(forge, s, p, get_or_404(s, Merge, ref, "merge"))
    s.commit()
    return _out(m)


@router.post("/{ref}/rollback", response_model=MergeOut, summary="Revert a completed merge on the target branch")
def rollback(ref: str, body: RollbackIn, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    m = svc.rollback_merge(forge, s, p, get_or_404(s, Merge, ref, "merge"), body.reason)
    s.commit()
    return _out(m)
