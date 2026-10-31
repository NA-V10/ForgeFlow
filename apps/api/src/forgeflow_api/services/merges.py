"""Merge queue: enqueue, evaluate (the 7-step gate), execute, re-validate, roll back."""

from __future__ import annotations

import shutil
import uuid
from typing import Any

from ff_merge import BLOCKED, CONFLICT, READY, MergeEvaluation, MergeGate, MergeRequest, OpenChangeSet, analyze_range
from ff_provenance import build_trailers
from ff_sandbox import CommandDenied, TestSummary, split_command
from ff_version import RefUpdateConflict, VersionEngineError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import Principal, require_human
from ..core import Forge, InvalidState, PermissionDenied, effective_policies
from ..db import utcnow
from ..events import Actor, record_event
from ..models import OPEN_MERGE_STATUSES, Merge, MergeStatus, Workspace, WorkspaceStatus
from .executions import store_artifact
from .registry import repo_path, set_task_status
from .review import approval_map, ensure_approvals, save_risk, submit_review
from .workspaces import transition


def _open_merges(s: Session, repository_id: uuid.UUID) -> list[Merge]:
    return list(s.execute(select(Merge).where(Merge.repository_id == repository_id,
                                              Merge.status.in_([m.value for m in OPEN_MERGE_STATUSES]))
                          .order_by(Merge.created_at)).scalars())


def enqueue_merge(forge: Forge, s: Session, p: Principal, ws: Workspace) -> Merge:
    if p.type == "agent" and ws.agent_id != p.agent_id:
        raise PermissionDenied("agents may only merge their own workspaces")
    if ws.status == WorkspaceStatus.CHECKPOINTED.value:
        submit_review(forge, s, p, ws)
    if ws.status != WorkspaceStatus.REVIEW.value:
        raise InvalidState(f"workspace is {ws.status}; it must be in REVIEW to merge")
    existing = next((m for m in _open_merges(s, ws.repository_id) if m.workspace_id == ws.id), None)
    if existing:
        existing.head_commit = ws.current_commit
        return existing
    m = Merge(repository_id=ws.repository_id, workspace_id=ws.id, task_id=ws.task_id,
              target_branch=ws.repository.default_branch, head_commit=ws.current_commit, requested_by=p.name)
    s.add(m)
    s.flush()
    record_event(s, "merge.queued", p.actor, f"'{ws.task.title}' queued for merge into {m.target_branch}",
                 repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, agent_id=ws.agent_id,
                 subject=("merge", m.id), payload={"head": ws.current_commit})
    return m


def _test_runner(forge: Forge, s: Session, ws: Workspace, merge: Merge):
    settings = ws.repository.settings or {}
    command = settings.get("test_command")
    if not command:
        return None
    rp = repo_path(ws.repository)

    def run(target_head: str, ws_head: str, tree: str) -> TestSummary | None:
        commit = forge.engine.commit_tree(rp, tree, [target_head, ws_head], "ForgeFlow merge validation",
                                          "ForgeFlow <control-plane@forgeflow.local>")
        path = forge.settings.scratch_dir / f"merge-{merge.id}-{commit[:8]}"
        if path.exists():
            forge.engine.remove_worktree(rp, path)
        forge.engine.create_detached_worktree(rp, path, commit)
        try:
            argv = split_command(command)
            try:
                r = forge.sandbox(ws.permissions).run(argv, path, timeout=float(settings.get("test_timeout", 600)))
            except CommandDenied:
                return TestSummary(framework="denied", errors=1)
            log = f"$ {command}  (merged tree {tree[:10]})\n[exit {r.exit_code}]\n{r.stdout}\n{r.stderr}"
            art = store_artifact(forge, s, None, f"merge-{str(merge.id)[:8]}-tests.log", "test-results",
                                 log.encode(), "text/plain", repository_id=ws.repository_id)
            merge.evaluation = {**(merge.evaluation or {}), "test_artifact_id": str(art.id)}
            return r.tests or TestSummary(framework="unknown", errors=0 if r.exit_code == 0 else 1)
        finally:
            forge.engine.remove_worktree(rp, path)
            shutil.rmtree(path, ignore_errors=True)

    return run


