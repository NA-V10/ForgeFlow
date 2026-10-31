"""repository → task → workspace → execution → diff → risk → approval → merge, end to end over HTTP."""

from __future__ import annotations

import pytest

from ff_agent_sdk import ForgeFlowError


def run_auth_agent(client, ws_id):
    with client.execution(ws_id, model="test-model") as run:
        src = run.read_file("app/auth.py")
        run.write_file("app/auth.py", src + (
            "\n\ndef validate_jwt(token):\n"
            "    return isinstance(token, str) and token.count('.') == 2\n"
        ))
        run.write_file("tests/test_auth.py", (
            "from app.auth import validate_jwt\n\n\n"
            "def test_validate_jwt():\n"
            "    assert validate_jwt('a.b.c')\n"
            "    assert not validate_jwt('nope')\n"
        ))
        result = run.run_command(["pytest", "-q", "-p", "no:cacheprovider"])
        assert result["exit_code"] == 0, result["stdout"] + result["stderr"]
        assert result["tests"]["passed"] == 2
        run.checkpoint_on_finish("Add JWT validation")
    return run


def test_vertical_slice(human, agents, repo):
    agent, client = agents.make("agent_auth")
    task, ws = agents.task_and_workspace("agent_auth", "Implement JWT authentication")
    assert ws["status"] == "CREATED" and ws["base_commit"] == repo["head"]
    assert ws["path"]  # humans see the host path ...
    assert client.get(f"/workspaces/{ws['id']}")["path"] is None  # ... agents never do
    assert all(w["path"] is None for w in client.get(f"/tasks/{task['id']}")["workspaces"])

    run = run_auth_agent(client, ws["id"])

    # execution provenance
    ex = human.get(f"/executions/{run.id}")
    assert ex["status"] == "SUCCESS"
    assert ex["model"] == "test-model" and ex["agent"]["name"] == "agent_auth"
    assert [c["tool"] for c in ex["tool_calls"]] == ["read_file", "write_file", "write_file", "run_command"]
    assert ex["summary"]["tests"]["passed"] == 2
    assert ex["summary"]["files"] == ["app/auth.py", "tests/test_auth.py"]
    assert ex["environment"]["sandbox"] == "local"
    assert {c["path"] for c in ex["changes"]} == {"app/auth.py", "tests/test_auth.py"}
    assert any(a["kind"] == "log" for a in ex["artifacts"])
    types = [e["type"] for e in ex["events"]]
    for t in ("agent.started", "file.modified", "test.started", "test.completed", "checkpoint.created", "agent.finished"):
        assert t in types

    ws_now = human.get(f"/workspaces/{ws['id']}")
    assert ws_now["status"] == "CHECKPOINTED" and ws_now["current_commit"] == ex["result_commit"]

    # standard + semantic diff
    diff = human.get(f"/workspaces/{ws['id']}/diff")
    assert {f["path"] for f in diff["files"]} == {"app/auth.py", "tests/test_auth.py"}
    assert "+def validate_jwt(token):" in diff["patch"]
    added = {(c["kind"], c["symbol"]) for c in diff["semantic"]["groups"]["functions"]}
    assert ("function_added", "validate_jwt") in added
    assert "Authentication" in diff["semantic"]["domains"]

    # review → risk + policy approvals (app/auth.py matches the default security-code policy)
    review = human.post(f"/workspaces/{ws['id']}/review")
    assert review["status"] == "OPEN"
    approvals = human.get("/approvals", workspace_id=ws["id"])
    assert [a["requirement_key"] for a in approvals] == ["policy:security-code"]
    risk = human.get("/risk-assessments", workspace_id=ws["id"])[0]
    assert any("authentication" in r for r in risk["reasons"])
    assert human.get(f"/tasks/{task['id']}")["status"] == "REVIEW"

    # merge is gated on approval
    merge = human.post("/merges", {"workspace_id": ws["id"]})
    assert merge["status"] == "REQUIRES_APPROVAL"
    steps = [(c["step"], c["status"]) for c in merge["evaluation"]["checks"]]
    assert steps == [(1, "pass"), (2, "pass"), (3, "pass"), (4, "warn"), (5, merge["evaluation"]["checks"][4]["status"]),
                     (6, "pass"), (7, "warn")]
    assert merge["evaluation"]["tests"]["passed"] == 2  # tests ran on the merged tree

    # an agent can never approve, even its own work
    with pytest.raises(ForgeFlowError) as exc:
        client.post(f"/approvals/{approvals[0]['id']}/approve", {})
    assert exc.value.status == 403
    with pytest.raises(ForgeFlowError):
        client.post(f"/merges/{merge['id']}/execute")

    detail = human.get(f"/approvals/{approvals[0]['id']}")
    ctx = detail["context"]
    assert ctx["agent"]["name"] == "agent_auth" and ctx["task"]["title"] == "Implement JWT authentication"
    assert ctx["files"] and "validate_jwt" in ctx["diff"] and ctx["risk"]["score"] > 0
    assert ctx["tests"]["passed"] == 2 and ctx["evidence"]["executions"][0]["commands"]

    human.post(f"/approvals/{approvals[0]['id']}/approve", {"comment": "LGTM"})
    merged = human.post(f"/merges/{merge['id']}/execute")
    assert merged["status"] == "MERGED" and merged["merge_commit"]
    assert human.get(f"/workspaces/{ws['id']}")["status"] == "MERGED"
    assert human.get(f"/tasks/{task['id']}")["status"] == "COMPLETED"
    assert human.get(f"/repositories/{repo['id']}")["head"] == merged["merge_commit"]

    # why does this line exist?
    blame = human.get(f"/repositories/{repo['id']}/blame", path="app/auth.py")
    line = next(l for l in blame["lines"] if "def validate_jwt" in l["content"])
    trace = human.get(f"/repositories/{repo['id']}/provenance", path="app/auth.py", line=line["line"])
    chain = [c["type"] for c in trace["chain"]]
    assert chain == ["line", "file", "commit", "change", "execution", "agent", "task", "model"]
    assert trace["chain"][5]["label"] == "agent_auth"
    assert trace["chain"][6]["label"] == "Implement JWT authentication"
    assert trace["chain"][7]["id"] == "test-model@2026-01"
    assert trace["chain"][4]["id"] == run.id

    # audit log integrity
    assert human.get("/events/verify")["valid"] is True
    merge_events = human.get("/events", type="merge.")
    assert {"merge.queued", "merge.evaluated", "merge.completed"} <= {e["type"] for e in merge_events}

    dash = human.get("/dashboard")
    assert dash["counts"]["tasks"]["COMPLETED"] == 1

    graph = human.get(f"/repositories/{repo['id']}/graph")
    types = {n["type"] for n in graph["nodes"]}
    assert types == {"repository", "branch", "task", "agent", "workspace", "change", "merge"}

    # rollback the merge
    rolled = human.post(f"/merges/{merge['id']}/rollback", {"reason": "demo"})
    assert rolled["status"] == "ROLLED_BACK"
    files = human.get(f"/repositories/{repo['id']}/files")
    assert "tests/test_auth.py" not in files


