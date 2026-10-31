"""Persistence model.

Every application entity uses a UUID primary key. Events are append-only and
hash-chained; the ORM refuses to update or delete them.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, new_id, utcnow


class StrEnum(str, enum.Enum):
    def __str__(self) -> str:  # pragma: no cover
        return self.value


class TaskStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class WorkspaceStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    CHECKPOINTED = "CHECKPOINTED"
    REVIEW = "REVIEW"
    MERGED = "MERGED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


WORKSPACE_TRANSITIONS: dict[WorkspaceStatus, set[WorkspaceStatus]] = {
    WorkspaceStatus.CREATED: {WorkspaceStatus.RUNNING, WorkspaceStatus.CHECKPOINTED, WorkspaceStatus.ABANDONED},
    WorkspaceStatus.RUNNING: {WorkspaceStatus.CHECKPOINTED, WorkspaceStatus.FAILED, WorkspaceStatus.ABANDONED},
    WorkspaceStatus.CHECKPOINTED: {WorkspaceStatus.RUNNING, WorkspaceStatus.REVIEW, WorkspaceStatus.ABANDONED,
                                   WorkspaceStatus.CHECKPOINTED},
    WorkspaceStatus.REVIEW: {WorkspaceStatus.MERGED, WorkspaceStatus.RUNNING, WorkspaceStatus.CHECKPOINTED,
                             WorkspaceStatus.ABANDONED, WorkspaceStatus.REVIEW},
    WorkspaceStatus.FAILED: {WorkspaceStatus.RUNNING, WorkspaceStatus.ABANDONED},
    WorkspaceStatus.MERGED: set(),
    WorkspaceStatus.ABANDONED: set(),
}


class ExecutionStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ApprovalStatus(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class MergeStatus(StrEnum):
    QUEUED = "QUEUED"
    READY = "READY"
    BLOCKED = "BLOCKED"
    REQUIRES_APPROVAL = "REQUIRES_APPROVAL"
    CONFLICT = "CONFLICT"
    MERGED = "MERGED"
    ROLLED_BACK = "ROLLED_BACK"
    FAILED = "FAILED"


OPEN_MERGE_STATUSES = (MergeStatus.QUEUED, MergeStatus.READY, MergeStatus.BLOCKED, MergeStatus.REQUIRES_APPROVAL,
                       MergeStatus.CONFLICT)


class Repository(Base):
    __tablename__ = "repositories"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    default_branch: Mapped[str] = mapped_column(String(200), default="main")
    storage_path: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    engine: Mapped[str] = mapped_column(String(32), default="git")
    settings: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    tasks: Mapped[list[Task]] = relationship(back_populates="repository")
    workspaces: Mapped[list[Workspace]] = relationship(back_populates="repository")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("repositories.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(32), default="scripted")  # scripted | llm | external
    model: Mapped[str] = mapped_column(String(200), default="unspecified")
    model_version: Mapped[str | None] = mapped_column(String(200))
    provider: Mapped[str | None] = mapped_column(String(100))
    capabilities: Mapped[list] = mapped_column(default=list)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    status: Mapped[str] = mapped_column(String(32), default="IDLE", index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.PENDING.value, index=True)
    priority: Mapped[str] = mapped_column(String(16), default="MEDIUM")
    base_commit: Mapped[str] = mapped_column(String(64))
    labels: Mapped[list] = mapped_column(default=list)
    created_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    started_at: Mapped[datetime | None]
    completed_at: Mapped[datetime | None]

    repository: Mapped[Repository] = relationship(back_populates="tasks")
    agent: Mapped[Agent | None] = relationship()


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=WorkspaceStatus.CREATED.value, index=True)
    branch: Mapped[str] = mapped_column(String(300))
    base_commit: Mapped[str] = mapped_column(String(64))
    current_commit: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)  # host path; never returned to agents
    permissions: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    repository: Mapped[Repository] = relationship(back_populates="workspaces")
    task: Mapped[Task] = relationship()
    agent: Mapped[Agent | None] = relationship()


class Execution(Base):
    __tablename__ = "executions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agents.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=ExecutionStatus.RUNNING.value, index=True)
    model: Mapped[str] = mapped_column(String(200))
    model_version: Mapped[str | None] = mapped_column(String(200))
    base_commit: Mapped[str] = mapped_column(String(64))
    result_commit: Mapped[str | None] = mapped_column(String(64))
    environment: Mapped[dict] = mapped_column(default=dict)
    summary: Mapped[dict] = mapped_column(default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    finished_at: Mapped[datetime | None]

    tool_calls: Mapped[list[ToolCall]] = relationship(back_populates="execution", order_by="ToolCall.sequence")
    agent: Mapped[Agent] = relationship()
    task: Mapped[Task] = relationship()
    workspace: Mapped[Workspace] = relationship()


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (UniqueConstraint("execution_id", "sequence"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    execution_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("executions.id"), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    tool: Mapped[str] = mapped_column(String(64), index=True)
    command: Mapped[str | None] = mapped_column(Text)
    input: Mapped[dict] = mapped_column(default=dict)
    output: Mapped[dict] = mapped_column(default=dict)
    files_affected: Mapped[list] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(16), index=True)  # OK | ERROR | DENIED
    exit_code: Mapped[int | None]
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    policy: Mapped[dict] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    execution: Mapped[Execution] = relationship(back_populates="tool_calls")


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("executions.id"), index=True)
    commit_sha: Mapped[str] = mapped_column(String(64), index=True)
    parent_commit: Mapped[str] = mapped_column(String(64))
    tree_id: Mapped[str] = mapped_column(String(64))
    message: Mapped[str] = mapped_column(Text)
    task_state: Mapped[dict] = mapped_column(default=dict)
    filesystem: Mapped[dict] = mapped_column(default=dict)
    created_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    task: Mapped[Task] = relationship()
    workspace: Mapped[Workspace] = relationship()


class Change(Base):
    """One file changed by one commit, attributed to the execution that produced it."""

    __tablename__ = "changes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("executions.id"), index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("agents.id"), index=True)
    checkpoint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("checkpoints.id"), index=True)
    commit_sha: Mapped[str] = mapped_column(String(64), index=True)
    parent_commit: Mapped[str] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    change_type: Mapped[str] = mapped_column(String(4))
    additions: Mapped[int] = mapped_column(Integer, default=0)
    deletions: Mapped[int] = mapped_column(Integer, default=0)
    semantic: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    task: Mapped[Task] = relationship()
    agent: Mapped[Agent | None] = relationship()


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", index=True)
    base_commit: Mapped[str] = mapped_column(String(64))
    head_commit: Mapped[str] = mapped_column(String(64))
    diff_stats: Mapped[dict] = mapped_column(default=dict)
    semantic_diff: Mapped[dict] = mapped_column(default=dict)
    policy: Mapped[dict] = mapped_column(default=dict)
    submitted_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    task: Mapped[Task] = relationship()


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    review_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("reviews.id"), index=True)
    merge_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("merges.id"), index=True)
    action: Mapped[str] = mapped_column(String(100), default="merge")
    requirement_key: Mapped[str] = mapped_column(String(500))
    kind: Mapped[str] = mapped_column(String(32))  # policy | semantic_conflict
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=ApprovalStatus.PENDING.value, index=True)
    head_commit: Mapped[str] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(default=dict)
    decided_by: Mapped[str | None] = mapped_column(String(200))
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    decided_at: Mapped[datetime | None]

    task: Mapped[Task] = relationship()
    workspace: Mapped[Workspace] = relationship()


class Policy(Base):
    """A versioned YAML policy document. scope is "global" or a repository id."""

    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("scope", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    scope: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[int] = mapped_column(Integer)
    document: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class RiskAssessment(Base):
    __tablename__ = "risk_assessments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    head_commit: Mapped[str] = mapped_column(String(64))
    score: Mapped[int] = mapped_column(Integer)
    severity: Mapped[str] = mapped_column(String(16), index=True)
    reasons: Mapped[list] = mapped_column(default=list)
    signals: Mapped[list] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)

    task: Mapped[Task] = relationship()


class Merge(Base):
    __tablename__ = "merges"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    repository_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("repositories.id"), index=True)
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"), index=True)
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tasks.id"), index=True)
    status: Mapped[str] = mapped_column(String(32), default=MergeStatus.QUEUED.value, index=True)
    target_branch: Mapped[str] = mapped_column(String(200))
    head_commit: Mapped[str] = mapped_column(String(64))
    evaluation: Mapped[dict] = mapped_column(default=dict)
    merge_commit: Mapped[str | None] = mapped_column(String(64))
    target_head_before: Mapped[str | None] = mapped_column(String(64))
    revert_commit: Mapped[str | None] = mapped_column(String(64))
    requested_by: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)
    evaluated_at: Mapped[datetime | None]
    merged_at: Mapped[datetime | None]

    task: Mapped[Task] = relationship()
    workspace: Mapped[Workspace] = relationship()


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=new_id)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("executions.id"), index=True)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("repositories.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(64))  # log | report | blob | test-results
    content_type: Mapped[str] = mapped_column(String(100), default="text/plain")
    size: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    storage_key: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (Index("ix_events_subject", "subject_type", "subject_id"),)

    seq: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True,
                                     autoincrement=True)
    id: Mapped[uuid.UUID] = mapped_column(unique=True, default=new_id)
    type: Mapped[str] = mapped_column(String(100), index=True)
    repository_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    execution_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    agent_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    subject_type: Mapped[str | None] = mapped_column(String(64))
    subject_id: Mapped[str | None] = mapped_column(String(64))
    actor_type: Mapped[str] = mapped_column(String(16))  # human | agent | system
    actor_id: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class EventChainHead(Base):
    """Single row holding the latest event hash; locked while appending to serialize the chain."""

    __tablename__ = "event_chain_head"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hash: Mapped[str] = mapped_column(String(64))
    count: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), default=0)


class ImmutableEventError(RuntimeError):
    pass


@event.listens_for(Event, "before_update")
def _no_update(*_):
    raise ImmutableEventError("events are append-only")


@event.listens_for(Event, "before_delete")
def _no_delete(*_):
    raise ImmutableEventError("events are append-only")
