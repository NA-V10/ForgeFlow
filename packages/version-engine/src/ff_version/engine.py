"""Version engine protocol.

Everything ForgeFlow needs from a version store is expressed here. The Git
implementation lives in :mod:`ff_version.git`; a native content-addressed store
can replace it by implementing the same protocol.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable


class VersionEngineError(RuntimeError):
    """Raised when the underlying store rejects an operation."""


class RefUpdateConflict(VersionEngineError):
    """A compare-and-swap ref update lost a race."""


@dataclass(frozen=True)
class FileChange:
    path: str
    status: str  # A, M, D, R
    additions: int
    deletions: int
    old_path: str | None = None
    binary: bool = False


@dataclass(frozen=True)
class DiffResult:
    base: str
    head: str
    files: list[FileChange]
    patch: str

    @property
    def additions(self) -> int:
        return sum(f.additions for f in self.files)

    @property
    def deletions(self) -> int:
        return sum(f.deletions for f in self.files)


@dataclass(frozen=True)
class MergeCheck:
    clean: bool
    tree: str | None
    conflicting_files: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CommitInfo:
    sha: str
    parents: list[str]
    author: str
    message: str
    timestamp: int
    trailers: dict[str, str]


@dataclass(frozen=True)
class BlameLine:
    line_no: int
    commit: str
    content: str


@runtime_checkable
class VersionEngine(Protocol):
    name: str

    # repositories
    def init_repository(
        self, repo_path: Path, default_branch: str = "main", initial_files: dict[str, bytes] | None = None
    ) -> str: ...
    def import_repository(self, source: str, repo_path: Path) -> str: ...
    def resolve(self, repo_path: Path, rev: str) -> str: ...
    def branch_head(self, repo_path: Path, branch: str) -> str | None: ...
    def list_branches(self, repo_path: Path) -> dict[str, str]: ...
    def is_ancestor(self, repo_path: Path, ancestor: str, descendant: str) -> bool: ...

    # workspaces
    def create_worktree(self, repo_path: Path, worktree_path: Path, branch: str, base: str) -> None: ...
    def remove_worktree(self, repo_path: Path, worktree_path: Path, branch: str | None = None) -> None: ...
    def commit_all(
        self, worktree_path: Path, message: str, author: str, trailers: dict[str, str] | None = None,
        allow_empty: bool = False,
    ) -> str | None: ...
    def reset_hard(self, worktree_path: Path, commit: str) -> None: ...
    def has_uncommitted_changes(self, worktree_path: Path) -> bool: ...

    # inspection
    def diff(self, repo_path: Path, base: str, head: str, context: int = 3) -> DiffResult: ...
    def diff_worktree(self, worktree_path: Path, base: str) -> DiffResult: ...
    def read_file(self, repo_path: Path, commit: str, path: str) -> bytes | None: ...
    def list_files(self, repo_path: Path, commit: str) -> list[str]: ...
    def tree_id(self, repo_path: Path, commit: str) -> str: ...
    def commit_info(self, repo_path: Path, commit: str) -> CommitInfo: ...
    def log(self, repo_path: Path, rev: str, limit: int = 50) -> list[CommitInfo]: ...
    def blame(self, repo_path: Path, commit: str, path: str) -> list[BlameLine]: ...

    # merging
    def check_merge(self, repo_path: Path, ours: str, theirs: str) -> MergeCheck: ...
    def merge(
        self, repo_path: Path, target_branch: str, source: str, message: str, author: str,
        trailers: dict[str, str] | None = None, expected_head: str | None = None,
    ) -> str: ...
    def revert(
        self, repo_path: Path, target_branch: str, commit: str, message: str, author: str,
        trailers: dict[str, str] | None = None,
    ) -> str: ...
    def materialize(self, repo_path: Path, commit: str, dest: Path) -> None: ...