def open_changesets(forge: Forge, s: Session, ws: Workspace) -> list[OpenChangeSet]:
    rp = repo_path(ws.repository)
    others = s.execute(select(Workspace).where(
        Workspace.repository_id == ws.repository_id, Workspace.id != ws.id,
        Workspace.status.in_([WorkspaceStatus.REVIEW.value, WorkspaceStatus.CHECKPOINTED.value,
                              WorkspaceStatus.RUNNING.value]))).scalars().all()
    out = []
    for o in others:
        if o.current_commit == o.base_commit:
            continue
        name = f"{o.agent.name if o.agent else 'workspace'} ({str(o.id)[:8]})"
        cs = analyze_range(forge.engine, rp, o.base_commit, o.current_commit).changeset(forge.engine, rp, name)
        out.append(OpenChangeSet(name=name, changeset=cs))
    return out


def evaluate_merge(forge: Forge, s: Session, actor: Actor, merge: Merge, *, run_tests: bool = True) -> MergeEvaluation:
    ws = s.get(Workspace, merge.workspace_id)
    assert ws is not None
    repo = ws.repository
    settings = repo.settings or {}
    merge.head_commit = ws.current_commit
    gate = MergeGate(forge.engine, effective_policies(s, repo.id), require_tests=bool(settings.get("require_tests")))
    name = f"{ws.agent.name if ws.agent else 'workspace'} ({str(ws.id)[:8]})"
    ev = gate.evaluate(
        MergeRequest(repo_path(repo), merge.target_branch, ws.base_commit, ws.current_commit, name,
                     agent=ws.agent.name if ws.agent else None),
        approvals=approval_map(s, ws),
        run_tests=_test_runner(forge, s, ws, merge) if run_tests else None,
        open_changesets=open_changesets(forge, s, ws),
    )
    if ev.requirements:
        ensure_approvals(s, ws, ev.requirements, actor, merge_id=merge.id)
    if ev.risk:
        save_risk(s, ws, ev.risk, actor)
    previous = merge.status
    merge.status = ev.decision
    test_artifact = (merge.evaluation or {}).get("test_artifact_id") if run_tests else None
    merge.evaluation = {**ev.to_dict(), "tests_run": run_tests and ev.tests is not None,
                        "test_artifact_id": test_artifact}
    merge.evaluated_at = utcnow()
    refs = dict(repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, agent_id=ws.agent_id)
    record_event(s, "merge.evaluated", actor, f"Merge of '{ws.task.title}': {ev.decision} — {'; '.join(ev.reasons[:3])}",
                 subject=("merge", merge.id), payload={"decision": ev.decision, "previous": previous,
                                                       "reasons": ev.reasons}, **refs)
    conflicts = [*({"conflict_type": "textual", "severity": "HIGH", "affected_files": [f],
                    "explanation": f"textual conflict in {f}"} for f in ev.textual_conflicts),
                 *(c.to_dict() for c in ev.semantic_conflicts)]
    for c in conflicts:
        record_event(s, "conflict.detected", actor,
                     f"{c['severity']} {c['conflict_type']} conflict for '{ws.task.title}': {c['explanation']}",
                     subject=("merge", merge.id), payload=c, **refs)
    for c in ev.advisory_conflicts:
        record_event(s, "conflict.detected", actor,
                     f"Potential {c['conflict_type']} with {c['with']}: {c['explanation']}",
                     subject=("merge", merge.id), payload={**c, "advisory": True}, **refs)
    if ev.decision in (BLOCKED, CONFLICT) and ws.task.status == "REVIEW":
        set_task_status(s, ws.task, "BLOCKED", actor, ev.reasons[0] if ev.reasons else ev.decision)
    elif ev.decision not in (BLOCKED, CONFLICT) and ws.task.status == "BLOCKED":
        set_task_status(s, ws.task, "REVIEW", actor, "merge checks no longer blocked")
    return ev


