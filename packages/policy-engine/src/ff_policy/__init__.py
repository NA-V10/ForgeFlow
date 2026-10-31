"""YAML policy engine.

A policy matches on any combination of ``action``, ``path``/``paths``, ``agent``,
``command``, ``min_risk`` and ``severity``; every listed condition must hold. Its
effect is one of ``deny``, ``require_approval``, ``require_review`` or ``allow``.

Evaluation is deterministic: all policies are evaluated in file order, and the
combined effect follows the precedence ``deny > require_approval > require_review
> allow > default``. An explicit ``allow`` never cancels a requirement; it only
matters when the policy set's default is ``deny``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from typing import Any

import yaml

EFFECTS = ("deny", "require_approval", "require_review", "allow")
_KNOWN_KEYS = {"name", "description", "action", "actions", "path", "paths", "agent", "agents", "command", "min_risk",
               "severity", "reason", "approvals", *EFFECTS}
_SEVERITY_RANK = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


class PolicyError(ValueError):
    pass


@lru_cache(maxsize=1024)
def _glob(pattern: str) -> re.Pattern[str]:
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def glob_match(value: str, pattern: str) -> bool:
    return bool(_glob(pattern).match(value))


def _action_match(action: str, pattern: str) -> bool:
    # actions are dotted ("deploy.production"); "*" matches one segment, "**" any
    return glob_match(action.replace(".", "/"), pattern.replace(".", "/"))


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    return [str(x) for x in v] if isinstance(v, list) else [str(v)]


@dataclass(frozen=True)
class Policy:
    name: str
    effect: str
    actions: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    min_risk: int | None = None
    severity: str | None = None
    approvals: int = 1
    reason: str | None = None
    description: str | None = None


@dataclass
class PolicyContext:
    action: str
    paths: list[str] = field(default_factory=list)
    agent: str | None = None
    command: str | None = None
    risk_score: int | None = None
    risk_severity: str | None = None


@dataclass
class PolicyMatch:
    policy: str
    effect: str
    reason: str
    matched_paths: list[str] = field(default_factory=list)
    approvals: int = 1


@dataclass
class PolicyDecision:
    effect: str  # ALLOW | DENY | REQUIRE_APPROVAL
    matches: list[PolicyMatch]
    reasons: list[str]

    @property
    def requirements(self) -> list[PolicyMatch]:
        return [m for m in self.matches if m.effect in ("require_approval", "require_review")]

    def to_dict(self) -> dict:
        return {"effect": self.effect, "reasons": self.reasons, "matches": [asdict(m) for m in self.matches],
                "requirements": [asdict(m) for m in self.requirements]}


@dataclass
class PolicySet:
    policies: list[Policy]
    default: str = "allow"

    @classmethod
    def from_yaml(cls, text: str) -> "PolicySet":
        try:
            data = yaml.safe_load(text) or {}
        except yaml.YAMLError as exc:
            raise PolicyError(f"invalid YAML: {exc}") from exc
        return cls.from_dict(data)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicySet":
        if not isinstance(data, dict):
            raise PolicyError("policy document must be a mapping")
        default = str(data.get("default", "allow")).lower()
        if default not in ("allow", "deny"):
            raise PolicyError("default must be 'allow' or 'deny'")
        items = data.get("policies") or []
        if not isinstance(items, list):
            raise PolicyError("'policies' must be a list")
        policies: list[Policy] = []
        names: set[str] = set()
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                raise PolicyError(f"policy #{i + 1} must be a mapping")
            name = str(item.get("name") or f"policy-{i + 1}")
            if name in names:
                raise PolicyError(f"duplicate policy name '{name}'")
            names.add(name)
            unknown = set(item) - _KNOWN_KEYS
            if unknown:
                raise PolicyError(f"policy '{name}': unknown keys {sorted(unknown)}")
            effects = [e for e in EFFECTS if item.get(e) is True]
            if len(effects) != 1:
                raise PolicyError(f"policy '{name}': exactly one of {', '.join(EFFECTS)} must be true")
            sev = item.get("severity")
            if sev is not None and str(sev).upper() not in _SEVERITY_RANK:
                raise PolicyError(f"policy '{name}': unknown severity {sev}")
            conditions = [item.get(k) for k in ("action", "actions", "path", "paths", "agent", "agents", "command",
                                                 "min_risk", "severity")]
            if all(c is None for c in conditions):
                raise PolicyError(f"policy '{name}': at least one match condition is required")
            policies.append(Policy(
                name=name,
                effect=effects[0],
                actions=tuple(_as_list(item.get("action")) + _as_list(item.get("actions"))),
                paths=tuple(_as_list(item.get("path")) + _as_list(item.get("paths"))),
                agents=tuple(_as_list(item.get("agent")) + _as_list(item.get("agents"))),
                commands=tuple(_as_list(item.get("command"))),
                min_risk=int(item["min_risk"]) if item.get("min_risk") is not None else None,
                severity=str(sev).upper() if sev else None,
                approvals=int(item.get("approvals", 1)),
                reason=item.get("reason"),
                description=item.get("description"),
            ))
        return cls(policies=policies, default=default)

    def evaluate(self, ctx: PolicyContext) -> PolicyDecision:
        matches: list[PolicyMatch] = []
        for p in self.policies:
            m = _match(p, ctx)
            if m is not None:
                matches.append(m)
        effects = {m.effect for m in matches}
        if "deny" in effects:
            effect = "DENY"
        elif effects & {"require_approval", "require_review"}:
            effect = "REQUIRE_APPROVAL"
        elif "allow" in effects or self.default == "allow":
            effect = "ALLOW"
        else:
            effect = "DENY"
        reasons = [m.reason for m in matches]
        if effect == "DENY" and not matches:
            reasons = [f"no policy allows action '{ctx.action}' (default: deny)"]
        return PolicyDecision(effect=effect, matches=matches, reasons=reasons)


def _match(p: Policy, ctx: PolicyContext) -> PolicyMatch | None:
    if p.actions and not any(_action_match(ctx.action, a) for a in p.actions):
        return None
    if p.agents and not (ctx.agent and any(glob_match(ctx.agent, a) for a in p.agents)):
        return None
    if p.commands and not (ctx.command and any(glob_match(ctx.command, c) for c in p.commands)):
        return None
    matched_paths: list[str] = []
    if p.paths:
        matched_paths = sorted({path for path in ctx.paths if any(glob_match(path, g) for g in p.paths)})
        if not matched_paths:
            return None
    if p.min_risk is not None and (ctx.risk_score is None or ctx.risk_score < p.min_risk):
        return None
    if p.severity is not None and (
        ctx.risk_severity is None or _SEVERITY_RANK.get(ctx.risk_severity, -1) < _SEVERITY_RANK[p.severity]
    ):
        return None
    verb = {"deny": "denies", "require_approval": "requires approval for",
            "require_review": "requires review of", "allow": "allows"}[p.effect]
    subject = ", ".join(matched_paths[:3]) + (" …" if len(matched_paths) > 3 else "") if matched_paths else \
        f"action '{ctx.action}'"
    extra = []
    if p.min_risk is not None:
        extra.append(f"risk {ctx.risk_score} ≥ {p.min_risk}")
    if p.severity is not None:
        extra.append(f"severity {ctx.risk_severity} ≥ {p.severity}")
    reason = p.reason or f"policy '{p.name}' {verb} {subject}" + (f" ({'; '.join(extra)})" if extra else "")
    return PolicyMatch(policy=p.name, effect=p.effect, reason=reason, matched_paths=matched_paths,
                       approvals=p.approvals)


DEFAULT_POLICY_YAML = """\
version: 1
default: allow
policies:
  - name: production-protection
    action: deploy.production
    require_approval: true

  - name: database-delete
    action: database.drop
    deny: true

  - name: dependency-change
    paths: [package.json, "**/package.json", requirements*.txt, pyproject.toml]
    require_review: true

  - name: security-code
    paths: ["security/**", "**/security/**", "auth/**", "**/auth/**", "**/auth.py", "**/*oauth*",
            "**/permissions.py", "**/middleware/auth*"]
    require_review: true

  - name: high-risk-merge
    action: merge
    min_risk: 60
    require_approval: true
    reason: merges with risk score of 60 or more need explicit approval

  - name: no-force-push
    action: command.run
    command: "git push*--force*"
    deny: true
"""

__all__ = [
    "DEFAULT_POLICY_YAML", "EFFECTS", "Policy", "PolicyContext", "PolicyDecision", "PolicyError", "PolicyMatch",
    "PolicySet", "glob_match",
]
