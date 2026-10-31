"""Workspaces (isolated git worktrees) and checkpoints."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from ff_merge import RangeAnalysis, analyze_range
from ff_provenance import build_trailers
from ff_semantic import SemanticDiff, semantic_diff
from ff_version import DiffResult
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal
from ..core import Forge, ForgeError, InvalidState, PermissionDenied, get_or_404
from ..events import Actor, record_event
from ..models import (
    WORKSPACE_TRANSITIONS,
    Agent,
    Change,
    Checkpoint,
    Execution,
    Repository,
    Task,
    Workspace,
    WorkspaceStatus,
)
from .registry import repo_head, repo_path, set_task_status

DEFAULT_PERMISSIONS: dict[str, Any] = {
    "write_paths": ["**"],
    "read_only_paths": [],
    "commands": None,  # None → sandbox default allow list
    "network": "none",
}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "task"


def ws_path(ws: Workspace) -> Path:
    return Path(ws.path)


def create_workspace(
    forge: Forge, s: Session, p: Principal, *, task_id: uuid.UUID | str, agent_id: uuid.UUID | str | None = None,
    permissions: dict[str, Any] | None = None,
) -> Workspace:
    task = get_or_404(s, Task, task_id, "task")
    if task.status in ("COMPLETED", "CANCELLED"):
        raise InvalidState(f"task is {task.status}")
    repo = task.repository
    agent = get_or_404(s, Agent, agent_id, "agent") if agent_id else task.agent
    if p.type == "agent" and (agent is None or agent.id != p.agent_id):
        raise PermissionDenied("agents may only create workspaces for themselves")
    if agent and task.agent_id is None:
        task.agent_id = agent.id
    perms = {**DEFAULT_PERMISSIONS, **(repo.settings or {}).get("default_permissions", {}), **(permissions or {})}
    unknown = set(perms) - set(DEFAULT_PERMISSIONS)
    if unknown:
        raise ForgeError(f"unknown workspace permissions: {sorted(unknown)}")
    wid = uuid.uuid4()
    base = repo_head(forge, repo)
    branch = f"forgeflow/ws/{str(wid)[:8]}-{_slug(task.title)}"
    path = forge.settings.workspaces_dir / str(repo.id) / str(wid)
    forge.engine.create_worktree(repo_path(repo), path, branch, base)
    ws = Workspace(id=wid, repository_id=repo.id, task_id=task.id, agent_id=agent.id if agent else None,
                   branch=branch, base_commit=base, current_commit=base, path=str(path), permissions=perms)
    s.add(ws)
    s.flush()
    record_event(s, "workspace.created", p.actor, f"Workspace {str(wid)[:8]} created for '{task.title}'",
                 repository_id=repo.id, task_id=task.id, workspace_id=wid, agent_id=ws.agent_id,
                 subject=("workspace", wid), payload={"branch": branch, "base_commit": base})
    return ws


def transition(s: Session, ws: Workspace, status: WorkspaceStatus | str, actor: Actor, reason: str = "") -> None:
    new = WorkspaceStatus(status)
    old = WorkspaceStatus(ws.status)
    if new == old and new not in WORKSPACE_TRANSITIONS[old]:
        return
    if new not in WORKSPACE_TRANSITIONS[old]:
        raise InvalidState(f"workspace cannot move from {old.value} to {new.value}")
    ws.status = new.value
    if new != old:
        record_event(s, "workspace.status_changed", actor, f"Workspace {str(ws.id)[:8]} {old.value} → {new.value}" +
                     (f": {reason}" if reason else ""), repository_id=ws.repository_id, task_id=ws.task_id,
                     workspace_id=ws.id, agent_id=ws.agent_id, subject=("workspace", ws.id),
                     payload={"from": old.value, "to": new.value})


def abandon_workspace(forge: Forge, s: Session, p: Principal, ws: Workspace, reason: str = "") -> Workspace:
    running = s.execute(select(Execution).where(Execution.workspace_id == ws.id, Execution.status == "RUNNING")
                        ).scalars().first()
    if running:
        raise InvalidState("workspace has a running execution; finish or cancel it first")
    transition(s, ws, WorkspaceStatus.ABANDONED, p.actor, reason)
    return ws


# ------------------------------------------------------------------ analysis
def committed_analysis(forge: Forge, ws: Workspace) -> RangeAnalysis:
    return analyze_range(forge.engine, repo_path(ws.repository), ws.base_commit, ws.current_commit)


def worktree_analysis(forge: Forge, ws: Workspace) -> tuple[DiffResult, SemanticDiff]:
    """Diff of the base commit against the live worktree, including uncommitted edits."""
    path = ws_path(ws)
    diff = forge.engine.diff_worktree(path, ws.base_commit)
    rp = repo_path(ws.repository)
    old: dict[str, bytes | None] = {}
    new: dict[str, bytes | None] = {}
    for f in diff.files:
        old[f.path] = forge.engine.read_file(rp, ws.base_commit, f.path) if f.status != "A" else None
        disk = path / f.path
        new[f.path] = disk.read_bytes() if f.status != "D" and disk.is_file() else None
    return diff, semantic_diff(old, new)


# ---------------------------------------------------------------- checkpoints
def create_checkpoint(
    forge: Forge, s: Session, actor: Actor, ws: Workspace, message: str | None = None,
    execution: Execution | None = None, created_by: str | None = None,
) -> Checkpoint | None:
    if ws.status in ("MERGED", "ABANDONED"):
        raise InvalidState(f"workspace is {ws.status}")
    if execution is None:
        execution = s.execute(select(Execution).where(Execution.workspace_id == ws.id)
                              .order_by(Execution.started_at.desc())).scalars().first()
    agent = ws.agent
    task = ws.task
    cid = uuid.uuid4()
    trailers = build_trailers(
        execution=execution.id if execution else None, agent=agent.id if agent else None, task=task.id,
        workspace=ws.id, model=(f"{execution.model}" + (f"@{execution.model_version}" if execution.model_version
                                                        else "")) if execution else None,
        checkpoint=cid, kind="checkpoint",
    )
    author = f"{agent.name} <{agent.name}@agents.forgeflow>" if agent else f"{created_by or actor.id} <human@forgeflow>"
    msg = message or f"Checkpoint for '{task.title}'"
    path = ws_path(ws)
    parent = forge.engine.head(path)
    commit = forge.engine.commit_all(path, msg, author, trailers)
    if commit is None:
        return None
    rp = repo_path(ws.repository)
    analysis = analyze_range(forge.engine, rp, parent, commit)
    files = forge.engine.list_files(rp, commit)
    cp = Checkpoint(
        id=cid, workspace_id=ws.id, task_id=task.id, execution_id=execution.id if execution else None,
        commit_sha=commit, parent_commit=parent, tree_id=forge.engine.tree_id(rp, commit), message=msg,
        task_state={"status": task.status, "title": task.title, "workspace_status": ws.status},
        filesystem={"files": len(files), "changed": len(analysis.diff.files),
                    "additions": analysis.diff.additions, "deletions": analysis.diff.deletions},
        created_by=created_by or actor.id,
    )
    s.add(cp)
    s.flush()
    by_path: dict[str, list[dict]] = {}
    for c in analysis.semantic.changes:
        by_path.setdefault(c.path, []).append(c.to_dict())
    for f in analysis.diff.files:
        s.add(Change(
            repository_id=ws.repository_id, task_id=task.id, workspace_id=ws.id,
            execution_id=execution.id if execution else None, agent_id=agent.id if agent else None,
            checkpoint_id=cid, commit_sha=commit, parent_commit=parent, path=f.path, change_type=f.status,
            additions=f.additions, deletions=f.deletions, semantic=by_path.get(f.path, []),
        ))
    ws.current_commit = commit
    if execution and execution.status == "RUNNING":
        execution.result_commit = commit
    if ws.status in ("CREATED", "REVIEW"):
        transition(s, ws, WorkspaceStatus.CHECKPOINTED, actor, "new checkpoint")
    record_event(s, "checkpoint.created", actor, f"Checkpoint {commit[:10]}: {msg} "
                 f"({len(analysis.diff.files)} files, +{analysis.diff.additions}/-{analysis.diff.deletions})",
                 repository_id=ws.repository_id, task_id=task.id, workspace_id=ws.id,
                 execution_id=execution.id if execution else None, agent_id=ws.agent_id,
                 subject=("checkpoint", cid),
                 payload={"commit": commit, "files": [f.path for f in analysis.diff.files],
                          "semantic": analysis.semantic.stats()})
    return cp


def restore_checkpoint(forge: Forge, s: Session, p: Principal, cp: Checkpoint) -> Workspace:
    ws = get_or_404(s, Workspace, cp.workspace_id)
    if ws.status in ("MERGED", "ABANDONED"):
        raise InvalidState(f"workspace is {ws.status}")
    if p.type == "agent" and ws.agent_id != p.agent_id:
        raise PermissionDenied("agents may only restore their own workspaces")
    forge.engine.reset_hard(ws_path(ws), cp.commit_sha)
    ws.current_commit = cp.commit_sha
    if ws.status == "REVIEW":
        transition(s, ws, WorkspaceStatus.CHECKPOINTED, p.actor, "checkpoint restored")
    record_event(s, "checkpoint.restored", p.actor, f"Workspace {str(ws.id)[:8]} restored to {cp.commit_sha[:10]}",
                 repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, agent_id=ws.agent_id,
                 subject=("checkpoint", cp.id), payload={"commit": cp.commit_sha, "task_state": cp.task_state})
    return ws


def mark_task_running(s: Session, task: Task, actor: Actor) -> None:
    if task.status in ("PENDING", "BLOCKED", "FAILED", "REVIEW"):
        set_task_status(s, task, "RUNNING", actor)


__all__ = ["DEFAULT_PERMISSIONS", "abandon_workspace", "committed_analysis", "create_checkpoint", "create_workspace",
           "mark_task_running", "restore_checkpoint", "transition", "worktree_analysis", "ws_path", "Repository"]
