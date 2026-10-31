from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from sqlalchemy import select

from ..auth import resolve_principal
from ..core import NotFound, get_or_404
from ..deps import ForgeDep, PrincipalDep, SessionDep
from ..events import event_to_dict, verify_chain
from ..models import Agent, Artifact, Change, Event, Execution, Repository, Task, Workspace
from ..schemas import ArtifactOut, ChangeOut, DashboardOut, EventOut
from ..services import command_center, insight

router = APIRouter(tags=["observability"])

_FILTERS = ("repository_id", "task_id", "workspace_id", "execution_id", "agent_id")


@router.get("/events", response_model=list[EventOut], summary="Audit events (immutable, hash-chained)")
def list_events(s: SessionDep, _: PrincipalDep, repository_id: str | None = None, task_id: str | None = None,
                workspace_id: str | None = None, execution_id: str | None = None, agent_id: str | None = None,
                type: str | None = Query(None, description="exact type or prefix ending in '.' e.g. 'merge.'"),
                after_seq: int | None = None, limit: int = Query(100, le=1000), order: str = "desc"):
    q = select(Event)
    for value, model, col in ((repository_id, Repository, Event.repository_id), (task_id, Task, Event.task_id),
                              (workspace_id, Workspace, Event.workspace_id),
                              (execution_id, Execution, Event.execution_id), (agent_id, Agent, Event.agent_id)):
        if value:
            q = q.where(col == get_or_404(s, model, value).id)
    if type:
        q = q.where(Event.type.startswith(type) if type.endswith(".") else Event.type == type)
    if after_seq is not None:
        q = q.where(Event.seq > after_seq)
    q = q.order_by(Event.seq.desc() if order == "desc" else Event.seq).limit(limit)
    return [event_to_dict(e) for e in s.execute(q).scalars()]


@router.get("/events/verify", summary="Verify the integrity of the audit hash chain")
def verify(s: SessionDep, _: PrincipalDep):
    return verify_chain(s)


@router.websocket("/ws/events")
async def events_ws(websocket: WebSocket, token: str | None = None, backfill: int = 50):
    """Real-time event stream. Optional query filters: repository_id, task_id, workspace_id, execution_id, agent_id."""
    forge = websocket.app.state.forge
    with forge.session() as s:
        try:
            resolve_principal(s, f"Bearer {token}" if token else None, forge.settings)
        except Exception:  # noqa: BLE001
            await websocket.close(code=4401)
            return
        filters = {k: websocket.query_params[k] for k in _FILTERS if websocket.query_params.get(k)}
        await websocket.accept()
        q = select(Event).order_by(Event.seq.desc()).limit(max(0, min(backfill, 500)))
        recent = [event_to_dict(e) for e in s.execute(q).scalars()]
    for e in reversed(recent):
        if all(e.get(k) == v for k, v in filters.items()):
            await websocket.send_json(e)

    async def pump():
        async for e in forge.bus.subscribe():
            if all(e.get(k) == v for k, v in filters.items()):
                await websocket.send_json(e)

    task = asyncio.create_task(pump())
    try:
        while True:
            await websocket.receive_text()  # keep-alive pings from the client; disconnect ends the loop
    except WebSocketDisconnect:
        pass
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(s: SessionDep, _: PrincipalDep):
    return insight.dashboard(s)


@router.get("/inbox", summary="Everything waiting on a human, ranked P0-P2 deterministically")
def get_inbox(s: SessionDep, _: PrincipalDep):
    return command_center.inbox(s)


@router.get("/threads", summary="Per-workspace agent thread summaries for the command center")
def get_threads(s: SessionDep, _: PrincipalDep, limit: int = Query(60, le=200), include_closed: bool = True):
    return command_center.threads(s, limit, include_closed)


@router.get("/changes", response_model=list[ChangeOut], summary="File-level changes with provenance")
def list_changes(s: SessionDep, _: PrincipalDep, repository_id: str | None = None, task_id: str | None = None,
                 workspace_id: str | None = None, execution_id: str | None = None, agent_id: str | None = None,
                 limit: int = Query(200, le=2000)):
    q = select(Change).order_by(Change.created_at.desc()).limit(limit)
    for value, model, col in ((repository_id, Repository, Change.repository_id), (task_id, Task, Change.task_id),
                              (workspace_id, Workspace, Change.workspace_id),
                              (execution_id, Execution, Change.execution_id), (agent_id, Agent, Change.agent_id)):
        if value:
            q = q.where(col == get_or_404(s, model, value).id)
    return s.execute(q).scalars().all()


@router.get("/artifacts", response_model=list[ArtifactOut])
def list_artifacts(s: SessionDep, _: PrincipalDep, execution_id: str | None = None, limit: int = 200):
    q = select(Artifact).order_by(Artifact.created_at.desc()).limit(limit)
    if execution_id:
        q = q.where(Artifact.execution_id == get_or_404(s, Execution, execution_id).id)
    return s.execute(q).scalars().all()


@router.get("/artifacts/{ref}/content", summary="Download artifact content")
def artifact_content(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep):
    a = get_or_404(s, Artifact, ref, "artifact")
    data = forge.store.get(a.storage_key)
    if data is None:
        raise NotFound("artifact content missing from storage")
    return Response(content=data, media_type=a.content_type,
                    headers={"Content-Disposition": f'inline; filename="{a.name}"'})


@router.get("/settings", summary="Runtime configuration (no secrets)")
def runtime_settings(forge: ForgeDep, p: PrincipalDep):
    st = forge.settings
    return {
        "principal": {"type": p.type, "name": p.name},
        "auth_mode": st.auth_mode,
        "database": "postgresql" if (st.database_url or "").startswith("postgresql") else "sqlite",
        "event_bus": "redis" if st.redis_url else "in-process",
        "artifact_store": forge.store.backend,
        "version_engine": forge.engine.name,
        "sandbox": forge.environment(),
        "command_timeout": st.command_timeout,
    }
