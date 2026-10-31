from ff_provenance import ProvenanceRef, build_trailers, parse_trailers, trace_line
from ff_version import GitEngine


def test_trailer_roundtrip():
    t = build_trailers(execution="e1", agent="a1", task="t1", model="claude-x", workspace=None)
    assert t == {"ForgeFlow-Execution": "e1", "ForgeFlow-Agent": "a1", "ForgeFlow-Task": "t1",
                 "ForgeFlow-Model": "claude-x"}
    ref = parse_trailers({**t, "Signed-off-by": "x"})
    assert ref == ProvenanceRef(execution="e1", agent="a1", task="t1", model="claude-x")
    assert ref.is_forgeflow
    assert not parse_trailers({}).is_forgeflow


class FakeResolver:
    def resolve(self, ref, commit_sha, path):
        return {
            "change": {"id": "chg-1", "label": f"{path} @ {commit_sha[:7]}"},
            "execution": {"id": ref.execution, "label": "exec run"},
            "agent": {"id": ref.agent, "label": "agent_auth"},
            "task": {"id": ref.task, "label": "Implement OAuth"},
        }


def test_trace_line_through_git(tmp_path):
    engine = GitEngine()
    repo = tmp_path / "r.git"
    engine.init_repository(repo, initial_files={"auth.py": b"def login():\n    pass\n"})
    wt = tmp_path / "wt"
    engine.create_worktree(repo, wt, "forgeflow/ws/x", engine.branch_head(repo, "main"))
    (wt / "auth.py").write_bytes(b"def login():\n    return validate_jwt()\n")
    sha = engine.commit_all(wt, "jwt", "agent_auth <a@x>", build_trailers(execution="e1", agent="a1", task="t1",
                                                                          model="model-v1"))
    lp = trace_line(engine, repo, sha, "auth.py", 2, FakeResolver())
    assert lp.origin == "agent"
    assert lp.content == "    return validate_jwt()"
    assert [c["type"] for c in lp.chain] == ["line", "file", "commit", "change", "execution", "agent", "task", "model"]
    assert lp.chain[-1]["id"] == "model-v1"
    assert "agent agent_auth" in lp.explain()

    human = trace_line(engine, repo, sha, "auth.py", 1)
    assert human.origin == "human"
    assert "outside ForgeFlow" in human.explain()
