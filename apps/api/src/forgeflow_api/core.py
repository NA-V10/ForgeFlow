"""Process-wide context shared by services: settings, version engine, storage, sandbox, event bus."""

from __future__ import annotations

import platform
import sys
import uuid
from dataclasses import dataclass
from typing import Any, TypeVar

from ff_policy import DEFAULT_POLICY_YAML, PolicySet
from ff_sandbox import CommandPolicy, DockerSandbox, LocalSandbox, NetworkPolicy
from ff_version import GitEngine
from sqlalchemy import String, cast, func, select
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .db import Base
from .events import EventBus
from .models import Policy
from .storage import ArtifactStore

T = TypeVar("T", bound=Base)


class ForgeError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(ForgeError):
    status_code, code = 404, "not_found"


class InvalidState(ForgeError):
    status_code, code = 409, "invalid_state"


class PermissionDenied(ForgeError):
    status_code, code = 403, "forbidden"


class PolicyDenied(ForgeError):
    status_code, code = 403, "policy_denied"


@dataclass
class Forge:
    settings: Settings
    engine: GitEngine
    store: ArtifactStore
    bus: EventBus
    session_factory: sessionmaker[Session]

    def session(self) -> Session:
        s = self.session_factory()
        s.info["ff_bus"] = self.bus
        return s

    def sandbox(self, permissions: dict[str, Any] | None = None):
        permissions = permissions or {}
        policy = CommandPolicy()
        if permissions.get("commands"):
            policy.allowed_executables = list(permissions["commands"])
        if permissions.get("deny_commands"):
            policy.deny_patterns = policy.deny_patterns + list(permissions["deny_commands"])
        network = NetworkPolicy(mode=permissions.get("network", self.settings.network_policy))
        if self.settings.sandbox == "docker":
            return DockerSandbox(image=self.settings.sandbox_image, policy=policy, network=network)
        return LocalSandbox(policy=policy, network=network)

    def environment(self, permissions: dict[str, Any] | None = None) -> dict[str, Any]:
        sb = self.sandbox(permissions)
        return {
            "sandbox": sb.name,
            "guarantees": sb.guarantees(),
            "network_policy": sb.network.mode,
            "allowed_commands": sb.policy.allowed_executables,
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "version_engine": self.engine.name,
        }


def get_or_404(session: Session, model: type[T], id_: Any, label: str | None = None) -> T:
    """Look up by UUID, by unique UUID prefix (≥ 4 hex chars) or, for named entities, by name."""
    label = label or model.__name__.lower()
    obj = None
    if isinstance(id_, uuid.UUID):
        obj = session.get(model, id_)
    else:
        ref = str(id_).strip()
        try:
            obj = session.get(model, uuid.UUID(ref))
        except ValueError:
            pass
        cols = model.__table__.c
        if obj is None and "name" in cols:
            obj = session.execute(select(model).where(cols.name == ref)).scalar_one_or_none()
        compact = ref.replace("-", "").lower()
        if obj is None and 4 <= len(compact) < 32 and all(ch in "0123456789abcdef" for ch in compact):
            id_text = func.replace(cast(cols.id, String), "-", "")
            rows = session.execute(select(model).where(id_text.like(compact + "%")).limit(2)).scalars().all()
            if len(rows) > 1:
                raise ForgeError(f"{label} id prefix '{ref}' is ambiguous")
            obj = rows[0] if rows else None
    if obj is None:
        raise NotFound(f"{label} {id_} not found")
    return obj


def policy_documents(session: Session, repository_id: uuid.UUID | None) -> list[Policy]:
    scopes = ["global"] + ([str(repository_id)] if repository_id else [])
    rows = session.execute(
        select(Policy).where(Policy.scope.in_(scopes), Policy.active.is_(True)).order_by(Policy.version)
    ).scalars().all()
    latest: dict[str, Policy] = {}
    for r in rows:
        latest[r.scope] = r
    return [latest[s] for s in scopes if s in latest]


def effective_policies(session: Session, repository_id: uuid.UUID | None) -> PolicySet:
    """Global policies followed by repository policies.

    A repository policy with the same name as a global one replaces it in place;
    the most specific ``default`` wins.
    """
    docs = policy_documents(session, repository_id)
    if not docs:
        return PolicySet.from_yaml(DEFAULT_POLICY_YAML)
    by_name: dict[str, Any] = {}
    default = "allow"
    for d in docs:
        ps = PolicySet.from_yaml(d.document)
        for p in ps.policies:
            by_name[p.name] = p
        default = ps.default
    return PolicySet(policies=list(by_name.values()), default=default)
