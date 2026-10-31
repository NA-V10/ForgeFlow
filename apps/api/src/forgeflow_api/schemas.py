"""Request and response models (the public API contract)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorOut(BaseModel):
    error: str
    message: str
    details: dict[str, Any] = {}


# ----------------------------------------------------------------- references
class AgentRef(ORM):
    id: uuid.UUID
    name: str
    model: str


class TaskRef(ORM):
    id: uuid.UUID
    title: str
    status: str


class WorkspaceRef(ORM):
    id: uuid.UUID
    status: str
    branch: str


# --------------------------------------------------------------- repositories
class RepositoryCreate(BaseModel):
    name: str = Field(examples=["demo-shop"])
    description: str = ""
    source_url: str | None = Field(default=None, description="Import from an existing Git URL or local path")
    default_branch: str = "main"
    initial_files: dict[str, str] | None = Field(default=None, description="Files for the initial commit")
    settings: dict[str, Any] = Field(default_factory=dict,
                                     description="test_command, require_tests, test_timeout, default_permissions")


class RepositorySettingsUpdate(BaseModel):
    settings: dict[str, Any]


class RepositoryOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    default_branch: str
    source_url: str | None
    engine: str
    settings: dict[str, Any]
    created_at: datetime
    head: str | None = None


class CommitOut(BaseModel):
    sha: str
    parents: list[str]
    author: str
    message: str
    timestamp: int
    trailers: dict[str, str]


# --------------------------------------------------------------------- agents
class AgentCreate(BaseModel):
    name: str = Field(examples=["agent_auth"])
    model: str = Field(default="unspecified", examples=["claude-opus-5-5"])
    model_version: str | None = None
    provider: str | None = None
    kind: Literal["scripted", "llm", "external"] = "external"
    description: str = ""
    capabilities: list[str] = []
    repository_id: uuid.UUID | None = None


class AgentOut(ORM):
    id: uuid.UUID
    name: str
    description: str
    kind: str
    model: str
    model_version: str | None
    provider: str | None
    capabilities: list[str]
    status: str
    repository_id: uuid.UUID | None
    created_at: datetime


class AgentCreated(AgentOut):
    token: str = Field(description="Shown once. Agents authenticate with 'Authorization: Bearer <token>'.")


# ---------------------------------------------------------------------- tasks
class TaskCreate(BaseModel):
    repository_id: str = Field(description="Repository id or name")
    title: str
    description: str = ""
    priority: str = "MEDIUM"
    agent_id: str | None = Field(default=None, description="Agent id or name")
    labels: list[str] = []


class TaskUpdate(BaseModel):
    status: str | None = None
    agent_id: str | None = None
    priority: str | None = None
    description: str | None = None


class TaskOut(ORM):
    id: uuid.UUID
    repository_id: uuid.UUID
    title: str
    description: str
    status: str
    priority: str
    base_commit: str
    labels: list[str]
    agent: AgentRef | None
    created_by: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None


# ----------------------------------------------------------------- workspaces
class WorkspaceCreate(BaseModel):
    task_id: str
    agent_id: str | None = None
    permissions: dict[str, Any] | None = None


class WorkspaceOut(ORM):
    id: uuid.UUID
    repository_id: uuid.UUID
    task: TaskRef
    agent: AgentRef | None
    status: str
    branch: str
    base_commit: str
    current_commit: str
    permissions: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    path: str | None = Field(default=None, description="Host path; only returned to human principals")


class FileChangeOut(BaseModel):
    path: str
    status: str
    additions: int
    deletions: int
    binary: bool = False


class DiffOut(BaseModel):
    base: str
    head: str
    files: list[FileChangeOut]
    additions: int
    deletions: int
    patch: str
    semantic: dict[str, Any] | None = None
    summary: str | None = None
    includes_uncommitted: bool = False


# ----------------------------------------------------------------- executions
class ExecutionCreate(BaseModel):
    workspace_id: str
    model: str | None = None
    model_version: str | None = None
    environment: dict[str, Any] = {}


class ToolCallIn(BaseModel):
    args: dict[str, Any] = {}


class ExecutionFinish(BaseModel):
    status: Literal["SUCCESS", "FAILED", "CANCELLED"] = "SUCCESS"
    summary: dict[str, Any] = {}
    error: str | None = None
    checkpoint: bool = True
    message: str | None = None


class ToolCallOut(ORM):
    id: uuid.UUID
    sequence: int
    tool: str
    command: str | None
    input: dict[str, Any]
    output: dict[str, Any]
    files_affected: list[str]
    status: str
    exit_code: int | None
    duration_ms: int
    policy: dict[str, Any]
    created_at: datetime


class ExecutionOut(ORM):
    id: uuid.UUID
    repository_id: uuid.UUID
    workspace_id: uuid.UUID
    task: TaskRef
    agent: AgentRef
    status: str
    model: str
    model_version: str | None
    base_commit: str
    result_commit: str | None
    environment: dict[str, Any]
    summary: dict[str, Any]
    error: str | None
    started_at: datetime
    finished_at: datetime | None


class ArtifactOut(ORM):
    id: uuid.UUID
    execution_id: uuid.UUID | None
    name: str
    kind: str
    content_type: str
    size: int
    sha256: str
    created_at: datetime


class ChangeOut(ORM):
    id: uuid.UUID
    repository_id: uuid.UUID
    task: TaskRef
    agent: AgentRef | None
    workspace_id: uuid.UUID
    execution_id: uuid.UUID | None
    checkpoint_id: uuid.UUID | None
    commit_sha: str
    parent_commit: str
    path: str
    change_type: str
    additions: int
    deletions: int
    semantic: list[dict[str, Any]]
    created_at: datetime


class EventOut(BaseModel):
    seq: int
    id: str
    type: str
    message: str
    payload: dict[str, Any]
    repository_id: str | None
    task_id: str | None
    workspace_id: str | None
    execution_id: str | None
    agent_id: str | None
    subject_type: str | None
    subject_id: str | None
    actor_type: str
    actor_id: str
    created_at: str
    hash: str
    prev_hash: str


class ExecutionDetail(ExecutionOut):
    tool_calls: list[ToolCallOut]
    artifacts: list[ArtifactOut] = []
    changes: list[ChangeOut] = []
    events: list[EventOut] = []


# ---------------------------------------------------------------- checkpoints
class CheckpointCreate(BaseModel):
    message: str | None = None


class CheckpointOut(ORM):
    id: uuid.UUID
    workspace_id: uuid.UUID
    task: TaskRef
    execution_id: uuid.UUID | None
    commit_sha: str
    parent_commit: str
    tree_id: str
    message: str
    task_state: dict[str, Any]
    filesystem: dict[str, Any]
    created_by: str | None
    created_at: datetime


# ------------------------------------------------------- reviews & approvals
class ReviewOut(ORM):
    id: uuid.UUID
    workspace_id: uuid.UUID
    task: TaskRef
    status: str
    base_commit: str
    head_commit: str
    diff_stats: dict[str, Any]
    semantic_diff: dict[str, Any]
    policy: dict[str, Any]
    submitted_by: str | None
    created_at: datetime


class ApprovalOut(ORM):
    id: uuid.UUID
    workspace: WorkspaceRef
    task: TaskRef
    review_id: uuid.UUID | None
    merge_id: uuid.UUID | None
    action: str
    requirement_key: str
    kind: str
    reason: str
    status: str
    head_commit: str
    details: dict[str, Any]
    decided_by: str | None
    comment: str | None
    created_at: datetime
    decided_at: datetime | None


class ApprovalDetail(ApprovalOut):
    context: dict[str, Any]


class ApprovalDecision(BaseModel):
    comment: str | None = None


class RiskAssessmentOut(ORM):
    id: uuid.UUID
    workspace_id: uuid.UUID
    task: TaskRef
    head_commit: str
    score: int
    severity: str
    reasons: list[str]
    signals: list[dict[str, Any]]
    created_at: datetime


# ------------------------------------------------------------------- policies
class PolicyPut(BaseModel):
    document: str = Field(description="YAML policy document")


class PolicyOut(ORM):
    id: uuid.UUID
    scope: str
    version: int
    document: str
    active: bool
    created_by: str | None
    created_at: datetime


class PolicyCheck(BaseModel):
    action: str = Field(examples=["merge", "deploy.production", "command.run"])
    repository_id: str | None = None
    paths: list[str] = []
    agent: str | None = None
    command: str | None = None
    risk_score: int | None = None
    risk_severity: str | None = None


# --------------------------------------------------------------------- merges
class MergeCreate(BaseModel):
    workspace_id: str
    execute: bool = Field(default=False, description="Merge immediately if the gate returns READY")


class MergeOut(ORM):
    id: uuid.UUID
    repository_id: uuid.UUID
    workspace: WorkspaceRef
    task: TaskRef
    status: str
    target_branch: str
    head_commit: str
    evaluation: dict[str, Any]
    merge_commit: str | None
    target_head_before: str | None
    revert_commit: str | None
    requested_by: str | None
    created_at: datetime
    evaluated_at: datetime | None
    merged_at: datetime | None
    position: int | None = None


class RollbackIn(BaseModel):
    reason: str | None = None


class ReproduceIn(BaseModel):
    keep_workspace: bool = False


# ------------------------------------------------------------------ dashboard
class DashboardOut(BaseModel):
    counts: dict[str, Any]
    active_agents: list[AgentOut]
    running_tasks: list[TaskOut]
    pending_approvals: list[ApprovalOut]
    merge_queue: list[MergeOut]
    recent_checkpoints: list[CheckpointOut]
    risk_distribution: dict[str, int]
    recent_executions: list[ExecutionOut]


class TaskDetail(TaskOut):
    workspaces: list[WorkspaceOut]
    executions: list[ExecutionOut]
    checkpoints: list[CheckpointOut]
    changes: list[ChangeOut]
    reviews: list[ReviewOut]
    approvals: list[ApprovalOut]
    risk: RiskAssessmentOut | None
    merges: list[MergeOut]
