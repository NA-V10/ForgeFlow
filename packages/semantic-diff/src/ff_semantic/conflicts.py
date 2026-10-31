"""Semantic conflict detection between two concurrent change sets.

Two workspaces can merge cleanly at the text level and still break each other:
one changes a function's contract while the other adds a caller, or both edit the
same symbol in different regions. This module flags those cases from the symbol
diff and dependency graph of each side. It is intentionally conservative (it
prefers false positives), and every finding says why it was raised.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from .diff import SemanticChange, SemanticDiff
from .graph import DependencyGraph

SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


@dataclass
class ChangeSet:
    name: str  # e.g. workspace id or agent name, used in explanations
    diff: SemanticDiff
    graph: DependencyGraph  # graph of this side's head snapshot


@dataclass
class SemanticConflict:
    conflict_type: str
    severity: str
    affected_symbols: list[str]
    affected_files: list[str]
    explanation: str

    def to_dict(self) -> dict:
        return asdict(self)


_SYMBOL_CATEGORIES = {"functions", "classes", "variables"}


def _sym_changes(cs: ChangeSet) -> list[SemanticChange]:
    return [c for c in cs.diff.changes if c.symbol and c.category in _SYMBOL_CATEGORIES]


def _ids(cs: ChangeSet, suffixes: tuple[str, ...]) -> dict[str, SemanticChange]:
    return {c.symbol_id: c for c in _sym_changes(cs) if c.kind.endswith(suffixes)}  # type: ignore[misc]


def _touched(cs: ChangeSet) -> dict[str, SemanticChange]:
    """Symbols whose behaviour changed, including the class owning a changed method."""
    out = dict(_ids(cs, ("_modified", "_removed")))
    for c in _sym_changes(cs):
        if c.kind.endswith(("_modified", "_removed", "_added")) and c.symbol and "." in c.symbol:
            cls = f"{c.path}::{c.symbol.rsplit('.', 1)[0]}"
            out.setdefault(cls, c)
    return out


def _owner_group(graph: DependencyGraph, symbol_id: str) -> tuple[str, set[str]]:
    """Dependencies of a symbol, aggregated over its whole class if it belongs to one."""
    path, _, name = symbol_id.partition("::")
    cls = name.split(".", 1)[0]
    fs = graph.files.get(path)
    if fs is None:
        return name, graph.dependencies_of(symbol_id)
    if cls in fs.symbols and fs.symbols[cls].kind in ("class", "interface"):
        members = [f"{path}::{n}" for n in fs.symbols if n == cls or n.startswith(cls + ".")]
        deps: set[str] = set()
        for m in members:
            deps |= graph.dependencies_of(m)
        return cls, {d for d in deps if not d.startswith(f"{path}::{cls}.") and d != f"{path}::{cls}"}
    return name, graph.dependencies_of(symbol_id)


def _short(symbol_id: str) -> str:
    return symbol_id.split("::", 1)[1]


def _file(symbol_id: str) -> str:
    return symbol_id.split("::", 1)[0]


def _directional(a: ChangeSet, b: ChangeSet) -> list[SemanticConflict]:
    """Conflicts where something B changed depends on something A changed."""
    out: list[SemanticConflict] = []
    removed_a = _ids(a, ("_removed",))
    sig_a = {sid: c for sid, c in _ids(a, ("_modified",)).items() if c.details.get("signature_changed")}
    touched_a = _touched(a)
    seen: set[tuple[str, str]] = set()

    for change in _sym_changes(b):
        if change.kind.endswith("_removed"):
            continue
        sid = change.symbol_id
        assert sid is not None
        owner, deps = _owner_group(b.graph, sid)
        for dep in sorted(deps):
            key = (owner, dep)
            if key in seen:
                continue
            via = f" (via `{owner}`)" if owner != change.symbol else ""
            if dep in removed_a:
                seen.add(key)
                out.append(SemanticConflict(
                    conflict_type="broken_reference",
                    severity="CRITICAL",
                    affected_symbols=[_short(dep), change.symbol],  # type: ignore[list-item]
                    affected_files=sorted({_file(dep), change.path}),
                    explanation=f"{a.name} removed `{_short(dep)}`, but {b.name} changed `{change.symbol}`{via} "
                                f"which still references it.",
                ))
            elif dep in sig_a:
                seen.add(key)
                d = sig_a[dep].details
                out.append(SemanticConflict(
                    conflict_type="signature_change",
                    severity="HIGH",
                    affected_symbols=[_short(dep), change.symbol],  # type: ignore[list-item]
                    affected_files=sorted({_file(dep), change.path}),
                    explanation=f"{a.name} changed the signature of `{_short(dep)}` "
                                f"({d.get('old_signature')} → {d.get('new_signature')}) while {b.name} changed "
                                f"`{change.symbol}`{via}, which calls or uses it.",
                ))
            elif dep in touched_a:
                seen.add(key)
                out.append(SemanticConflict(
                    conflict_type="dependency_conflict",
                    severity="MEDIUM",
                    affected_symbols=[_short(dep), owner],
                    affected_files=sorted({_file(dep), change.path}),
                    explanation=f"{b.name} changed `{owner}`, which depends on `{_short(dep)}`; {a.name} modified "
                                f"`{_short(dep)}` concurrently. The combined behaviour has not been validated together.",
                ))
    return out


def detect_semantic_conflicts(a: ChangeSet, b: ChangeSet) -> list[SemanticConflict]:
    conflicts: list[SemanticConflict] = []

    # 1. both sides changed the same symbol
    a_syms = {c.symbol_id: c for c in _sym_changes(a)}
    b_syms = {c.symbol_id: c for c in _sym_changes(b)}
    for sid in sorted(set(a_syms) & set(b_syms)):
        ca, cb = a_syms[sid], b_syms[sid]
        both_added = ca.kind.endswith("_added") and cb.kind.endswith("_added")
        conflicts.append(SemanticConflict(
            conflict_type="duplicate_definition" if both_added else "same_symbol",
            severity="HIGH",
            affected_symbols=[ca.symbol],  # type: ignore[list-item]
            affected_files=[ca.path],
            explanation=(f"Both {a.name} and {b.name} define `{ca.symbol}` in {ca.path}." if both_added else
                         f"{a.name} ({ca.kind.replace('_', ' ')}) and {b.name} ({cb.kind.replace('_', ' ')}) both "
                         f"changed `{ca.symbol}` in {ca.path}; even if the text merges, the intent may not."),
        ))

    # 2. dependency-based conflicts, both directions
    conflicts += _directional(a, b)
    conflicts += _directional(b, a)

    # 3. routes
    def routes(cs: ChangeSet) -> dict[str, SemanticChange]:
        return {f"{c.details['method']} {c.details['path']}": c for c in cs.diff.changes
                if c.category == "apis" and c.kind != "route_removed"}

    ra, rb = routes(a), routes(b)
    for key in sorted(set(ra) & set(rb)):
        conflicts.append(SemanticConflict(
            conflict_type="route_collision", severity="HIGH",
            affected_symbols=sorted({s for s in (ra[key].symbol, rb[key].symbol) if s}),
            affected_files=sorted({ra[key].path, rb[key].path}),
            explanation=f"Both {a.name} and {b.name} add or change the API route {key}.",
        ))

    # 4. dependency versions
    def deps(cs: ChangeSet) -> dict[str, SemanticChange]:
        return {c.details["package"]: c for c in cs.diff.changes if c.category == "dependencies"}

    da, db = deps(a), deps(b)
    for pkg in sorted(set(da) & set(db)):
        va, vb = da[pkg].details.get("version"), db[pkg].details.get("version")
        if va != vb or da[pkg].kind != db[pkg].kind:
            conflicts.append(SemanticConflict(
                conflict_type="dependency_version", severity="MEDIUM",
                affected_symbols=[pkg], affected_files=sorted({da[pkg].path, db[pkg].path}),
                explanation=f"{a.name} sets {pkg} to {va or 'removed'} while {b.name} sets it to {vb or 'removed'}.",
            ))

    # 5. configuration keys
    def cfg(cs: ChangeSet) -> dict[tuple[str, str], SemanticChange]:
        return {(c.path, c.details["key"]): c for c in cs.diff.changes if c.category == "configuration" and
                "key" in c.details}

    ca_, cb_ = cfg(a), cfg(b)
    for path, key in sorted(set(ca_) & set(cb_)):
        conflicts.append(SemanticConflict(
            conflict_type="config_key", severity="MEDIUM", affected_symbols=[key], affected_files=[path],
            explanation=f"Both {a.name} and {b.name} change configuration key `{key}` in {path}.",
        ))

    # de-duplicate and order by severity
    unique: dict[tuple, SemanticConflict] = {}
    for c in conflicts:
        k = (c.conflict_type, tuple(sorted(c.affected_symbols)))
        if k not in unique or SEVERITY_ORDER[c.severity] > SEVERITY_ORDER[unique[k].severity]:
            unique[k] = c
    return sorted(unique.values(), key=lambda c: (-SEVERITY_ORDER[c.severity], c.conflict_type, c.affected_symbols))
