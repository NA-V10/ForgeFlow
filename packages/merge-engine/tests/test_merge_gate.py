from pathlib import Path

import pytest

from ff_merge import BLOCKED, CONFLICT, READY, REQUIRES_APPROVAL, MergeGate, MergeRequest, OpenChangeSet, analyze_range
from ff_policy import DEFAULT_POLICY_YAML, PolicySet
from ff_sandbox import TestSummary
from ff_version import GitEngine

AUTHN = b"""class AuthenticationContext:
    def __init__(self, user):
        self.user = user

    def is_authenticated(self):
        return self.user is not None
"""
AUTHZ = b"""from app.authn import AuthenticationContext


class AuthorizationContext:
    def __init__(self, authn: AuthenticationContext, roles):
        self.authn = authn
        self.roles = roles

    def can(self, action):
        return self.authn.is_authenticated() and action in self.roles
"""


@pytest.fixture()
def env(tmp_path: Path):
    engine = GitEngine()
    repo = tmp_path / "repo.git"
    engine.init_repository(repo, initial_files={
        "app/__init__.py": b"", "app/authn.py": AUTHN, "app/authz.py": AUTHZ,
        "app/util.py": b"def add(a, b):\n    return a + b\n", "README.md": b"# demo\n",
        "package.json": b'{"dependencies": {}}',
    })
    counter = iter(range(100))

    def workspace(files: dict[str, bytes]) -> tuple[str, str]:
        base = engine.branch_head(repo, "main")
        name = f"ws{next(counter)}"
        wt = tmp_path / name
        engine.create_worktree(repo, wt, f"forgeflow/ws/{name}", base)
        for p, c in files.items():
            (wt / p).parent.mkdir(parents=True, exist_ok=True)
            (wt / p).write_bytes(c)
        return base, engine.commit_all(wt, f"{name} change", f"{name} <{name}@x>")

    return engine, repo, workspace


def gate(engine, **kw):
    return MergeGate(engine, PolicySet.from_yaml(DEFAULT_POLICY_YAML), **kw)


def passing_tests(*_):
    return TestSummary(framework="pytest", passed=3)


def test_ready(env):
    engine, repo, ws = env
    base, head = ws({"app/util.py": b"def add(a, b):\n    return b + a\n"})
    ev = gate(engine).evaluate(MergeRequest(repo, "main", base, head, "ws-util"), run_tests=passing_tests)
    assert ev.decision == READY, ev.reasons
    assert [c.status for c in ev.checks] == ["pass"] * 7
    assert [c.step for c in ev.checks] == [1, 2, 3, 4, 5, 6, 7]


def test_policy_requires_approval_then_ready(env):
    engine, repo, ws = env
    base, head = ws({"package.json": b'{"dependencies": {"left-pad": "1.0.0"}}'})
    g = gate(engine)
    req = MergeRequest(repo, "main", base, head, "ws-dep")
    ev = g.evaluate(req, run_tests=passing_tests)
    assert ev.decision == REQUIRES_APPROVAL
    assert [r.key for r in ev.requirements] == ["policy:dependency-change"]
    assert g.evaluate(req, approvals={"policy:dependency-change": "APPROVED"}, run_tests=passing_tests).decision == READY
    rejected = g.evaluate(req, approvals={"policy:dependency-change": "REJECTED"}, run_tests=passing_tests)
    assert rejected.decision == BLOCKED


def test_failing_tests_block(env):
    engine, repo, ws = env
    base, head = ws({"app/util.py": b"def add(a, b):\n    return a - b\n"})
    ev = gate(engine).evaluate(MergeRequest(repo, "main", base, head, "ws"),
                               run_tests=lambda *_: TestSummary(framework="pytest", passed=2, failed=1))
    assert ev.decision == BLOCKED
    assert "1 test(s) failing on the merged tree" in ev.reasons
    assert any(s.name == "test_failures" for s in ev.risk.signals)


def test_textual_conflict(env):
    engine, repo, ws = env
    b1, h1 = ws({"README.md": b"# A\n"})
    b2, h2 = ws({"README.md": b"# B\n"})
    engine.merge(repo, "main", h1, "merge 1", "ForgeFlow <ff@x>")
    ev = gate(engine).evaluate(MergeRequest(repo, "main", b2, h2, "ws-b"), run_tests=passing_tests)
    assert ev.decision == CONFLICT
    assert ev.textual_conflicts == ["README.md"]
    assert ev.checks[2].status == "skip"


def test_semantic_conflict_after_concurrent_merge(env):
    engine, repo, ws = env
    _, ha = ws({"app/authn.py": AUTHN.replace(b"is not None", b"is not None and self.user.active")})
    bb, hb = ws({"app/authz.py": AUTHZ.replace(b"action in self.roles", b"action in self.roles or 'admin' in self.roles")})
    g = gate(engine)
    # before A merges, B sees A only as an advisory conflict
    open_a = OpenChangeSet("ws-a", analyze_range(engine, repo, bb, ha).changeset(engine, repo, "ws-a"))
    pre = g.evaluate(MergeRequest(repo, "main", bb, hb, "ws-b"), run_tests=passing_tests, open_changesets=[open_a])
    assert pre.advisory_conflicts and pre.advisory_conflicts[0]["conflict_type"] == "dependency_conflict"
    engine.merge(repo, "main", ha, "merge A", "ForgeFlow <ff@x>")
    ev = g.evaluate(MergeRequest(repo, "main", bb, hb, "ws-b"), run_tests=passing_tests)
    assert ev.decision == REQUIRES_APPROVAL
    assert [c.conflict_type for c in ev.semantic_conflicts] == ["dependency_conflict"]
    sem_keys = [r.key for r in ev.requirements if r.kind == "semantic_conflict"]
    assert sem_keys == ["semantic:dependency_conflict:AuthenticationContext,AuthorizationContext"]
    approvals = {r.key: "APPROVED" for r in ev.requirements}
    assert g.evaluate(MergeRequest(repo, "main", bb, hb, "ws-b"), approvals=approvals,
                      run_tests=passing_tests).decision == READY


def test_critical_semantic_conflict(env):
    engine, repo, ws = env
    _, ha = ws({"app/util.py": b"def sub(a, b):\n    return a - b\n"})  # removes add()
    bb, hb = ws({"app/calc.py": b"from app.util import add\n\n\ndef total(xs):\n    return add(xs[0], xs[1])\n"})
    engine.merge(repo, "main", ha, "merge A", "ForgeFlow <ff@x>")
    ev = gate(engine).evaluate(MergeRequest(repo, "main", bb, hb, "ws-b"), run_tests=passing_tests)
    assert ev.decision == CONFLICT
    assert ev.semantic_conflicts[0].conflict_type == "broken_reference"


def test_bad_base_and_empty(env):
    engine, repo, ws = env
    base, head = ws({"x.txt": b"1\n"})
    ev = gate(engine).evaluate(MergeRequest(repo, "main", head, head, "ws"))
    assert ev.decision == BLOCKED
    ev2 = gate(engine).evaluate(MergeRequest(repo, "main", base, base, "ws"))
    assert ev2.decision == BLOCKED and "no committed changes" in ev2.reasons[0]


def test_require_tests(env):
    engine, repo, ws = env
    base, head = ws({"app/util.py": b"def add(a, b):\n    return b + a\n"})
    ev = gate(engine, require_tests=True).evaluate(MergeRequest(repo, "main", base, head, "ws"))
    assert ev.decision == BLOCKED
