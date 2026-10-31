"""Principals.

* Agents authenticate with the token issued when the agent was created
  (``Authorization: Bearer ffa_…``). Only the SHA-256 of the token is stored.
* Humans authenticate with the admin token. In ``dev`` auth mode, requests
  without a token act as the configured local human user.

Approval decisions require a human principal; tool calls require the agent that
owns the execution. These checks live in the services, not just the routers.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .events import Actor
from .models import Agent

AGENT_TOKEN_PREFIX = "ffa_"


def new_agent_token() -> tuple[str, str]:
    token = AGENT_TOKEN_PREFIX + secrets.token_urlsafe(32)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    type: str  # human | agent
    id: str
    name: str
    agent_id: uuid.UUID | None = None

    @property
    def is_human(self) -> bool:
        return self.type == "human"

    @property
    def actor(self) -> Actor:
        return Actor(self.type, self.name if self.is_human else str(self.agent_id))


class Forbidden(PermissionError):
    pass


def require_human(p: Principal, action: str) -> None:
    if not p.is_human:
        raise Forbidden(f"only humans may {action}")


def resolve_principal(session: Session, authorization: str | None, settings) -> Principal:
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    if token:
        if token.startswith(AGENT_TOKEN_PREFIX):
            agent = session.execute(select(Agent).where(Agent.token_hash == hash_token(token))).scalar_one_or_none()
            if agent is None or agent.status == "DISABLED":
                raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid agent token")
            return Principal("agent", str(agent.id), agent.name, agent.id)
        if hmac.compare_digest(token, settings.admin_token):
            return Principal("human", "admin", settings.local_user)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    if settings.auth_mode == "dev":
        return Principal("human", "local", settings.local_user)
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "authentication required",
                        headers={"WWW-Authenticate": "Bearer"})


__all__ = ["AGENT_TOKEN_PREFIX", "Forbidden", "Principal", "hash_token", "new_agent_token", "require_human",
           "resolve_principal"]