def execute_merge(forge: Forge, s: Session, p: Principal, merge: Merge) -> Merge:
    if merge.status in (MergeStatus.MERGED.value, MergeStatus.ROLLED_BACK.value):
        raise InvalidState(f"merge is already {merge.status}")
    ws = s.get(Workspace, merge.workspace_id)
    assert ws is not None
    if p.type == "agent" and ws.agent_id != p.agent_id:
        raise PermissionDenied("agents may only merge their own workspaces")
    repo = ws.repository
    for attempt in range(2):
        ev = evaluate_merge(forge, s, p.actor, merge)
        if ev.decision != READY:
            s.commit()
            raise InvalidState(f"merge is {ev.decision}: " + "; ".join(ev.reasons), decision=ev.decision,
                               reasons=ev.reasons, merge_id=str(merge.id))
        trailers = build_trailers(merge=merge.id, task=ws.task_id, workspace=ws.id,
                                  agent=ws.agent_id, kind="merge")
        try:
            commit = forge.engine.merge(
                repo_path(repo), merge.target_branch, ws.current_commit,
                f"Merge '{ws.task.title}' ({ws.branch})\n\nApproved by ForgeFlow merge gate: "
                f"risk {ev.risk.score}/100 {ev.risk.severity}." if ev.risk else f"Merge '{ws.task.title}'",
                "ForgeFlow <control-plane@forgeflow.local>", trailers, expected_head=ev.target_head,
            )
            break
        except RefUpdateConflict:
            if attempt == 1:
                raise InvalidState("target branch kept moving during merge; retry") from None
        except VersionEngineError as exc:
            merge.status = MergeStatus.FAILED.value
            s.commit()
            raise InvalidState(f"merge failed: {exc}") from exc
    merge.status = MergeStatus.MERGED.value
    merge.merge_commit = commit
    merge.target_head_before = ev.target_head
    merge.merged_at = utcnow()
    transition(s, ws, WorkspaceStatus.MERGED, p.actor, f"merged as {commit[:10]}")
    if ws.task.status != "COMPLETED":
        if ws.task.status not in ("REVIEW", "RUNNING"):
            set_task_status(s, ws.task, "REVIEW", p.actor)
        set_task_status(s, ws.task, "COMPLETED", p.actor, f"merged into {merge.target_branch}")
    record_event(s, "merge.completed", p.actor, f"Merged '{ws.task.title}' into {merge.target_branch} as {commit[:10]}",
                 repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, agent_id=ws.agent_id,
                 subject=("merge", merge.id), payload={"merge_commit": commit, "target_head_before": ev.target_head})
    s.flush()
    revalidate_queue(forge, s, repo.id, exclude=merge.id)
    return merge


def revalidate_queue(forge: Forge, s: Session, repository_id: uuid.UUID, exclude: uuid.UUID | None = None) -> None:
    """After the target moves, re-check every open merge (without tests) so new conflicts surface immediately."""
    for m in _open_merges(s, repository_id):
        if m.id != exclude:
            evaluate_merge(forge, s, Actor.system(), m, run_tests=False)


def rollback_merge(forge: Forge, s: Session, p: Principal, merge: Merge, reason: str | None = None) -> Merge:
    require_human(p, "roll back merges")
    if merge.status != MergeStatus.MERGED.value or not merge.merge_commit:
        raise InvalidState(f"merge is {merge.status}; only MERGED merges can be rolled back")
    ws = s.get(Workspace, merge.workspace_id)
    assert ws is not None
    try:
        commit = forge.engine.revert(
            repo_path(ws.repository), merge.target_branch, merge.merge_commit,
            f"Revert '{ws.task.title}'\n\n{reason or 'Rolled back via ForgeFlow'}",
            f"{p.name} <human@forgeflow>", build_trailers(merge=merge.id, task=ws.task_id, kind="rollback"),
        )
    except VersionEngineError as exc:
        raise InvalidState(f"rollback failed: {exc}") from exc
    merge.status = MergeStatus.ROLLED_BACK.value
    merge.revert_commit = commit
    record_event(s, "merge.rolled_back", p.actor, f"Rolled back '{ws.task.title}' with {commit[:10]}"
                 + (f": {reason}" if reason else ""), repository_id=ws.repository_id, task_id=ws.task_id,
                 workspace_id=ws.id, agent_id=ws.agent_id, subject=("merge", merge.id),
                 payload={"revert_commit": commit, "reason": reason})
    s.flush()
    revalidate_queue(forge, s, ws.repository_id)
    return merge


def queue_view(s: Session, repository_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
    q = select(Merge).order_by(Merge.created_at.desc())
    if repository_id:
        q = q.where(Merge.repository_id == repository_id)
    rows = s.execute(q).scalars().all()
    open_rows = sorted((m for m in rows if m.status in [x.value for x in OPEN_MERGE_STATUSES]),
                       key=lambda m: m.created_at)
    position = {m.id: i + 1 for i, m in enumerate(open_rows)}
    return [{"merge": m, "position": position.get(m.id)} for m in rows]
