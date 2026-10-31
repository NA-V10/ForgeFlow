"""Deterministic risk scoring.

The score is a sum of explainable, weighted signals computed from the diff,
the semantic diff, test evidence and detected conflicts. No model is involved;
the same inputs always produce the same score and the same reasons.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

SEVERITIES = ("LOW", "MEDIUM", "HIGH", "CRITICAL")


@lru_cache(maxsize=512)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pattern.startswith("**", i):
            out += ".*"
            i += 2
        elif pattern[i] == "*":
            out += "[^/]*"
            i += 1
        elif pattern[i] == "?":
            out += "[^/]"
            i += 1
        else:
            out += re.escape(pattern[i])
            i += 1
    return re.compile(out + r"\Z")


def glob_match(path: str, pattern: str) -> bool:
    return bool(_glob_regex(pattern).match(path))


@dataclass
class RiskConfig:
    sensitive_paths: list[str] = field(default_factory=lambda: [
        "security/**", "**/security/**", "auth/**", "**/auth/**", "**/secrets*", "**/*.pem", "**/*.key",
        ".env*", "**/.env*", ".github/workflows/**", "infra/**", "infrastructure/**", "**/Dockerfile",
        "deploy/**", "**/permissions*",
    ])
    thresholds: tuple[int, int, int] = (30, 60, 85)  # MEDIUM, HIGH, CRITICAL lower bounds


@dataclass
class RiskFile:
    path: str
    status: str = "M"
    additions: int = 0
    deletions: int = 0


@dataclass
class TestEvidence:
    __test__ = False  # not a pytest test class

    passed: int = 0
    failed: int = 0
    errors: int = 0
    ran: bool = True

    @property
    def failing(self) -> int:
        return self.failed + self.errors


@dataclass
class RiskInput:
    files: list[RiskFile]
    semantic_changes: list[Mapping[str, Any]] = field(default_factory=list)
    tests: TestEvidence | None = None
    conflicts: list[Mapping[str, Any]] = field(default_factory=list)


@dataclass
class RiskSignal:
    name: str
    points: int
    reason: str


@dataclass
class RiskResult:
    score: int
    severity: str
    reasons: list[str]
    signals: list[RiskSignal]

    def to_dict(self) -> dict:
        return asdict(self)

    def render(self) -> str:
        lines = [f"{self.score} / 100", "", self.severity, "", "Reasons:"]
        lines += [f"- {r}" for r in self.reasons] or ["- no risk signals"]
        return "\n".join(lines)


def _tier(value: int, tiers: Iterable[tuple[int, int]]) -> int:
    points = 0
    for threshold, pts in tiers:
        if value > threshold:
            points = pts
    return points


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def severity_for(score: int, thresholds: tuple[int, int, int] = (30, 60, 85)) -> str:
    medium, high, critical = thresholds
    if score >= critical:
        return "CRITICAL"
    if score >= high:
        return "HIGH"
    if score >= medium:
        return "MEDIUM"
    return "LOW"


def assess_risk(inp: RiskInput, config: RiskConfig | None = None) -> RiskResult:
    cfg = config or RiskConfig()
    signals: list[RiskSignal] = []

    def add(name: str, points: int, reason: str) -> None:
        if points:
            signals.append(RiskSignal(name=name, points=points, reason=reason))

    n_files = len(inp.files)
    lines = sum(f.additions + f.deletions for f in inp.files)
    add("files_changed", _tier(n_files, [(5, 5), (15, 10), (40, 20)]), f"{_plural(n_files, 'file')} changed")
    add("lines_changed", _tier(lines, [(100, 5), (500, 10), (1500, 20)]), f"{lines} lines changed")

    sensitive = sorted({f.path for f in inp.files if any(glob_match(f.path, p) for p in cfg.sensitive_paths)})
    if sensitive:
        shown = ", ".join(sensitive[:3]) + (f" (+{len(sensitive) - 3} more)" if len(sensitive) > 3 else "")
        add("sensitive_paths", min(25, 15 + 5 * (len(sensitive) - 1)), f"sensitive paths changed: {shown}")

    changes = list(inp.semantic_changes)

    def count(pred) -> int:
        return sum(1 for c in changes if pred(c))

    def domains(c) -> list[str]:
        return list(c.get("domains") or [])

    def is_code(c) -> bool:
        return c.get("category") in ("functions", "classes", "apis", "imports", "variables", "files")

    dep_added = count(lambda c: c.get("kind") == "dependency_added")
    dep_other = count(lambda c: c.get("kind") in ("dependency_removed", "dependency_changed"))
    if dep_added or dep_other:
        parts = []
        if dep_added:
            parts.append(f"{_plural(dep_added, 'dependency')} added")
        if dep_other:
            parts.append(f"{_plural(dep_other, 'dependency')} changed or removed")
        add("dependencies", min(20, 10 * dep_added + 5 * dep_other), ", ".join(parts))

    migrations = sorted({f.path for f in inp.files if "migrations/" in f.path.lower()
                         or "alembic/versions" in f.path.lower()})
    if migrations:
        add("database_migration", 15, f"database migration changed: {', '.join(migrations[:3])}")

    is_test = lambda c: "Tests" in domains(c)  # noqa: E731
    authn = count(lambda c: is_code(c) and "Authentication" in domains(c) and not is_test(c))
    if authn:
        add("authentication", 20, f"authentication code changed ({_plural(authn, 'change')})")
    authz = count(lambda c: is_code(c) and "Authorization" in domains(c) and not is_test(c))
    if authz:
        add("authorization", 20, f"authorization code changed ({_plural(authz, 'change')})")
    security = count(lambda c: "Security" in domains(c) and not is_test(c))
    if security:
        add("security", 10, f"security-sensitive code or settings changed ({_plural(security, 'change')})")

    routes_added = count(lambda c: c.get("kind") == "route_added")
    routes_changed = count(lambda c: c.get("kind") in ("route_changed", "route_removed"))
    if routes_added or routes_changed:
        parts = []
        if routes_changed:
            parts.append(f"public API modified ({_plural(routes_changed, 'route')})")
        if routes_added:
            parts.append(f"{_plural(routes_added, 'route')} added")
        add("public_api", min(20, 15 * min(routes_changed, 1) + 5 * routes_added), ", ".join(parts))

    config_changes = [c for c in changes if c.get("category") == "configuration"]
    if config_changes:
        sensitive_cfg = [c for c in config_changes if (c.get("details") or {}).get("sensitive")]
        pts = 5 + (15 if sensitive_cfg else 0)
        reason = f"configuration changed ({_plural(len(config_changes), 'key')})"
        if sensitive_cfg:
            reason += f", including {_plural(len(sensitive_cfg), 'secret-like key')}"
        add("configuration", pts, reason)

    tests = inp.tests
    if tests is None or not tests.ran:
        add("no_test_evidence", 10, "no test results recorded")
    elif tests.failing:
        add("test_failures", 25 + (10 if tests.failing > 5 else 0), f"{_plural(tests.failing, 'test')} failing")

    sev_points = {"CRITICAL": 30, "HIGH": 20, "MEDIUM": 10, "LOW": 3}
    if inp.conflicts:
        worst = max(inp.conflicts, key=lambda c: SEVERITIES.index(c.get("severity", "LOW")))
        add("semantic_conflicts", sev_points[worst.get("severity", "LOW")],
            f"{_plural(len(inp.conflicts), 'semantic conflict')} with concurrent work "
            f"(worst: {worst.get('severity')} {worst.get('conflict_type')})")

    tests_added = count(lambda c: is_test(c) and str(c.get("kind", "")).endswith("_added"))
    raw = sum(s.points for s in signals)
    if tests_added and raw:
        signals.append(RiskSignal(name="tests_added", points=-min(5, raw),
                                  reason=f"mitigation: {_plural(tests_added, 'test')} added"))

    score = max(0, min(100, sum(s.points for s in signals)))
    ordered = sorted(signals, key=lambda s: -s.points)
    return RiskResult(score=score, severity=severity_for(score, cfg.thresholds),
                      reasons=[s.reason for s in ordered], signals=ordered)


__all__ = [
    "RiskConfig", "RiskFile", "RiskInput", "RiskResult", "RiskSignal", "SEVERITIES", "TestEvidence",
    "assess_risk", "glob_match", "severity_for",
]
