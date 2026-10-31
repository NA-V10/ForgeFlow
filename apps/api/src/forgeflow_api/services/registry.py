"""Repositories, agents and tasks."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, new_agent_token, require_human
from ..core import Forge, ForgeError, InvalidState, get_or_404
from ..db import utcnow
from ..events import record_event
from ..models import Agent, Repository, Task, TaskStatus

NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")
PRIORITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")
TASK_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"RUNNING", "BLOCKED", "CANCELLED", "FAILED"},
    "RUNNING": {"BLOCKED", "REVIEW", "FAILED", "CANCELLED", "COMPLETED", "PENDING"},
    "BLOCKED": {"RUNNING", "PENDING", "REVIEW", "CANCELLED", "FAILED"},
    "REVIEW": {"RUNNING", "COMPLETED", "BLOCKED", "FAILED", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": {"PENDING", "RUNNING"},
    "CANCELLED": set(),
}


def _validate_name(name: str, what: str) -> None:
    if not NAME_RE.match(name):
        raise ForgeError(f"{what} name must match {NAME_RE.pattern}")


# ---------------------------------------------------------------- repositories
def create_repository(
    forge: Forge, s: Session, p: Principal, *, name: str, description: str = "", source_url: str | None = None,
    default_branch: str = "main", initial_files: dict[str, str] | None = None, settings: dict[str, Any] | None = None,
) -> Repository:
    require_human(p, "register repositories")
    _validate_name(name, "repository")
    if s.execute(select(Repository).where(Repository.name == name)).scalar_one_or_none():
        raise InvalidState(f"repository '{name}' already exists")
    rid = uuid.uuid4()
    path = forge.settings.repos_dir / f"{rid}.git"
    if source_url:
        forge.engine.import_repository(source_url, path)
        default_branch = forge.engine.default_branch(path)
    else:
        files = {k: v.encode() for k, v in (initial_files or {}).items()} or None
        forge.engine.init_repository(path, default_branch, files)
    repo = Repository(id=rid, name=name, description=description, default_branch=default_branch,
                      storage_path=str(path), source_url=source_url, engine=forge.engine.name,
                      settings=settings or {})
    s.add(repo)
    s.flush()
    head = forge.engine.branch_head(path, default_branch)
    record_event(s, "repository.created", p.actor, f"Repository {name} registered", repository_id=rid,
                 subject=("repository", rid), payload={"default_branch": default_branch, "head": head,
                                                        "source_url": source_url})
    return repo


def update_repository_settings(s: Session, p: Principal, repo: Repository, settings: dict[str, Any]) -> Repository:
    require_human(p, "change repository settings")
    allowed = {"test_command", "require_tests", "test_timeout", "default_permissions"}
    unknown = set(settings) - allowed
    if unknown:
        raise ForgeError(f"unknown repository settings: {sorted(unknown)}")
    repo.settings = {**(repo.settings or {}), **settings}
    record_event(s, "repository.updated", p.actor, f"Repository {repo.name} settings updated",
                 repository_id=repo.id, subject=("repository", repo.id), payload={"settings": settings})
    return repo


def repo_path(repo: Repository) -> Path:
    return Path(repo.storage_path)


def repo_head(forge: Forge, repo: Repository) -> str:
    head = forge.engine.branch_head(repo_path(repo), repo.default_branch)
    if head is None:
        raise InvalidState(f"repository {repo.name} has no {repo.default_branch} branch")
    return head


# ---------------------------------------------------------------------- agents
def create_agent(
    s: Session, p: Principal, *, name: str, model: str, model_version: str | None = None, provider: str | None = None,
    kind: str = "scripted", description: str = "", capabilities: list[str] | None = None,
    repository_id: uuid.UUID | None = None,
) -> tuple[Agent, str]:
    require_human(p, "register agents")
    _validate_name(name, "agent")
    if s.execute(select(Agent).where(Agent.name == name)).scalar_one_or_none():
        raise InvalidState(f"agent '{name}' already exists")
    if repository_id:
        get_or_404(s, Repository, repository_id)
    token, token_hash = new_agent_token()
    agent = Agent(name=name, model=model, model_version=model_version, provider=provider, kind=kind,
                  description=description, capabilities=capabilities or [], repository_id=repository_id,
                  token_hash=token_hash)
    s.add(agent)
    s.flush()
    record_event(s, "agent.created", p.actor, f"Agent {name} registered ({model})", agent_id=agent.id,
                 repository_id=repository_id, subject=("agent", agent.id),
                 payload={"model": model, "model_version": model_version, "kind": kind})
    return agent, token


def rotate_agent_token(s: Session, p: Principal, agent: Agent) -> str:
    require_human(p, "rotate agent tokens")
    token, token_hash = new_agent_token()
    agent.token_hash = token_hash
    record_event(s, "agent.token_rotated", p.actor, f"Token rotated for {agent.name}", agent_id=agent.id,
                 subject=("agent", agent.id))
    return token


# ----------------------------------------------------------------------- tasks
def create_task(
    forge: Forge, s: Session, p: Principal, *, repository_id: uuid.UUID | str, title: str, description: str = "",
    priority: str = "MEDIUM", agent_id: uuid.UUID | str | None = None, labels: list[str] | None = None,
) -> Task:
    repo = get_or_404(s, Repository, repository_id, "repository")
    title = title.strip()
    if not title:
        raise ForgeError("task title is required")
    priority = priority.upper()
    if priority not in PRIORITIES:
        raise ForgeError(f"priority must be one of {', '.join(PRIORITIES)}")
    agent = get_or_404(s, Agent, agent_id, "agent") if agent_id else None
    task = Task(repository_id=repo.id, title=title, description=description, priority=priority,
                agent_id=agent.id if agent else None, labels=labels or [], base_commit=repo_head(forge, repo),
                created_by=p.name)
    s.add(task)
    s.flush()
    record_event(s, "task.created", p.actor, f"Task created: {title}", repository_id=repo.id, task_id=task.id,
                 agent_id=task.agent_id, subject=("task", task.id),
                 payload={"title": title, "priority": priority, "base_commit": task.base_commit})
    return task


def set_task_status(s: Session, task: Task, status: str, actor, reason: str = "") -> None:
    status = TaskStatus(status).value
    if status == task.status:
        return
    if status not in TASK_TRANSITIONS[task.status]:
        raise InvalidState(f"task cannot move from {task.status} to {status}")
    old = task.status
    task.status = status
    if status == "RUNNING" and task.started_at is None:
        task.started_at = utcnow()
    if status in ("COMPLETED", "FAILED", "CANCELLED"):
        task.completed_at = utcnow()
    record_event(s, "task.status_changed", actor, f"Task '{task.title}' {old} → {status}" +
                 (f": {reason}" if reason else ""), repository_id=task.repository_id, task_id=task.id,
                 agent_id=task.agent_id, subject=("task", task.id), payload={"from": old, "to": status})


def assign_task(s: Session, p: Principal, task: Task, agent_id: uuid.UUID | str | None) -> Task:
    agent = get_or_404(s, Agent, agent_id, "agent") if agent_id else None
    task.agent_id = agent.id if agent else None
    record_event(s, "task.assigned", p.actor, f"Task '{task.title}' assigned to {agent.name if agent else 'nobody'}",
                 repository_id=task.repository_id, task_id=task.id, agent_id=task.agent_id, subject=("task", task.id))
    return task

