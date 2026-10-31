"""Concurrent agents: isolation, merge-queue revalidation and semantic conflict detection."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor


def edit(client, ws_id, path, old, new, message):
    with client.execution(ws_id) as run:
        src = run.read_file(path)
        assert old in src
        run.write_file(path, src.replace(old, new))
        run.checkpoint_on_finish(message)


def test_semantic_conflict_between_agents(human, agents, repo):
    _, a = agents.make("agent_authn")
    _, b = agents.make("agent_authz")
    _, ws_a = agents.task_and_workspace("agent_authn", "Require active users")
    _, ws_b = agents.task_and_workspace("agent_authz", "Admins can do everything")

    # both agents run at the same time in separate worktrees
    with ThreadPoolExecutor(2) as pool:
        fa = pool.submit(edit, a, ws_a["id"], "app/auth.py", "return self.user is not None",
                         "return self.user is not None and getattr(self.user, 'active', True)", "active users only")
        fb = pool.submit(edit, b, ws_b["id"], "app/permissions.py", "action in self.roles",
                         "(action in self.roles or 'admin' in self.roles)", "admin override")
        fa.result()
        fb.result()

    # the open-workspace check already sees the dependency between them
    advisory = human.get(f"/workspaces/{ws_b['id']}/conflicts")["conflicts"]
    assert advisory and advisory[0]["conflict_type"] == "dependency_conflict"

    # A merges first (needs the security-code approval for app/auth.py)
    m_a = human.post("/merges", {"workspace_id": ws_a["id"]})
    for appr in human.get("/approvals", workspace_id=ws_a["id"], status="PENDING"):
        human.post(f"/approvals/{appr['id']}/approve", {})
    assert human.post(f"/merges/{m_a['id']}/execute")["status"] == "MERGED"

    # B now textually merges cleanly but semantically depends on what A changed
    m_b = human.post("/merges", {"workspace_id": ws_b["id"]})
    ev = m_b["evaluation"]
    assert m_b["status"] == "REQUIRES_APPROVAL"
    assert ev["checks"][1]["status"] == "pass"  # no textual conflict
    conflict = ev["semantic_conflicts"][0]
    assert conflict["conflict_type"] == "dependency_conflict"
    assert set(conflict["affected_symbols"]) == {"AuthenticationContext", "AuthorizationContext"}
    assert conflict["affected_files"] == ["app/auth.py", "app/permissions.py"]
    assert "AuthorizationContext" in conflict["explanation"]
    pending = human.get("/approvals", workspace_id=ws_b["id"], status="PENDING")
    assert {p["kind"] for p in pending} == {"semantic_conflict", "policy"}
    detected = human.get("/events", type="conflict.detected", workspace_id=ws_b["id"])
    assert detected

    for appr in pending:
        human.post(f"/approvals/{appr['id']}/approve", {"comment": "reviewed combined behaviour"})
    assert human.post(f"/merges/{m_b['id']}/execute")["status"] == "MERGED"


def test_textual_conflict_and_queue_revalidation(human, agents, repo):
    _, a = agents.make("agent_one")
    _, b = agents.make("agent_two")
    _, ws_a = agents.task_and_workspace("agent_one", "Readme A")
    _, ws_b = agents.task_and_workspace("agent_two", "Readme B")
    edit(a, ws_a["id"], "README.md", "# demo", "# demo A", "a")
    edit(b, ws_b["id"], "README.md", "# demo", "# demo B", "b")
    m_a = human.post("/merges", {"workspace_id": ws_a["id"]})
    m_b = human.post("/merges", {"workspace_id": ws_b["id"]})
    assert m_a["status"] == "READY" and m_b["status"] == "READY"
    queue = human.get("/merges", open_only=True)
    assert [m["position"] for m in queue if m["id"] in (m_a["id"], m_b["id"])] == [2, 1]  # newest first, by position

    human.post(f"/merges/{m_a['id']}/execute")
    # merging A re-validated B automatically
    b_now = human.get(f"/merges/{m_b['id']}")
    assert b_now["status"] == "CONFLICT"
    assert b_now["evaluation"]["textual_conflicts"] == ["README.md"]
    assert human.get(f"/tasks/{b_now['task']['id']}")["status"] == "BLOCKED"