def test_reproduce_execution(human, agents):
    _, client = agents.make("agent_repro")
    _, ws = agents.task_and_workspace("agent_repro", "Reproducible change")
    run = run_auth_agent(client, ws["id"])
    report = human.post(f"/executions/{run.id}/reproduce", {})
    assert report["verdict"] == "REPRODUCED", report
    assert report["files"]["match"] is True
    replayed = [s for s in report["steps"] if s["tool"] == "run_command"]
    assert replayed[0]["replay_tests"]["passed"] == 2
    assert any("model outputs" in x for x in report["not_reproducible"])
    assert report["artifact_id"]


def test_checkpoints_and_restore(human, agents):
    _, client = agents.make("agent_cp")
    _, ws = agents.task_and_workspace("agent_cp", "Checkpoint test")
    run = client.start_execution(ws["id"])
    run.write_file("notes.txt", "one\n")
    cp1 = client.post(f"/workspaces/{ws['id']}/checkpoints", {"message": "first"})
    run.write_file("notes.txt", "two\n")
    cp2 = client.post(f"/workspaces/{ws['id']}/checkpoints", {"message": "second"})
    with pytest.raises(ForgeFlowError) as exc:
        client.post(f"/workspaces/{ws['id']}/checkpoints", {"message": "empty"})
    assert exc.value.status == 409
    assert [c["message"] for c in human.get("/checkpoints", workspace_id=ws["id"])] == ["first", "second"]
    assert cp2["parent_commit"] == cp1["commit_sha"]
    restored = human.post(f"/checkpoints/{cp1['id']}/restore")
    assert restored["current_commit"] == cp1["commit_sha"]
    assert run.read_file("notes.txt") == "one\n"
    run.finish()


