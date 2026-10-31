"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-30 21:51:00.245372
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
import forgeflow_api.db
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('event_chain_head',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('count', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_event_chain_head'))
    )
    op.create_table('events',
    sa.Column('seq', sa.BigInteger().with_variant(sa.Integer(), 'sqlite'), autoincrement=True, nullable=False),
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=True),
    sa.Column('task_id', sa.Uuid(), nullable=True),
    sa.Column('workspace_id', sa.Uuid(), nullable=True),
    sa.Column('execution_id', sa.Uuid(), nullable=True),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('subject_type', sa.String(length=64), nullable=True),
    sa.Column('subject_id', sa.String(length=64), nullable=True),
    sa.Column('actor_type', sa.String(length=16), nullable=False),
    sa.Column('actor_id', sa.String(length=200), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('payload', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('prev_hash', sa.String(length=64), nullable=False),
    sa.Column('hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('seq', name=op.f('pk_events')),
    sa.UniqueConstraint('hash', name=op.f('uq_events_hash')),
    sa.UniqueConstraint('id', name=op.f('uq_events_id'))
    )
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_events_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index('ix_events_subject', ['subject_type', 'subject_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_type'), ['type'], unique=False)
        batch_op.create_index(batch_op.f('ix_events_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('policies',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scope', sa.String(length=64), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('document', sa.Text(), nullable=False),
    sa.Column('active', sa.Boolean(), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_policies')),
    sa.UniqueConstraint('scope', 'version', name=op.f('uq_policies_scope_version'))
    )
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_policies_active'), ['active'], unique=False)
        batch_op.create_index(batch_op.f('ix_policies_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_policies_scope'), ['scope'], unique=False)

    op.create_table('repositories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('default_branch', sa.String(length=200), nullable=False),
    sa.Column('storage_path', sa.Text(), nullable=False),
    sa.Column('source_url', sa.Text(), nullable=True),
    sa.Column('engine', sa.String(length=32), nullable=False),
    sa.Column('settings', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_repositories')),
    sa.UniqueConstraint('name', name=op.f('uq_repositories_name'))
    )
    with op.batch_alter_table('repositories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_repositories_created_at'), ['created_at'], unique=False)

    op.create_table('agents',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('model_version', sa.String(length=200), nullable=True),
    sa.Column('provider', sa.String(length=100), nullable=True),
    sa.Column('capabilities', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_agents_repository_id_repositories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agents')),
    sa.UniqueConstraint('name', name=op.f('uq_agents_name')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_agents_token_hash'))
    )
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agents_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_agents_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_agents_status'), ['status'], unique=False)

    op.create_table('tasks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('title', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('priority', sa.String(length=16), nullable=False),
    sa.Column('base_commit', sa.String(length=64), nullable=False),
    sa.Column('labels', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.Column('started_at', forgeflow_api.db.UTCDateTime(), nullable=True),
    sa.Column('completed_at', forgeflow_api.db.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_tasks_agent_id_agents')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_tasks_repository_id_repositories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tasks'))
    )
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tasks_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tasks_status'), ['status'], unique=False)

    op.create_table('workspaces',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('branch', sa.String(length=300), nullable=False),
    sa.Column('base_commit', sa.String(length=64), nullable=False),
    sa.Column('current_commit', sa.String(length=64), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('permissions', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.Column('updated_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_workspaces_agent_id_agents')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_workspaces_repository_id_repositories')),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_workspaces_task_id_tasks')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_workspaces'))
    )
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_workspaces_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_workspaces_task_id'), ['task_id'], unique=False)

    op.create_table('executions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('agent_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('model', sa.String(length=200), nullable=False),
    sa.Column('model_version', sa.String(length=200), nullable=True),
    sa.Column('base_commit', sa.String(length=64), nullable=False),
    sa.Column('result_commit', sa.String(length=64), nullable=True),
    sa.Column('environment', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('summary', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('error', sa.Text(), nullable=True),
    sa.Column('started_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.Column('finished_at', forgeflow_api.db.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_executions_agent_id_agents')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_executions_repository_id_repositories')),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_executions_task_id_tasks')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_executions_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_executions'))
    )
    with op.batch_alter_table('executions', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_executions_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_executions_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_executions_started_at'), ['started_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_executions_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_executions_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_executions_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('merges',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('target_branch', sa.String(length=200), nullable=False),
    sa.Column('head_commit', sa.String(length=64), nullable=False),
    sa.Column('evaluation', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('merge_commit', sa.String(length=64), nullable=True),
    sa.Column('target_head_before', sa.String(length=64), nullable=True),
    sa.Column('revert_commit', sa.String(length=64), nullable=True),
    sa.Column('requested_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.Column('evaluated_at', forgeflow_api.db.UTCDateTime(), nullable=True),
    sa.Column('merged_at', forgeflow_api.db.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_merges_repository_id_repositories')),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_merges_task_id_tasks')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_merges_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_merges'))
    )
    with op.batch_alter_table('merges', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_merges_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_merges_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_merges_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_merges_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_merges_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('reviews',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(length=32), nullable=False),
    sa.Column('base_commit', sa.String(length=64), nullable=False),
    sa.Column('head_commit', sa.String(length=64), nullable=False),
    sa.Column('diff_stats', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('semantic_diff', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('policy', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('submitted_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_reviews_task_id_tasks')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_reviews_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_reviews'))
    )
    with op.batch_alter_table('reviews', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reviews_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_reviews_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_reviews_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reviews_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('risk_assessments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('head_commit', sa.String(length=64), nullable=False),
    sa.Column('score', sa.Integer(), nullable=False),
    sa.Column('severity', sa.String(length=16), nullable=False),
    sa.Column('reasons', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('signals', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_risk_assessments_task_id_tasks')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_risk_assessments_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_risk_assessments'))
    )
    with op.batch_alter_table('risk_assessments', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_risk_assessments_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_risk_assessments_severity'), ['severity'], unique=False)
        batch_op.create_index(batch_op.f('ix_risk_assessments_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_risk_assessments_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('approvals',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('review_id', sa.Uuid(), nullable=True),
    sa.Column('merge_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=100), nullable=False),
    sa.Column('requirement_key', sa.String(length=500), nullable=False),
    sa.Column('kind', sa.String(length=32), nullable=False),
    sa.Column('reason', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('head_commit', sa.String(length=64), nullable=False),
    sa.Column('details', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('decided_by', sa.String(length=200), nullable=True),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.Column('decided_at', forgeflow_api.db.UTCDateTime(), nullable=True),
    sa.ForeignKeyConstraint(['merge_id'], ['merges.id'], name=op.f('fk_approvals_merge_id_merges')),
    sa.ForeignKeyConstraint(['review_id'], ['reviews.id'], name=op.f('fk_approvals_review_id_reviews')),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_approvals_task_id_tasks')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_approvals_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_approvals'))
    )
    with op.batch_alter_table('approvals', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_approvals_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_approvals_merge_id'), ['merge_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approvals_review_id'), ['review_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approvals_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_approvals_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_approvals_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('artifacts',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=True),
    sa.Column('repository_id', sa.Uuid(), nullable=True),
    sa.Column('name', sa.String(length=300), nullable=False),
    sa.Column('kind', sa.String(length=64), nullable=False),
    sa.Column('content_type', sa.String(length=100), nullable=False),
    sa.Column('size', sa.BigInteger(), nullable=False),
    sa.Column('sha256', sa.String(length=64), nullable=False),
    sa.Column('storage_key', sa.Text(), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], name=op.f('fk_artifacts_execution_id_executions')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_artifacts_repository_id_repositories')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_artifacts'))
    )
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_artifacts_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_artifacts_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_artifacts_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_artifacts_sha256'), ['sha256'], unique=False)

    op.create_table('checkpoints',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=True),
    sa.Column('commit_sha', sa.String(length=64), nullable=False),
    sa.Column('parent_commit', sa.String(length=64), nullable=False),
    sa.Column('tree_id', sa.String(length=64), nullable=False),
    sa.Column('message', sa.Text(), nullable=False),
    sa.Column('task_state', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('filesystem', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_by', sa.String(length=200), nullable=True),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], name=op.f('fk_checkpoints_execution_id_executions')),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_checkpoints_task_id_tasks')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_checkpoints_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_checkpoints'))
    )
    with op.batch_alter_table('checkpoints', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_checkpoints_commit_sha'), ['commit_sha'], unique=False)
        batch_op.create_index(batch_op.f('ix_checkpoints_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_checkpoints_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_checkpoints_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_checkpoints_workspace_id'), ['workspace_id'], unique=False)

    op.create_table('tool_calls',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=False),
    sa.Column('sequence', sa.Integer(), nullable=False),
    sa.Column('tool', sa.String(length=64), nullable=False),
    sa.Column('command', sa.Text(), nullable=True),
    sa.Column('input', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('output', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('files_affected', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('exit_code', sa.Integer(), nullable=True),
    sa.Column('duration_ms', sa.Integer(), nullable=False),
    sa.Column('policy', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], name=op.f('fk_tool_calls_execution_id_executions')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tool_calls')),
    sa.UniqueConstraint('execution_id', 'sequence', name=op.f('uq_tool_calls_execution_id_sequence'))
    )
    with op.batch_alter_table('tool_calls', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_tool_calls_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_status'), ['status'], unique=False)
        batch_op.create_index(batch_op.f('ix_tool_calls_tool'), ['tool'], unique=False)

    op.create_table('changes',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('repository_id', sa.Uuid(), nullable=False),
    sa.Column('task_id', sa.Uuid(), nullable=False),
    sa.Column('workspace_id', sa.Uuid(), nullable=False),
    sa.Column('execution_id', sa.Uuid(), nullable=True),
    sa.Column('agent_id', sa.Uuid(), nullable=True),
    sa.Column('checkpoint_id', sa.Uuid(), nullable=True),
    sa.Column('commit_sha', sa.String(length=64), nullable=False),
    sa.Column('parent_commit', sa.String(length=64), nullable=False),
    sa.Column('path', sa.Text(), nullable=False),
    sa.Column('change_type', sa.String(length=4), nullable=False),
    sa.Column('additions', sa.Integer(), nullable=False),
    sa.Column('deletions', sa.Integer(), nullable=False),
    sa.Column('semantic', sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), 'postgresql'), nullable=False),
    sa.Column('created_at', forgeflow_api.db.UTCDateTime(), nullable=False),
    sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name=op.f('fk_changes_agent_id_agents')),
    sa.ForeignKeyConstraint(['checkpoint_id'], ['checkpoints.id'], name=op.f('fk_changes_checkpoint_id_checkpoints')),
    sa.ForeignKeyConstraint(['execution_id'], ['executions.id'], name=op.f('fk_changes_execution_id_executions')),
    sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], name=op.f('fk_changes_repository_id_repositories')),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_changes_task_id_tasks')),
    sa.ForeignKeyConstraint(['workspace_id'], ['workspaces.id'], name=op.f('fk_changes_workspace_id_workspaces')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_changes'))
    )
    with op.batch_alter_table('changes', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_changes_agent_id'), ['agent_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_changes_checkpoint_id'), ['checkpoint_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_changes_commit_sha'), ['commit_sha'], unique=False)
        batch_op.create_index(batch_op.f('ix_changes_created_at'), ['created_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_changes_execution_id'), ['execution_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_changes_repository_id'), ['repository_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_changes_task_id'), ['task_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_changes_workspace_id'), ['workspace_id'], unique=False)



    # Audit events are append-only at the database level too, not only in the ORM.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("""
            CREATE OR REPLACE FUNCTION forgeflow_events_immutable() RETURNS trigger AS $$
            BEGIN RAISE EXCEPTION 'events are append-only'; END; $$ LANGUAGE plpgsql;
        """)
        op.execute("CREATE TRIGGER events_no_update BEFORE UPDATE OR DELETE ON events "
                   "FOR EACH ROW EXECUTE FUNCTION forgeflow_events_immutable()")
    elif bind.dialect.name == "sqlite":
        op.execute("CREATE TRIGGER events_no_update BEFORE UPDATE ON events "
                   "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END")
        op.execute("CREATE TRIGGER events_no_delete BEFORE DELETE ON events "
                   "BEGIN SELECT RAISE(ABORT, 'events are append-only'); END")

def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS events_no_update ON events")
        op.execute("DROP FUNCTION IF EXISTS forgeflow_events_immutable()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS events_no_update")
        op.execute("DROP TRIGGER IF EXISTS events_no_delete")
    with op.batch_alter_table('changes', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_changes_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_changes_task_id'))
        batch_op.drop_index(batch_op.f('ix_changes_repository_id'))
        batch_op.drop_index(batch_op.f('ix_changes_execution_id'))
        batch_op.drop_index(batch_op.f('ix_changes_created_at'))
        batch_op.drop_index(batch_op.f('ix_changes_commit_sha'))
        batch_op.drop_index(batch_op.f('ix_changes_checkpoint_id'))
        batch_op.drop_index(batch_op.f('ix_changes_agent_id'))

    op.drop_table('changes')
    with op.batch_alter_table('tool_calls', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tool_calls_tool'))
        batch_op.drop_index(batch_op.f('ix_tool_calls_status'))
        batch_op.drop_index(batch_op.f('ix_tool_calls_execution_id'))
        batch_op.drop_index(batch_op.f('ix_tool_calls_created_at'))

    op.drop_table('tool_calls')
    with op.batch_alter_table('checkpoints', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_checkpoints_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_checkpoints_task_id'))
        batch_op.drop_index(batch_op.f('ix_checkpoints_execution_id'))
        batch_op.drop_index(batch_op.f('ix_checkpoints_created_at'))
        batch_op.drop_index(batch_op.f('ix_checkpoints_commit_sha'))

    op.drop_table('checkpoints')
    with op.batch_alter_table('artifacts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_artifacts_sha256'))
        batch_op.drop_index(batch_op.f('ix_artifacts_repository_id'))
        batch_op.drop_index(batch_op.f('ix_artifacts_execution_id'))
        batch_op.drop_index(batch_op.f('ix_artifacts_created_at'))

    op.drop_table('artifacts')
    with op.batch_alter_table('approvals', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_approvals_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_approvals_task_id'))
        batch_op.drop_index(batch_op.f('ix_approvals_status'))
        batch_op.drop_index(batch_op.f('ix_approvals_review_id'))
        batch_op.drop_index(batch_op.f('ix_approvals_merge_id'))
        batch_op.drop_index(batch_op.f('ix_approvals_created_at'))

    op.drop_table('approvals')
    with op.batch_alter_table('risk_assessments', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_risk_assessments_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_risk_assessments_task_id'))
        batch_op.drop_index(batch_op.f('ix_risk_assessments_severity'))
        batch_op.drop_index(batch_op.f('ix_risk_assessments_created_at'))

    op.drop_table('risk_assessments')
    with op.batch_alter_table('reviews', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reviews_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_reviews_task_id'))
        batch_op.drop_index(batch_op.f('ix_reviews_status'))
        batch_op.drop_index(batch_op.f('ix_reviews_created_at'))

    op.drop_table('reviews')
    with op.batch_alter_table('merges', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_merges_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_merges_task_id'))
        batch_op.drop_index(batch_op.f('ix_merges_status'))
        batch_op.drop_index(batch_op.f('ix_merges_repository_id'))
        batch_op.drop_index(batch_op.f('ix_merges_created_at'))

    op.drop_table('merges')
    with op.batch_alter_table('executions', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_executions_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_executions_task_id'))
        batch_op.drop_index(batch_op.f('ix_executions_status'))
        batch_op.drop_index(batch_op.f('ix_executions_started_at'))
        batch_op.drop_index(batch_op.f('ix_executions_repository_id'))
        batch_op.drop_index(batch_op.f('ix_executions_agent_id'))

    op.drop_table('executions')
    with op.batch_alter_table('workspaces', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_workspaces_task_id'))
        batch_op.drop_index(batch_op.f('ix_workspaces_status'))
        batch_op.drop_index(batch_op.f('ix_workspaces_repository_id'))
        batch_op.drop_index(batch_op.f('ix_workspaces_created_at'))
        batch_op.drop_index(batch_op.f('ix_workspaces_agent_id'))

    op.drop_table('workspaces')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_tasks_status'))
        batch_op.drop_index(batch_op.f('ix_tasks_repository_id'))
        batch_op.drop_index(batch_op.f('ix_tasks_created_at'))
        batch_op.drop_index(batch_op.f('ix_tasks_agent_id'))

    op.drop_table('tasks')
    with op.batch_alter_table('agents', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agents_status'))
        batch_op.drop_index(batch_op.f('ix_agents_repository_id'))
        batch_op.drop_index(batch_op.f('ix_agents_created_at'))

    op.drop_table('agents')
    with op.batch_alter_table('repositories', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_repositories_created_at'))

    op.drop_table('repositories')
    with op.batch_alter_table('policies', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_policies_scope'))
        batch_op.drop_index(batch_op.f('ix_policies_created_at'))
        batch_op.drop_index(batch_op.f('ix_policies_active'))

    op.drop_table('policies')
    with op.batch_alter_table('events', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_events_workspace_id'))
        batch_op.drop_index(batch_op.f('ix_events_type'))
        batch_op.drop_index(batch_op.f('ix_events_task_id'))
        batch_op.drop_index('ix_events_subject')
        batch_op.drop_index(batch_op.f('ix_events_repository_id'))
        batch_op.drop_index(batch_op.f('ix_events_execution_id'))
        batch_op.drop_index(batch_op.f('ix_events_created_at'))
        batch_op.drop_index(batch_op.f('ix_events_agent_id'))

    op.drop_table('events')
    op.drop_table('event_chain_head')
