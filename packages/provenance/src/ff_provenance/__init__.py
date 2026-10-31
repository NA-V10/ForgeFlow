"""Provenance: who and what produced each line of code.

Every commit ForgeFlow creates carries trailers identifying the execution, agent,
task, workspace and model. Combined with ``blame`` this answers
"why does this line exist?" by walking

    line → file → commit → change → execution → agent → task → model

The package is storage-agnostic: callers supply a version engine (anything with
``blame`` and ``commit_info``) and a resolver that looks ids up in their database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

TRAILER_PREFIX = "ForgeFlow-"
KEYS = ("Execution", "Agent", "Task", "Workspace", "Model", "Checkpoint", "Merge", "Kind")


def build_trailers(**values: Any) -> dict[str, str]:
    """``build_trailers(execution=..., agent=...)`` → ``{"ForgeFlow-Execution": ...}``."""
    out: dict[str, str] = {}
    for key in KEYS:
        v = values.get(key.lower())
        if v is not None and v != "":
            out[TRAILER_PREFIX + key] = str(v)
    return out


@dataclass(frozen=True)
class ProvenanceRef:
    execution: str | None = None
    agent: str | None = None
    task: str | None = None
    workspace: str | None = None
    model: str | None = None
    checkpoint: str | None = None
    merge: str | None = None
    kind: str | None = None

    @property
    def is_forgeflow(self) -> bool:
        return any((self.execution, self.agent, self.task, self.merge, self.checkpoint))


def parse_trailers(trailers: dict[str, str]) -> ProvenanceRef:
    values = {k[len(TRAILER_PREFIX):].lower(): v for k, v in trailers.items() if k.startswith(TRAILER_PREFIX)}
    return ProvenanceRef(**{k: values.get(k) for k in ProvenanceRef.__dataclass_fields__})


class _Engine(Protocol):
    def blame(self, repo_path: Path, commit: str, path: str) -> list[Any]: ...
    def commit_info(self, repo_path: Path, commit: str) -> Any: ...


class Resolver(Protocol):
    def resolve(self, ref: ProvenanceRef, commit_sha: str, path: str) -> dict[str, Any]:
        """Return records keyed by ``change``, ``execution``, ``agent``, ``task`` (any may be missing)."""
        ...


@dataclass
class LineProvenance:
    path: str
    line: int
    content: str
    commit: str
    commit_author: str
    commit_message: str
    origin: str  # "agent" | "human"
    ref: ProvenanceRef
    chain: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["ref"] = asdict(self.ref)
        return d

    def explain(self) -> str:
        if self.origin == "human":
            return (f"{self.path}:{self.line} was introduced by commit {self.commit[:10]} "
                    f"({self.commit_author}) outside ForgeFlow: \"{self.commit_message.splitlines()[0]}\".")
        steps = " → ".join(f"{c['type']} {c.get('label') or c.get('id')}" for c in self.chain)
        return f"{self.path}:{self.line} ← {steps}"


def trace_line(engine: _Engine, repo_path: Path, commit: str, path: str, line: int,
               resolver: Resolver | None = None) -> LineProvenance:
    blame = engine.blame(repo_path, commit, path)
    entry = next((b for b in blame if b.line_no == line), None)
    if entry is None:
        raise ValueError(f"{path} has no line {line} at {commit[:10]}")
    info = engine.commit_info(repo_path, entry.commit)
    ref = parse_trailers(info.trailers)
    lp = LineProvenance(path=path, line=line, content=entry.content, commit=entry.commit, commit_author=info.author,
                        commit_message=info.message, origin="agent" if ref.is_forgeflow else "human", ref=ref)
    lp.chain.append({"type": "line", "id": f"{path}:{line}", "label": entry.content.strip()[:80]})
    lp.chain.append({"type": "file", "id": path, "label": path})
    lp.chain.append({"type": "commit", "id": entry.commit, "label": entry.commit[:10]})
    records = resolver.resolve(ref, entry.commit, path) if resolver and ref.is_forgeflow else {}
    for kind in ("change", "execution", "agent", "task"):
        rec = records.get(kind)
        if rec:
            lp.chain.append({"type": kind, **rec})
        elif kind == "execution" and ref.execution:
            lp.chain.append({"type": kind, "id": ref.execution, "label": ref.execution})
        elif kind == "agent" and ref.agent:
            lp.chain.append({"type": kind, "id": ref.agent, "label": ref.agent})
        elif kind == "task" and ref.task:
            lp.chain.append({"type": kind, "id": ref.task, "label": ref.task})
    if ref.model:
        lp.chain.append({"type": "model", "id": ref.model, "label": ref.model})
    return lp


__all__ = ["KEYS", "LineProvenance", "ProvenanceRef", "Resolver", "TRAILER_PREFIX", "build_trailers",
           "parse_trailers", "trace_line"]