def test_security_boundaries(human, agents, http):
    _, client = agents.make("agent_sec")
    _, other = agents.make("agent_other")
    _, ws = agents.task_and_workspace("agent_sec", "Security test")
    run = client.start_execution(ws["id"])

    for bad in ("../outside.txt", "/etc/passwd", ".git/config", "C:\\Windows\\win.ini"):
        with pytest.raises(ForgeFlowError) as exc:
            run.write_file(bad, "x")
        assert exc.value.code == "policy_denied", bad
    with pytest.raises(ForgeFlowError) as exc:
        run.run_command(["curl", "https://example.com"])
    assert exc.value.code == "policy_denied"
    with pytest.raises(ForgeFlowError) as exc:
        run.run_command(["bash", "-c", "echo hi"])
    assert exc.value.code == "policy_denied"

    # other agents and humans cannot drive this execution's tools
    with pytest.raises(ForgeFlowError) as exc:
        other.post(f"/executions/{run.id}/tools/read_file", {"args": {"path": "README.md"}})
    assert exc.value.status == 403
    with pytest.raises(ForgeFlowError) as exc:
        human.post(f"/executions/{run.id}/tools/read_file", {"args": {"path": "README.md"}})
    assert exc.value.status == 403
    with pytest.raises(ForgeFlowError):
        other.start_execution(ws["id"])

    # denials are audited as tool calls and events
    ex = human.get(f"/executions/{run.id}")
    assert sum(1 for c in ex["tool_calls"] if c["status"] == "DENIED") == 6
    assert sum(1 for e in ex["events"] if e["type"] == "tool.denied") == 6

    # agents cannot register agents, repositories or change policies
    with pytest.raises(ForgeFlowError):
        client.post("/agents", {"name": "evil", "model": "x"})
    with pytest.raises(ForgeFlowError):
        client.request("PUT", "/policies/global", json={"document": "policies: []"})

    # bad tokens are rejected
    resp = http.get("/api/v1/tasks", headers={"Authorization": "Bearer ffa_not-a-real-token"})
    assert resp.status_code == 401
    run.finish("CANCELLED", checkpoint=False)


def test_repository_policy_denies_writes(human, agents, repo):
    human.request("PUT", f"/policies/{repo['id']}", json={"document": (
        "policies:\n"
        "  - name: no-secrets\n    action: 'file.*'\n    path: 'secrets/**'\n    deny: true\n"
        "  - name: security-code\n    path: 'nothing/**'\n    require_review: true\n"
    )})
    eff = human.get("/policies/effective", repository_id=repo["id"])
    names = [p["name"] for p in eff["policies"]]
    assert "no-secrets" in names and names.count("security-code") == 1  # repository overrides global by name
    check = human.post("/policies/check", {"action": "file.write", "paths": ["secrets/key.pem"],
                                            "repository_id": repo["id"]})
    assert check["effect"] == "DENY"
    _, client = agents.make("agent_pol")
    _, ws = agents.task_and_workspace("agent_pol", "Policy test")
    run = client.start_execution(ws["id"])
    with pytest.raises(ForgeFlowError) as exc:
        run.write_file("secrets/key.pem", "-----BEGIN-----")
    assert "no-secrets" in exc.value.message
    run.finish("CANCELLED", checkpoint=False)
    with pytest.raises(ForgeFlowError) as exc:
        human.request("PUT", "/policies/global", json={"document": "policies:\n  - {name: x, deny: true}\n"})
    assert exc.value.status == 400


def test_failed_execution_and_abandon(human, agents):
    _, client = agents.make("agent_fail")
    task, ws = agents.task_and_workspace("agent_fail", "Doomed")
    with pytest.raises(RuntimeError):
        with client.execution(ws["id"]) as run:
            run.write_file("x.py", "x = 1\n")
            raise RuntimeError("model crashed")
    assert human.get(f"/workspaces/{ws['id']}")["status"] == "FAILED"
    assert human.get(f"/tasks/{task['id']}")["status"] == "FAILED"
    assert human.get(f"/executions/{run.id}")["error"].startswith("RuntimeError")
    assert human.post(f"/workspaces/{ws['id']}/abandon")["status"] == "ABANDONED"


def test_events_are_immutable(app, human, repo):
    from sqlalchemy import select

    from forgeflow_api.models import Event, ImmutableEventError

    forge = app.state.forge
    with forge.session() as s:
        e = s.execute(select(Event)).scalars().first()
        e.message = "tampered"
        with pytest.raises(ImmutableEventError):
            s.commit()
    # tampering below the ORM is blocked by database triggers
    with forge.session() as s:
        from sqlalchemy import text
        from sqlalchemy.exc import DatabaseError

        with pytest.raises(DatabaseError):
            s.execute(text("UPDATE events SET message = 'x'"))
    assert human.get("/events/verify")["valid"] is True


def test_websocket_streams_events(http, human, repo):
    with http.websocket_connect("/api/v1/ws/events?backfill=0") as ws:
        human.post("/tasks", {"repository_id": repo["id"], "title": "Streamed task"})
        evt = ws.receive_json()
        assert evt["type"] == "task.created" and "Streamed task" in evt["message"]


def test_short_ids_and_names(human, agents, repo):
    _, client = agents.make("agent_ids")
    task, ws = agents.task_and_workspace("agent_ids", "Short ids")
    assert human.get(f"/tasks/{task['id'][:8]}")["id"] == task["id"]
    assert human.get("/repositories/demo")["id"] == repo["id"]
    assert human.get("/agents/agent_ids")["name"] == "agent_ids"
    with pytest.raises(ForgeFlowError) as exc:
        human.get("/tasks/zzzz")
    assert exc.value.status == 404
