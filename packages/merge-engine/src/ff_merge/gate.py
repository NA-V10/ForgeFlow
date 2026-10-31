"""The merge gate.

Runs the seven pre-merge checks and produces one of ``READY``, ``BLOCKED``,
``REQUIRES_APPROVAL`` or ``CONFLICT`` with human-readable reasons:

1. verify base commit
2. check textual conflicts
3. run semantic conflict detection
4. evaluate policies
5. calculate risk
6. run configured tests
7. check approval requirements

Checks are evaluated in dependency order (tests → risk → policy) but reported in
the order above. The gate is pure decision logic: it does not merge, persist or
create approvals itself.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ff_policy import PolicyContext, PolicyDecision, PolicySet
from ff_risk import RiskConfig, RiskFile, RiskInput, RiskResult, TestEvidence, assess_risk
from ff_sandbox import TestSummary
from ff_semantic import ChangeSet, SemanticConflict, detect_semantic_conflicts
from ff_version import MergeCheck, VersionEngine

from .analysis import RangeAnalysis, analyze_range

READY, BLOCKED, REQUIRES_APPROVAL, CONFLICT = "READY", "BLOCKED", "REQUIRES_APPROVAL", "CONFLICT"

TestRunner = Callable[[str, str, str], TestSummary | None]  # (target_head, ws_head, merge_tree)


@dataclass
class MergeRequest:
    repo_path: Path
    target_branch: str
    base_commit: str
    head_commit: str
    name: str  # human label for the workspace, used in explanations
    agent: str | None = None


@dataclass
class OpenChangeSet:
    """Another not-yet-merged workspace, for advisory semantic conflict checks."""
    name: str
    changeset: ChangeSet


@dataclass
class Requirement:
    key: str  # stable id used to match approvals, e.g. "policy:security-code"
    kind: str  # policy | semantic_conflict
    reason: str
    approvals_required: int = 1
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateCheck:
    step: int
    name: str
    status: str  # pass | fail | warn | skip
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class MergeEvaluation:
    decision: str
    reasons: list[str]
    checks: list[GateCheck]
    requirements: list[Requirement]
    target_head: str | None
    merge_tree: str | None
    risk: RiskResult | None = None
    policy: PolicyDecision | None = None
    semantic_conflicts: list[SemanticConflict] = field(default_factory=list)
    advisory_conflicts: list[dict[str, Any]] = field(default_factory=list)
    textual_conflicts: list[str] = field(default_factory=list)
    tests: TestSummary | None = None
    analysis: RangeAnalysis | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "reasons": self.reasons,
            "checks": [asdict(c) for c in self.checks],
            "requirements": [asdict(r) for r in self.requirements],
            "target_head": self.target_head,
            "merge_tree": self.merge_tree,
            "risk": self.risk.to_dict() if self.risk else None,
            "policy": self.policy.to_dict() if self.policy else None,
            "semantic_conflicts": [c.to_dict() for c in self.semantic_conflicts],
            "advisory_conflicts": self.advisory_conflicts,
            "textual_conflicts": self.textual_conflicts,
            "tests": self.tests.to_dict() if self.tests else None,
        }


class MergeGate:
    def __init__(self, engine: VersionEngine, policies: PolicySet, risk_config: RiskConfig | None = None,
                 require_tests: bool = False) -> None:
        self.engine = engine
        self.policies = policies
        self.risk_config = risk_config or RiskConfig()
        self.require_tests = require_tests

    def evaluate(
        self,
        req: MergeRequest,
        approvals: dict[str, str] | None = None,
        run_tests: TestRunner | None = None,
        open_changesets: list[OpenChangeSet] | None = None,
    ) -> MergeEvaluation:
        approvals = approvals or {}
        checks: dict[int, GateCheck] = {}
        reasons: list[str] = []
        blocked = conflict = False
        engine, repo = self.engine, req.repo_path

        target_head = engine.branch_head(repo, req.target_branch)

        # 1. base commit
        if target_head is None:
            checks[1] = GateCheck(1, "verify base commit", "fail", f"target branch {req.target_branch} not found")
            return self._finish(BLOCKED, [checks[1].summary], checks, [], None, None)
        base_ok = engine.is_ancestor(repo, req.base_commit, target_head)
        head_ok = engine.is_ancestor(repo, req.base_commit, req.head_commit)
        if not (base_ok and head_ok):
            why = ("base commit is not part of the target branch history" if not base_ok
                   else "workspace head does not descend from its base commit")
            checks[1] = GateCheck(1, "verify base commit", "fail", why,
                                  {"base": req.base_commit, "target_head": target_head})
            return self._finish(BLOCKED, [why], checks, [], target_head, None)
        if req.head_commit == req.base_commit:
            checks[1] = GateCheck(1, "verify base commit", "fail", "workspace has no committed changes")
            return self._finish(BLOCKED, ["workspace has no committed changes; create a checkpoint first"], checks,
                                [], target_head, None)
        moved = target_head != req.base_commit
        checks[1] = GateCheck(
            1, "verify base commit", "pass",
            f"base {req.base_commit[:10]} is in {req.target_branch}" +
            (f"; {req.target_branch} has moved to {target_head[:10]}" if moved else " and is current"),
            {"base": req.base_commit, "target_head": target_head, "target_moved": moved},
        )

        # 2. textual conflicts
        mc: MergeCheck = engine.check_merge(repo, target_head, req.head_commit)
        if not mc.clean:
            checks[2] = GateCheck(2, "textual conflicts", "fail",
                                  f"{len(mc.conflicting_files)} file(s) conflict: {', '.join(mc.conflicting_files)}",
                                  {"files": mc.conflicting_files, "messages": mc.messages})
            for i, name in ((3, "semantic conflicts"), (4, "policies"), (5, "risk"), (6, "tests"), (7, "approvals")):
                checks[i] = GateCheck(i, name, "skip", "skipped because of textual conflicts")
            ev = self._finish(CONFLICT, [f"textual conflict in {f}" for f in mc.conflicting_files], checks, [],
                              target_head, None)
            ev.textual_conflicts = mc.conflicting_files
            return ev
        checks[2] = GateCheck(2, "textual conflicts", "pass", "merges cleanly", {"tree": mc.tree})

        analysis = analyze_range(engine, repo, req.base_commit, req.head_commit)

        # 3. semantic conflicts against work merged since the base, and advisory against open workspaces
        mine = analysis.changeset(engine, repo, req.name)
        semantic: list[SemanticConflict] = []
        if moved:
            merged = analyze_range(engine, repo, req.base_commit, target_head).changeset(
                engine, repo, f"{req.target_branch} (merged since base)")
            semantic = detect_semantic_conflicts(merged, mine)
        advisory: list[dict[str, Any]] = []
        for other in open_changesets or []:
            for c in detect_semantic_conflicts(other.changeset, mine):
                advisory.append({"with": other.name, **c.to_dict()})
        requirements: list[Requirement] = []
        critical = [c for c in semantic if c.severity == "CRITICAL"]
        if critical:
            conflict = True
            reasons += [f"semantic conflict ({c.conflict_type}): {c.explanation}" for c in critical]
            checks[3] = GateCheck(3, "semantic conflicts", "fail", f"{len(critical)} critical semantic conflict(s)",
                                  {"conflicts": [c.to_dict() for c in semantic], "advisory": advisory})
        elif semantic:
            for c in semantic:
                key = "semantic:" + c.conflict_type + ":" + ",".join(sorted(c.affected_symbols))
                requirements.append(Requirement(key=key, kind="semantic_conflict",
                                                reason=f"{c.severity} semantic conflict: {c.explanation}",
                                                details=c.to_dict()))
            checks[3] = GateCheck(3, "semantic conflicts", "warn",
                                  f"{len(semantic)} semantic conflict(s) with work merged since base need sign-off",
                                  {"conflicts": [c.to_dict() for c in semantic], "advisory": advisory})
        else:
            checks[3] = GateCheck(3, "semantic conflicts", "warn" if advisory else "pass",
                                  "no conflicts with merged work" +
                                  (f"; {len(advisory)} potential conflict(s) with other open workspaces"
                                   if advisory else ""),
                                  {"conflicts": [], "advisory": advisory})

        # 6. tests (run before risk so failures feed the score)
        tests: TestSummary | None = None
        if run_tests is not None and mc.tree:
            tests = run_tests(target_head, req.head_commit, mc.tree)
        if tests is None:
            status = "fail" if self.require_tests else "warn"
            checks[6] = GateCheck(6, "tests", status, "no test command configured" if run_tests is None
                                  else "tests did not produce results")
            if self.require_tests:
                blocked = True
                reasons.append("tests are required but no results were produced")
        elif tests.failed or tests.errors:
            blocked = True
            reasons.append(f"{tests.failed + tests.errors} test(s) failing on the merged tree")
            checks[6] = GateCheck(6, "tests", "fail", f"{tests.passed} passed, {tests.failed} failed, "
                                  f"{tests.errors} errors on the merged tree", tests.to_dict())
        else:
            checks[6] = GateCheck(6, "tests", "pass", f"{tests.passed} passed on the merged tree", tests.to_dict())

        # 5. risk
        risk = assess_risk(RiskInput(
            files=[RiskFile(f.path, f.status, f.additions, f.deletions) for f in analysis.diff.files],
            semantic_changes=[c.to_dict() for c in analysis.semantic.changes],
            tests=TestEvidence(tests.passed, tests.failed, tests.errors) if tests else None,
            conflicts=[c.to_dict() for c in semantic],
        ), self.risk_config)
        checks[5] = GateCheck(5, "risk", "pass" if risk.severity in ("LOW", "MEDIUM") else "warn",
                              f"{risk.score}/100 {risk.severity}", risk.to_dict())

        # 4. policies
        policy = self.policies.evaluate(PolicyContext(
            action="merge", paths=[f.path for f in analysis.diff.files], agent=req.agent,
            risk_score=risk.score, risk_severity=risk.severity,
        ))
        if policy.effect == "DENY":
            blocked = True
            reasons += policy.reasons
            checks[4] = GateCheck(4, "policies", "fail", "; ".join(policy.reasons), policy.to_dict())
        else:
            for m in policy.requirements:
                requirements.append(Requirement(key=f"policy:{m.policy}", kind="policy", reason=m.reason,
                                                approvals_required=m.approvals,
                                                details={"effect": m.effect, "paths": m.matched_paths}))
            checks[4] = GateCheck(4, "policies", "warn" if policy.requirements else "pass",
                                  f"{len(policy.requirements)} approval requirement(s)" if policy.requirements
                                  else "no policy objections", policy.to_dict())

        # 7. approvals
        pending, rejected = [], []
        for r in requirements:
            status = approvals.get(r.key, "MISSING")
            if status == "REJECTED":
                rejected.append(r)
            elif status != "APPROVED":
                pending.append(r)
        if rejected:
            blocked = True
            reasons += [f"approval rejected: {r.reason}" for r in rejected]
            checks[7] = GateCheck(7, "approvals", "fail", f"{len(rejected)} approval(s) rejected",
                                  {"rejected": [r.key for r in rejected], "pending": [r.key for r in pending]})
        elif pending:
            checks[7] = GateCheck(7, "approvals", "warn", f"{len(pending)} of {len(requirements)} approval(s) pending",
                                  {"pending": [r.key for r in pending]})
        else:
            checks[7] = GateCheck(7, "approvals", "pass",
                                  f"all {len(requirements)} approval(s) granted" if requirements
                                  else "no approvals required")

        if conflict:
            decision = CONFLICT
        elif blocked:
            decision = BLOCKED
        elif pending:
            decision = REQUIRES_APPROVAL
            reasons += [f"approval required: {r.reason}" for r in pending]
        else:
            decision = READY
            reasons.append(f"all checks passed; risk {risk.score}/100 {risk.severity}")

        ev = self._finish(decision, reasons, checks, requirements, target_head, mc.tree)
        ev.risk, ev.policy, ev.tests, ev.analysis = risk, policy, tests, analysis
        ev.semantic_conflicts, ev.advisory_conflicts = semantic, advisory
        return ev

    @staticmethod
    def _finish(decision: str, reasons: list[str], checks: dict[int, GateCheck], requirements: list[Requirement],
                target_head: str | None, tree: str | None) -> MergeEvaluation:
        return MergeEvaluation(decision=decision, reasons=reasons, checks=[checks[k] for k in sorted(checks)],
                               requirements=requirements, target_head=target_head, merge_tree=tree)
