"""Agent executions and mediated tool calls.

Agents never receive host paths or direct filesystem access. Every operation is
a tool call executed here, after:

1. ownership check (the calling agent owns the execution),
2. path confinement to the workspace,
3. workspace permissions (writable / read-only globs, command allow list),
4. policy evaluation (``file.read``, ``file.write``, ``file.delete``, ``command.run``),

and is recorded as a :class:`ToolCall` with inputs, outputs, affected files and
the policy decision, plus audit events. File contents written by agents are
stored content-addressed so executions can be replayed.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
import uuid
from typing import Any

from ff_policy import PolicyContext, glob_match
from ff_sandbox import BoundaryViolation, CommandDenied, confine, split_command
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import Principal
from ..core import Forge, ForgeError, InvalidState, PermissionDenied, PolicyDenied, effective_policies, get_or_404
from ..db import utcnow
from ..events import Actor, record_event
from ..models import Agent, Artifact, Execution, ExecutionStatus, ToolCall, Workspace, WorkspaceStatus
from .registry import set_task_status
from .workspaces import create_checkpoint, mark_task_running, transition, ws_path

MAX_READ_BYTES = 1024 * 1024
MAX_WRITE_BYTES = 5 * 1024 * 1024
DB_OUTPUT_LIMIT = 8 * 1024
TOOLS = ("read_file", "write_file", "delete_file", "list_files", "run_command")


def _agent_actor(execution: Execution) -> Actor:
    return Actor("agent", str(execution.agent_id))


def start_execution(
    forge: Forge, s: Session, p: Principal, *, workspace_id: uuid.UUID | str, model: str | None = None,
    model_version: str | None = None, environment: dict[str, Any] | None = None,
) -> Execution:
    if p.type != "agent":
        raise PermissionDenied("executions are started by agents (use the agent's token)")
    ws = get_or_404(s, Workspace, workspace_id, "workspace")
    agent = get_or_404(s, Agent, p.agent_id, "agent")
    if ws.agent_id is None:
        ws.agent_id = agent.id
    elif ws.agent_id != agent.id:
        raise PermissionDenied("workspace belongs to a different agent")
    if ws.status in ("MERGED", "ABANDONED"):
        raise InvalidState(f"workspace is {ws.status}")
    running = s.execute(select(Execution).where(Execution.workspace_id == ws.id,
                                                Execution.status == ExecutionStatus.RUNNING.value)).scalars().first()
    if running:
        raise InvalidState(f"workspace already has a running execution {running.id}")
    head = forge.engine.head(ws_path(ws))
    ex = Execution(
        repository_id=ws.repository_id, workspace_id=ws.id, task_id=ws.task_id, agent_id=agent.id,
        model=model or agent.model, model_version=model_version or agent.model_version, base_commit=head,
        environment={**forge.environment(ws.permissions), "client": environment or {}},
    )
    s.add(ex)
    s.flush()
    actor = _agent_actor(ex)
    transition(s, ws, WorkspaceStatus.RUNNING, actor, f"execution {str(ex.id)[:8]} started")
    mark_task_running(s, ws.task, actor)
    agent.status = "ACTIVE"
    record_event(s, "agent.started", actor, f"{agent.name} started on '{ws.task.title}' with {ex.model}",
                 repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, execution_id=ex.id,
                 agent_id=agent.id, subject=("execution", ex.id),
                 payload={"model": ex.model, "model_version": ex.model_version, "base_commit": head,
                          "sandbox": ex.environment.get("sandbox")})
    return ex


def _own(p: Principal, ex: Execution) -> None:
    if p.type != "agent" or p.agent_id != ex.agent_id:
        raise PermissionDenied("only the agent that owns this execution may call its tools")
    if ex.status != ExecutionStatus.RUNNING.value:
        raise InvalidState(f"execution is {ex.status}")


def _next_seq(s: Session, ex: Execution) -> int:
    return (s.execute(select(func.max(ToolCall.sequence)).where(ToolCall.execution_id == ex.id)).scalar() or 0) + 1


def _clip(text: str) -> str:
    return text if len(text) <= DB_OUTPUT_LIMIT else text[:DB_OUTPUT_LIMIT] + f"\n… [{len(text) - DB_OUTPUT_LIMIT} more]"


def _file_hashes(root, paths: list[str]) -> dict[str, str | None]:
    out = {}
    for rel in paths:
        f = root / rel
        out[rel] = hashlib.sha256(f.read_bytes()).hexdigest() if f.is_file() else None
    return out


def run_tool(forge: Forge, s: Session, p: Principal, ex: Execution, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    _own(p, ex)
    if tool not in TOOLS:
        raise ForgeError(f"unknown tool '{tool}'; available: {', '.join(TOOLS)}")
    ws: Workspace = ex.workspace
    agent: Agent = ex.agent
    root = ws_path(ws)
    perms = ws.permissions or {}
    policies = effective_policies(s, ws.repository_id)
    actor = _agent_actor(ex)
    seq = _next_seq(s, ex)
    started = time.monotonic()
    call = ToolCall(execution_id=ex.id, sequence=seq, tool=tool, input={}, output={}, files_affected=[], status="OK")
    refs = dict(repository_id=ws.repository_id, task_id=ws.task_id, workspace_id=ws.id, execution_id=ex.id,
                agent_id=agent.id)

    def deny(reason: str, policy: dict | None = None) -> None:
        call.status = "DENIED"
        call.output = {"error": reason}
        call.policy = policy or {}
        call.duration_ms = int((time.monotonic() - started) * 1000)
        s.add(call)
        record_event(s, "tool.denied", actor, f"{agent.name}: {tool} denied — {reason}", subject=("tool_call", call.id),
                     payload={"tool": tool, "input": call.input, "reason": reason}, **refs)
        s.commit()  # the denial itself must be audited even though the request fails
        raise PolicyDenied(reason)

    def check_policy(action: str, paths: list[str] | None = None, command: str | None = None) -> dict:
        decision = policies.evaluate(PolicyContext(action=action, paths=paths or [], agent=agent.name, command=command))
        d = decision.to_dict()
        if decision.effect == "DENY":
            deny("; ".join(decision.reasons), d)
        return d

    def confined(rel: str):
        try:
            return confine(root, rel)
        except BoundaryViolation as exc:
            deny(str(exc))

    if tool in ("read_file", "write_file", "delete_file"):
        rel = str(args.get("path") or "")
        call.input = {"path": rel}
        target = confined(rel)
        rel = target.relative_to(root.resolve()).as_posix()
        call.input["path"] = rel
        if tool != "read_file":
            if not any(glob_match(rel, g) for g in perms.get("write_paths") or ["**"]):
                deny(f"{rel} is outside this workspace's writable paths")
            if any(glob_match(rel, g) for g in perms.get("read_only_paths") or []):
                deny(f"{rel} is read-only for this workspace")
        call.policy = check_policy(f"file.{tool.split('_')[0]}", [rel])

        if tool == "read_file":
            if not target.is_file():
                raise ForgeError(f"{rel} does not exist", tool_call=seq)
            data = target.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            truncated = len(data) > MAX_READ_BYTES
            try:
                content, encoding = data[:MAX_READ_BYTES].decode("utf-8"), "utf-8"
            except UnicodeDecodeError:
                content, encoding = base64.b64encode(data[:MAX_READ_BYTES]).decode(), "base64"
            call.output = {"sha256": sha, "size": len(data), "truncated": truncated}
            result = {"path": rel, "content": content, "encoding": encoding, "sha256": sha, "size": len(data),
                      "truncated": truncated}
        elif tool == "write_file":
            encoding = args.get("encoding", "utf-8")
            raw = args.get("content")
            if not isinstance(raw, str):
                raise ForgeError("content must be a string")
            data = base64.b64decode(raw) if encoding == "base64" else raw.encode("utf-8")
            if len(data) > MAX_WRITE_BYTES:
                raise ForgeError(f"file too large ({len(data)} bytes)")
            existed = target.exists()
            sha = forge.store.put_blob(data)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f".{target.name}.ff-tmp")
            tmp.write_bytes(data)
            os.replace(tmp, target)
            call.input.update({"sha256": sha, "size": len(data), "encoding": encoding})
            call.files_affected = [rel]
            call.output = {"created": not existed, "sha256": sha}
            result = {"path": rel, "sha256": sha, "size": len(data), "created": not existed}
            record_event(s, "file.modified", actor, f"{agent.name} {'created' if not existed else 'modified'} {rel}",
                         subject=("file", rel), payload={"path": rel, "sha256": sha, "created": not existed,
                                                         "size": len(data)}, **refs)
        else:
            if not target.exists():
                raise ForgeError(f"{rel} does not exist")
            if target.is_dir():
                raise ForgeError("delete_file only deletes files")
            target.unlink()
            call.files_affected = [rel]
            result = {"path": rel, "deleted": True}
            record_event(s, "file.deleted", actor, f"{agent.name} deleted {rel}", subject=("file", rel),
                         payload={"path": rel}, **refs)

    elif tool == "list_files":
        prefix = str(args.get("prefix") or "")
        base = confined(prefix) if prefix else root.resolve()
        call.input = {"prefix": prefix}
        files: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if d not in (".git", "node_modules", "__pycache__", ".venv"))
            for fn in sorted(filenames):
                files.append((os.path.join(dirpath, fn)).replace(os.sep, "/")[len(str(root.resolve())) + 1:])
                if len(files) >= 5000:
                    break
        call.output = {"count": len(files)}
        result = {"files": files}

    else:  # run_command
        try:
            argv = split_command(args.get("argv") or args.get("command") or [])
        except ValueError as exc:
            raise ForgeError(f"cannot parse command: {exc}") from exc
        command = " ".join(argv)
        call.command = command
        call.input = {"argv": argv, "timeout": args.get("timeout")}
        call.policy = check_policy("command.run", command=command)
        sandbox = forge.sandbox(perms)
        decision = sandbox.policy.check(argv)
        if not decision.allowed:
            deny(decision.reason)
        timeout = min(float(args.get("timeout") or forge.settings.command_timeout), forge.settings.command_timeout)
        before = forge.engine.dirty_paths(root)
        before_hashes = _file_hashes(root, before)
        is_test = any(w in ("pytest", "jest", "vitest", "test") for w in argv[:4])
        if is_test:
            record_event(s, "test.started", actor, f"{agent.name} started tests: {command}",
                         subject=("execution", ex.id), payload={"command": command}, **refs)
            s.commit()
        try:
            r = sandbox.run(argv, root, timeout=timeout)
        except CommandDenied as exc:
            deny(str(exc))
        after = forge.engine.dirty_paths(root)
        after_hashes = _file_hashes(root, after)
        touched = sorted(p for p in set(before) | set(after) if before_hashes.get(p) != after_hashes.get(p))
        log = f"$ {command}\n[exit {r.exit_code}{' timed out' if r.timed_out else ''} in {r.duration_ms}ms]\n" \
              f"--- stdout ---\n{r.stdout}\n--- stderr ---\n{r.stderr}\n"
        artifact = store_artifact(forge, s, ex, f"{seq:04d}-{argv[0].rsplit('/', 1)[-1]}.log", "log",
                                  log.encode(), "text/plain")
        call.exit_code = r.exit_code
        call.files_affected = touched
        call.status = "OK" if r.exit_code == 0 else "ERROR"
        call.output = {"exit_code": r.exit_code, "stdout": _clip(r.stdout), "stderr": _clip(r.stderr),
                       "timed_out": r.timed_out, "sandbox": r.sandbox, "artifact_id": str(artifact.id),
                       "tests": r.tests.to_dict() if r.tests else None}
        result = {"exit_code": r.exit_code, "stdout": r.stdout, "stderr": r.stderr, "timed_out": r.timed_out,
                  "duration_ms": r.duration_ms, "files_affected": touched,
                  "tests": r.tests.to_dict() if r.tests else None}
        if r.tests:
            t = r.tests
            record_event(s, "test.completed", actor, f"Tests {command}: {t.passed} passed, {t.failed} failed"
                         + (f", {t.errors} errors" if t.errors else ""), subject=("execution", ex.id),
                         payload={"command": command, **t.to_dict(), "exit_code": r.exit_code}, **refs)

    call.duration_ms = int((time.monotonic() - started) * 1000)
    s.add(call)
    s.flush()
    record_event(s, "tool.executed", actor, f"{agent.name}: {tool} {call.command or call.input.get('path') or ''}"
                 .strip(), subject=("tool_call", call.id),
                 payload={"tool": tool, "sequence": seq, "status": call.status, "exit_code": call.exit_code,
                          "files": call.files_affected, "duration_ms": call.duration_ms}, **refs)
    result["tool_call_id"] = str(call.id)
    result["sequence"] = seq
    return result


def store_artifact(forge: Forge, s: Session, ex: Execution | None, name: str, kind: str, data: bytes,
                   content_type: str, repository_id: uuid.UUID | None = None) -> Artifact:
    sha = hashlib.sha256(data).hexdigest()
    key = f"executions/{ex.id}/{name}" if ex else f"repositories/{repository_id}/{uuid.uuid4()}-{name}"
    forge.store.put(key, data, content_type)
    a = Artifact(execution_id=ex.id if ex else None, repository_id=ex.repository_id if ex else repository_id,
                 name=name, kind=kind, content_type=content_type, size=len(data), sha256=sha, storage_key=key)
    s.add(a)
    s.flush()
    return a


def latest_test_summary(ex: Execution) -> dict[str, Any] | None:
    for call in sorted(ex.tool_calls, key=lambda c: -c.sequence):
        tests = (call.output or {}).get("tests")
        if call.tool == "run_command" and tests:
            return {**tests, "command": call.command, "tool_call": call.sequence}
    return None


def finish_execution(
    forge: Forge, s: Session, p: Principal, ex: Execution, *, status: str = "SUCCESS",
    summary: dict[str, Any] | None = None, error: str | None = None, checkpoint: bool = True,
    message: str | None = None,
) -> Execution:
    if p.type == "agent":
        _own(p, ex)
    elif ex.status != ExecutionStatus.RUNNING.value:
        raise InvalidState(f"execution is {ex.status}")
    status = ExecutionStatus(status.upper()).value
    if status == "RUNNING":
        raise ForgeError("cannot finish an execution with status RUNNING")
    ws: Workspace = ex.workspace
    actor = _agent_actor(ex) if p.type == "agent" else p.actor
    cp = None
    if checkpoint and status != "CANCELLED":
        cp = create_checkpoint(forge, s, actor, ws, message or f"{ex.agent.name}: {ws.task.title}", execution=ex)
    s.refresh(ex)
    calls = sorted(ex.tool_calls, key=lambda c: c.sequence)
    files = sorted({f for c in calls for f in (c.files_affected or []) if c.status != "DENIED"})
    ex.status = status
    ex.error = error
    ex.finished_at = utcnow()
    ex.result_commit = forge.engine.head(ws_path(ws))
    ex.summary = {
        **(summary or {}),
        "tool_calls": len(calls),
        "denied": sum(1 for c in calls if c.status == "DENIED"),
        "commands": [c.command for c in calls if c.tool == "run_command" and c.command],
        "files": files,
        "tests": latest_test_summary(ex),
        "checkpoint": str(cp.id) if cp else None,
        "duration_ms": int((ex.finished_at - ex.started_at).total_seconds() * 1000),
    }
    if status == "FAILED":
        transition(s, ws, WorkspaceStatus.FAILED, actor, error or "execution failed")
        set_task_status(s, ws.task, "FAILED", actor, error or "execution failed")
    elif ws.status == WorkspaceStatus.RUNNING.value:
        transition(s, ws, WorkspaceStatus.CHECKPOINTED, actor, f"execution {str(ex.id)[:8]} finished")
    ex.agent.status = "IDLE"
    tests = ex.summary["tests"]
    record_event(s, "agent.finished", actor,
                 f"{ex.agent.name} finished '{ws.task.title}': {status}" +
                 (f" — tests {tests['passed']} passed, {tests['failed']} failed" if tests else ""),
                 repository_id=ex.repository_id, task_id=ex.task_id, workspace_id=ws.id, execution_id=ex.id,
                 agent_id=ex.agent_id, subject=("execution", ex.id),
                 payload={"status": status, "result_commit": ex.result_commit, "files": files, "tests": tests})
    return ex
