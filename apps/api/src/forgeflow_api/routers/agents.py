from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from ..core import get_or_404
from ..deps import PrincipalDep, SessionDep
from ..models import Agent
from ..schemas import AgentCreate, AgentCreated, AgentOut
from ..services import registry

router = APIRouter(prefix="/agents", tags=["agents"])


@router.post("", response_model=AgentCreated, status_code=201, summary="Register an agent and issue its token")
def create_agent(body: AgentCreate, s: SessionDep, p: PrincipalDep):
    agent, token = registry.create_agent(s, p, **body.model_dump())
    s.commit()
    return AgentCreated(**AgentOut.model_validate(agent).model_dump(), token=token)


@router.get("", response_model=list[AgentOut])
def list_agents(s: SessionDep, _: PrincipalDep, status: str | None = None):
    q = select(Agent).order_by(Agent.created_at)
    if status:
        q = q.where(Agent.status == status.upper())
    return s.execute(q).scalars().all()


@router.get("/me", response_model=AgentOut, summary="The agent authenticated by the bearer token")
def me(s: SessionDep, p: PrincipalDep):
    return get_or_404(s, Agent, p.agent_id or "-", "agent")


@router.get("/{ref}", response_model=AgentOut)
def get_agent(ref: str, s: SessionDep, _: PrincipalDep):
    return get_or_404(s, Agent, ref, "agent")


@router.post("/{ref}/rotate-token", response_model=AgentCreated)
def rotate_token(ref: str, s: SessionDep, p: PrincipalDep):
    agent = get_or_404(s, Agent, ref, "agent")
    token = registry.rotate_agent_token(s, p, agent)
    s.commit()
    return AgentCreated(**AgentOut.model_validate(agent).model_dump(), token=token)
