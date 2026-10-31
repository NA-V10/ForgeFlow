"""Inbox ranking and thread summaries that drive the command-center UI."""


def edit(client, ws_id, path, old, new, message):
    with client.execution(ws_id) as run:
        run.write_file(path, run.read_file(path).replace(old, new))
        run.checkpoint_on_finish(message)


def test_inbox_and_threads(human, agents, repo):
    _, a = agents.make("agent_cc_auth")
    _, b = agents.make("agent_cc_docs")
    _, ws_a = agents.task_and_workspace("agent_cc_auth", "Harden login")
    _, ws_b = agents.task_and_workspace("agent_cc_docs", "Readme tweak")
    edit(a, ws_a["id"], "app/auth.py", "return self.user is not None", "return bool(self.user)", "harden")
    edit(b, ws_b["id"], "README.md", "# demo", "# demo shop", "docs")
    assert human.get("/inbox") == []

    human.post("/merges", {"workspace_id": ws_a["id"]})  # needs the security-code approval
    human.post("/merges", {"workspace_id": ws_b["id"]})  # READY

    items = human.get("/inbox")
    kinds = {(i["kind"], i["needs"]) for i in items}
    assert kinds == {("approval", "approve"), ("merge", "merge")}
    assert [i["priority"] for i in items] == sorted(i["priority"] for i in items)
    approval = next(i for i in items if i["kind"] == "approval")
    assert approval["agent"]["name"] == "agent_cc_auth" and approval["href"].startswith("/approvals/")
    assert approval["risk"]["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    threads = {t["task"]["title"]: t for t in human.get("/threads")}
    t = threads["Harden login"]
    assert t["status"] == "REVIEW" and t["agent"]["name"] == "agent_cc_auth"
    assert t["execution"]["status"] == "SUCCESS"
    assert t["execution"]["tool_calls"] == 2 and t["execution"]["files"] == 1
    assert t["execution"]["last_tool"]["tool"] == "write_file"
    assert t["gate"]["status"] == "REQUIRES_APPROVAL" and t["gate"]["total"] == 7 and 0 < t["gate"]["passed"] < 7
    assert t["pending_approvals"] == 1
    assert t["last_event"]["type"]
    assert threads["Readme tweak"]["gate"]["status"] == "READY"

    human.post(f"/merges/{threads['Readme tweak']['gate']['merge_id']}/execute")
    merged = {t["task"]["title"]: t for t in human.get("/threads")}["Readme tweak"]
    assert merged["gate"]["passed"] == 7 and merged["status"] == "MERGED"
    assert all(t["status"] != "MERGED" for t in human.get("/threads", include_closed="false"))
    assert all(i["kind"] != "merge" for i in human.get("/inbox"))


def test_inbox_conflict_is_p0(human, agents, repo):
    _, a = agents.make("agent_p0_a")
    _, b = agents.make("agent_p0_b")
    _, ws_a = agents.task_and_workspace("agent_p0_a", "Readme A")
    _, ws_b = agents.task_and_workspace("agent_p0_b", "Readme B")
    edit(a, ws_a["id"], "README.md", "# demo", "# A", "a")
    edit(b, ws_b["id"], "README.md", "# demo", "# B", "b")
    m_a = human.post("/merges", {"workspace_id": ws_a["id"]})
    human.post("/merges", {"workspace_id": ws_b["id"]})
    human.post(f"/merges/{m_a['id']}/execute")
    first = human.get("/inbox")[0]
    assert first["priority"] == "P0" and first["needs"] == "resolve" and first["title"] == "Readme B"
