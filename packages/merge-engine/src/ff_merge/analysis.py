"""Range analysis shared by review, diff views and the merge gate."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ff_semantic import ChangeSet, DependencyGraph, SemanticDiff, build_dependency_graph, detect_language, semantic_diff
from ff_version import DiffResult, VersionEngine

MAX_GRAPH_FILES = 5000


@dataclass
class RangeAnalysis:
    base: str
    head: str
    diff: DiffResult
    semantic: SemanticDiff

    def changeset(self, engine: VersionEngine, repo_path: Path, name: str) -> ChangeSet:
        return ChangeSet(name=name, diff=self.semantic, graph=snapshot_graph(engine, repo_path, self.head))


def analyze_range(engine: VersionEngine, repo_path: Path, base: str, head: str) -> RangeAnalysis:
    diff = engine.diff(repo_path, base, head)
    old: dict[str, bytes | None] = {}
    new: dict[str, bytes | None] = {}
    for f in diff.files:
        if f.binary:
            old[f.path] = b"" if f.status != "A" else None
            new[f.path] = b"\0" if f.status != "D" else None
            continue
        old[f.path] = engine.read_file(repo_path, base, f.path) if f.status != "A" else None
        new[f.path] = engine.read_file(repo_path, head, f.path) if f.status != "D" else None
    return RangeAnalysis(base=base, head=head, diff=diff, semantic=semantic_diff(old, new))


def snapshot_graph(engine: VersionEngine, repo_path: Path, commit: str) -> DependencyGraph:
    return _snapshot_graph(engine, str(repo_path), commit)


@lru_cache(maxsize=64)
def _snapshot_graph(engine: VersionEngine, repo_path: str, commit: str) -> DependencyGraph:
    path = Path(repo_path)
    files = {}
    for f in engine.list_files(path, commit)[:MAX_GRAPH_FILES * 4]:
        if detect_language(f) is None:
            continue
        content = engine.read_file(path, commit, f)
        if content is not None:
            files[f] = content
        if len(files) >= MAX_GRAPH_FILES:
            break
    return build_dependency_graph(files)
