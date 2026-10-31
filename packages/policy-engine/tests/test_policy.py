import pytest

from ff_policy import DEFAULT_POLICY_YAML, PolicyContext, PolicyError, PolicySet

SPEC_EXAMPLE = """
policies:

  - name: production-protection
    action: deploy.production
    require_approval: true

  - name: database-delete
    action: database.drop
    deny: true

  - name: dependency-change
    path: package.json
    require_review: true

  - name: security-code
    path: security/**
    require_review: true
"""


@pytest.fixture()
def ps() -> PolicySet:
    return PolicySet.from_yaml(SPEC_EXAMPLE)


def test_spec_example_parses(ps):
    assert [p.name for p in ps.policies] == ["production-protection", "database-delete", "dependency-change",
                                             "security-code"]


def test_deny(ps):
    d = ps.evaluate(PolicyContext(action="database.drop"))
    assert d.effect == "DENY"
    assert d.reasons == ["policy 'database-delete' denies action 'database.drop'"]


def test_require_approval_action(ps):
    d = ps.evaluate(PolicyContext(action="deploy.production"))
    assert d.effect == "REQUIRE_APPROVAL"
    assert [m.policy for m in d.requirements] == ["production-protection"]


def test_path_review(ps):
    d = ps.evaluate(PolicyContext(action="merge", paths=["package.json", "security/keys.py", "README.md"]))
    assert d.effect == "REQUIRE_APPROVAL"
    assert {m.policy: m.matched_paths for m in d.requirements} == {
        "dependency-change": ["package.json"], "security-code": ["security/keys.py"]}


def test_allow_by_default(ps):
    d = ps.evaluate(PolicyContext(action="merge", paths=["src/app.py"]))
    assert d.effect == "ALLOW" and d.matches == []


def test_deny_beats_everything():
    ps = PolicySet.from_yaml("""
policies:
  - {name: a, action: merge, allow: true}
  - {name: b, action: merge, require_approval: true}
  - {name: c, action: merge, agent: "untrusted-*", deny: true}
""")
    assert ps.evaluate(PolicyContext(action="merge", agent="untrusted-bot")).effect == "DENY"
    assert ps.evaluate(PolicyContext(action="merge", agent="trusted")).effect == "REQUIRE_APPROVAL"


def test_default_deny():
    ps = PolicySet.from_yaml("default: deny\npolicies:\n  - {name: reads, action: 'file.*', allow: true}\n")
    assert ps.evaluate(PolicyContext(action="file.read")).effect == "ALLOW"
    d = ps.evaluate(PolicyContext(action="command.run"))
    assert d.effect == "DENY" and "default: deny" in d.reasons[0]


def test_risk_conditions():
    ps = PolicySet.from_yaml(DEFAULT_POLICY_YAML)
    low = ps.evaluate(PolicyContext(action="merge", paths=["src/x.py"], risk_score=20, risk_severity="LOW"))
    high = ps.evaluate(PolicyContext(action="merge", paths=["src/x.py"], risk_score=70, risk_severity="HIGH"))
    assert low.effect == "ALLOW"
    assert high.effect == "REQUIRE_APPROVAL"
    assert "60 or more" in high.reasons[0]


def test_command_policy():
    ps = PolicySet.from_yaml(DEFAULT_POLICY_YAML)
    assert ps.evaluate(PolicyContext(action="command.run", command="git push origin main --force")).effect == "DENY"
    assert ps.evaluate(PolicyContext(action="command.run", command="pytest -q")).effect == "ALLOW"


def test_action_wildcards():
    ps = PolicySet.from_yaml("policies:\n  - {name: d, action: 'deploy.*', require_approval: true}\n")
    assert ps.evaluate(PolicyContext(action="deploy.staging")).effect == "REQUIRE_APPROVAL"
    assert ps.evaluate(PolicyContext(action="deployment")).effect == "ALLOW"


def test_deterministic():
    ps = PolicySet.from_yaml(DEFAULT_POLICY_YAML)
    ctx = PolicyContext(action="merge", paths=["auth/x.py", "package.json"], risk_score=90, risk_severity="CRITICAL")
    assert ps.evaluate(ctx) == ps.evaluate(ctx)


@pytest.mark.parametrize("doc,msg", [
    ("policies:\n  - {name: x, action: a}\n", "exactly one"),
    ("policies:\n  - {name: x, action: a, deny: true, allow: true}\n", "exactly one"),
    ("policies:\n  - {name: x, deny: true}\n", "match condition"),
    ("policies:\n  - {name: x, action: a, deny: true, bogus: 1}\n", "unknown keys"),
    ("policies:\n  - {name: x, action: a, deny: true}\n  - {name: x, action: b, deny: true}\n", "duplicate"),
    ("default: maybe\n", "default"),
    ("policies: [\n", "invalid YAML"),
])
def test_validation(doc, msg):
    with pytest.raises(PolicyError, match=msg):
        PolicySet.from_yaml(doc)
