import pytest
from fastapi.testclient import TestClient

from ff_agent_sdk import ForgeFlowClient
from forgeflow_api.config import Settings
from forgeflow_api.main import create_app
from forgeflow_runtime import END, Playbook, PlaybookPlanner, StateGraph, run_agent

PYTEST = ["pytest", "-q", "-p", "no:cacheprovider"]


def test_state_graph_routes_and_limits():
    g = StateGraph(dict)
    g.add_node("inc", lambda s: {"n": s["n"] + 1})
    g.set_entry_point("inc")
    g.add_conditional_edges("inc", lambda s: "again" if s["n"] < 3 else "done", {"again": "inc", "done": END})
    out = g.compile().invoke({"n": 0})
    assert out["n"] == 3 and out["trace"] == ["inc", "inc", "inc"]

    loop = StateGraph(dict, max_steps=5)
    loop.add_node("a", lambda s: None)
    loop.set_entry_point("a")
    loop.add_edge("a", "a")
    with pytest.raises(RuntimeError, match="exceeded"):
        loop.compile().invoke({})
    bad = StateGraph(dict)
    bad.add_node("a", lambda s: None)
    bad.set_entry_point("a")
    bad.add_edge("a", "missing")
    with pytest.raises(ValueError):
        bad.compile()


@pytest.fixture()
def env(tmp_path):
    app = create_app(Settings(data_dir=tmp_path / "d"))
    with TestClient(app) as http:
        human = ForgeFlowClient(client=http)
        repo = human.post("/repositories", {"name": "r", "initial_files": {
            "calc.py": "def add(a, b):\n    return a - b\n",
            "test_calc.py": "from calc import add\n\n\ndef test_add():\n    assert add(2, 2) == 4\n"}})
        agent = human.post("/agents", {"name": "fixer", "model": "scripted-playbook", "kind": "scripted"})
        task = human.post("/tasks", {"repository_id": repo["id"], "title": "Fix add", "agent_id": "fixer"})
        yield human, ForgeFlowClient(client=http, token=agent["token"]), task


def test_playbook_agent_validates_fixes_and_submits(env):
    human, agent, task = env
    pb = Playbook(
        steps=[{"append": {"path": "calc.py", "content": "\n\ndef mul(a, b):\n    return a * b\n"}}],
        fix_steps=[{"replace": {"path": "calc.py", "old": "return a - b", "new": "return a + b"}}],
        validate=PYTEST,
    )
    state = run_agent(agent, task["id"], PlaybookPlanner(pb), validate=pb.validate, message="Fix add, add mul")
    assert state["trace"] == ["setup", "act", "validate", "fix", "validate", "finish", "submit"]
    assert state["tests_ok"] and state["tests"]["passed"] == 1
    ex = human.get(f"/executions/{state['execution_id']}")
    assert ex["status"] == "SUCCESS" and ex["summary"]["fix_attempts"] == 1
    assert [c["tool"] for c in ex["tool_calls"]].count("run_command") == 2
    assert state["review"]["status"] == "OPEN"
    assert human.get(f"/tasks/{task['id']}")["status"] == "REVIEW"


def test_failure_marks_execution_failed(env):
    human, agent, task = env
    pb = Playbook(steps=[{"replace": {"path": "calc.py", "old": "not there", "new": "x"}}])
    with pytest.raises(ValueError):
        run_agent(agent, task["id"], PlaybookPlanner(pb))
    ex = human.get("/executions", task_id=task["id"])[0]
    assert ex["status"] == "FAILED" and "not found" in ex["error"]


class FakeBlock:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeAnthropic:
    """Stands in for anthropic.Anthropic: scripted tool_use turns, then a final text turn."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.requests = []
        self.beta = self
        self.messages = self

    def create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        content = self.turns.pop(0)
        stop = "tool_use" if any(b.type == "tool_use" for b in content) else "end_turn"
        return FakeBlock(content=content, stop_reason=stop)


def test_claude_planner_drives_tools_through_forgeflow(env):
    from forgeflow_runtime.claude import ClaudePlanner

    human, agent, task = env
    fake = FakeAnthropic([
        [FakeBlock(type="tool_use", id="t1", name="read_file", input={"path": "calc.py"})],
        [FakeBlock(type="tool_use", id="t2", name="write_file",
                   input={"path": "calc.py", "content": "def add(a, b):\n    return a + b\n"}),
         FakeBlock(type="tool_use", id="t3", name="write_file", input={"path": "../escape.py", "content": "x"})],
        [FakeBlock(type="tool_use", id="t4", name="run_command", input={"argv": PYTEST})],
        [FakeBlock(type="text", text="Fixed add() to return the sum.")],
    ])
    planner = ClaudePlanner(model="claude-opus-5-5", client=fake)
    state = run_agent(agent, task["id"], planner, validate=PYTEST)
    assert state["tests_ok"]
    req = fake.requests[0]
    assert req["model"] == "claude-opus-5-5" and req["thinking"] == {"type": "adaptive"}
    # the escape attempt was denied by ForgeFlow and reported back to the model as an error
    results = fake.requests[2]["messages"][-1]["content"]
    escape = next(r for r in results if r["tool_use_id"] == "t3")
    assert escape["is_error"] and "policy_denied" in escape["content"]
    ex = human.get(f"/executions/{state['execution_id']}")
    assert ex["model"] == "claude-opus-5-5"
    assert any(c["status"] == "DENIED" for c in ex["tool_calls"])
