from ff_risk import RiskFile, RiskInput, TestEvidence, assess_risk, glob_match, severity_for


def test_glob_match():
    assert glob_match("security/keys.py", "security/**")
    assert glob_match("app/security/x/y.py", "**/security/**")
    assert glob_match(".env", ".env*")
    assert glob_match("svc/Dockerfile", "**/Dockerfile")
    assert not glob_match("docs/security.md", "security/**")
    assert glob_match("package.json", "package.json")
    assert not glob_match("a/package.json", "package.json")


def test_trivial_change_is_low():
    r = assess_risk(RiskInput(files=[RiskFile("README.md", "M", 3, 1)], tests=TestEvidence(passed=10)))
    assert r.score == 0 and r.severity == "LOW" and r.reasons == []


def test_high_risk_example_is_deterministic():
    inp = RiskInput(
        files=[RiskFile("auth/oauth.py", "A", 120, 0), RiskFile("app/routes.py", "M", 20, 8),
               RiskFile("requirements.txt", "M", 1, 0)],
        semantic_changes=[
            {"kind": "class_added", "category": "classes", "domains": ["Authentication"], "path": "auth/oauth.py"},
            {"kind": "route_changed", "category": "apis", "domains": ["API", "Authentication"], "path": "app/routes.py"},
            {"kind": "dependency_added", "category": "dependencies", "domains": ["Dependencies"], "path": "requirements.txt"},
        ],
        tests=TestEvidence(passed=41, failed=2),
    )
    r1, r2 = assess_risk(inp), assess_risk(inp)
    assert r1 == r2
    assert r1.score == 5 + 15 + 20 + 15 + 10 + 25  # lines, sensitive, authn, api, dep, tests
    assert r1.severity == "CRITICAL"
    text = " | ".join(r1.reasons)
    for expected in ("authentication code changed", "public API modified", "1 dependency added", "2 tests failing",
                     "sensitive paths changed: auth/oauth.py"):
        assert expected in text


def test_missing_tests_conflicts_and_mitigation():
    r = assess_risk(RiskInput(
        files=[RiskFile("db/migrations/001_init.py", "A", 30, 0), RiskFile("tests/test_db.py", "A", 40, 0)],
        semantic_changes=[{"kind": "function_added", "category": "functions", "domains": ["Tests"], "path": "tests/test_db.py"}],
        conflicts=[{"severity": "MEDIUM", "conflict_type": "dependency_conflict"}],
    ))
    names = {s.name: s.points for s in r.signals}
    assert names["database_migration"] == 15
    assert names["no_test_evidence"] == 10
    assert names["semantic_conflicts"] == 10
    assert names["tests_added"] == -5
    assert r.score == 30 and r.severity == "MEDIUM"


def test_score_capped_and_severity_bands():
    files = [RiskFile(f"auth/f{i}.py", "M", 100, 100) for i in range(50)]
    r = assess_risk(RiskInput(files=files, tests=TestEvidence(failed=10),
                              conflicts=[{"severity": "CRITICAL", "conflict_type": "broken_reference"}]))
    assert r.score == 100 and r.severity == "CRITICAL"
    assert [severity_for(s) for s in (0, 29, 30, 59, 60, 84, 85)] == \
        ["LOW", "LOW", "MEDIUM", "MEDIUM", "HIGH", "HIGH", "CRITICAL"]


def test_sensitive_config_key():
    r = assess_risk(RiskInput(files=[RiskFile("config.yaml")], tests=TestEvidence(passed=1), semantic_changes=[
        {"kind": "config_changed", "category": "configuration", "domains": ["Configuration"], "details": {"sensitive": True}}]))
    assert r.score == 20
    assert "secret-like key" in r.reasons[0]
