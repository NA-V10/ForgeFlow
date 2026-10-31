import json

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ff_agent_sdk import ForgeFlowClient
from forgeflow_api.config import Settings
from forgeflow_api.main import create_app
from forgeflow_cli import main as cli

PLAYBOOK = """
message: Add multiply
validate: [pytest, -q, -p, no:cacheprovider]
steps:
  - append:
      path: calc.py
      content: |

        def mul(a, b):
            return a * b
  - write:
      path: test_mul.py
      content: |
        from calc import mul


        def test_mul():
            assert mul(3, 4) == 12
"""


@pytest.fixture()
def forge(tmp_path, monkeypatch):
    monkeypatch.setenv("FORGEFLOW_CONFIG_DIR", str(tmp_path / "cfg"))
    app = create_app(Settings(data_dir=tmp_path / "data"))
    runner = CliRunner()
    with TestClient(app) as http:
        cli._client_override = ForgeFlowClient(client=http)

        def run(*args, ok=True):
            res = runner.invoke(cli.app, [str(a) for a in args])
            if ok:
                assert res.exit_code == 0, res.output
            return res

        def j(*args):
            return json.loads(run(*args, "--json").stdout)

        yield run, j, tmp_path
    cli._client_override = None


def test_cli_end_to_end(forge):
    run, j, tmp = forge
    src = tmp / "src"
    src.mkdir()
    import subprocess

    (src / "calc.py").write_bytes(b"def add(a, b):\n    return a + b\n")
    for cmd in (["git", "init", "-q", "-b", "main"], ["git", "add", "."],
                ["git", "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init"]):
        subprocess.run(cmd, cwd=src, check=True)

    repo = j("repo", "create", "calc", "--from", src, "--test-command", "pytest -q -p no:cacheprovider")
    assert repo["head"]
    assert [r["name"] for r in j("repo", "list")] == ["calc"]
    agent = j("agent", "create", "mathbot", "--model", "scripted-playbook", "--kind", "scripted")
    assert "token" in agent
    task = j("task", "create", "Add multiply", "--repo", "calc", "--agent", "mathbot")
    pb = tmp / "pb.yaml"
    pb.write_text(PLAYBOOK)
    started = j("agent", "start", "mathbot", "--task", task["id"][:8], "--playbook", pb)
    assert started["tests"]["passed"] == 1 and started["review_id"]
    ws = started["workspace_id"]

    d = j("diff", ws[:8], "--semantic")
    assert ("function_added", "mul") in {(c["kind"], c["symbol"]) for c in d["semantic"]["groups"]["functions"]}
    assert "Semantic changes:" in run("diff", ws, "--semantic").stdout
    assert "+def mul" in run("diff", ws).stdout

    r = j("risk", ws)
    assert 0 <= r["score"] <= 100 and r["severity"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")
    assert "/ 100" in run("risk", ws).stdout
    assert j("policy", "check", "database.drop")["effect"] == "DENY"
    assert j("policy", "check", "merge", "--path", "package.json")["effect"] == "REQUIRE_APPROVAL"

    shown = j("task", "show", task["id"])
    assert shown["status"] == "REVIEW" and shown["executions"][0]["status"] == "SUCCESS"
    assert "provenance" in run("task", "show", task["id"]).stdout

    m = j("merge", ws)
    assert m["status"] == "MERGED", m["evaluation"]["reasons"]
    assert j("queue")[0]["status"] == "MERGED"
    assert "MERGED" in run("queue").stdout
    assert "workspace is MERGED" in run("merge", ws, "--dry-run", ok=False).output

    t = j("trace", "calc.py:4", "--repo", "calc")
    assert [c["type"] for c in t["chain"]][-3:] == ["agent", "task", "model"]
    assert t["chain"][-3]["label"] == "mathbot"

    rep = j("reproduce", started["execution_id"])
    assert rep["verdict"] == "REPRODUCED"

    rb = j("rollback", m["id"], "-m", "test")
    assert rb["status"] == "ROLLED_BACK"
    assert any(e["type"] == "merge.rolled_back" for e in j("events", "--limit", "5"))


def test_cli_checkpoints_and_errors(forge):
    run, j, tmp = forge
    j("repo", "create", "r2")
    j("agent", "create", "bot2")
    task = j("task", "create", "Edit readme", "--repo", "r2", "--agent", "bot2")
    ws = j("workspace", "create", "--task", task["id"])
    assert ws["path"]
    from pathlib import Path

    Path(ws["path"], "README.md").write_bytes(b"# changed by a human\n")
    cp = j("checkpoint", "create", ws["id"], "-m", "human edit")
    assert [c["id"] for c in j("checkpoint", "list", ws["id"])] == [cp["id"]]
    assert j("checkpoint", "restore", cp["id"])["current_commit"] == cp["commit_sha"]
    assert [w["id"] for w in j("workspace", "list")] == [ws["id"]]
    res = run("approve", "deadbeef", ok=False)
    assert res.exit_code == 1 and "not found" in res.output
    res = run("merge", "nope", ok=False)
    assert res.exit_code == 1
