"""Git implementation of :class:`ff_version.engine.VersionEngine`.

Managed repositories are *bare*. Agents work in ``git worktree`` checkouts; merges
and reverts are performed with plumbing (``merge-tree --write-tree``, ``commit-tree``,
``update-ref <new> <old>``) so they never need a working tree and are atomic
compare-and-swap operations on the target ref.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from filelock import FileLock

from .engine import (
    BlameLine,
    CommitInfo,
    DiffResult,
    FileChange,
    MergeCheck,
    RefUpdateConflict,
    VersionEngineError,
)

_AUTHOR_RE = re.compile(r"^\s*(?P<name>[^<]+?)\s*<(?P<email>[^>]*)>\s*$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_RECORD_SEP = "\x1e"
_FIELD_SEP = "\x1f"

# Settings that make git output stable and keep repository-provided hooks/filters
# from running inside the control plane.
_BASE_CONFIG = [
    "-c", "core.autocrlf=false",
    "-c", "core.quotepath=false",
    "-c", "core.longpaths=true",
    "-c", "core.hooksPath=" + os.devnull,
    "-c", "commit.gpgsign=false",
    "-c", "advice.detachedHead=false",
    "-c", "init.defaultBranch=main",
]


def _split_author(author: str) -> tuple[str, str]:
    m = _AUTHOR_RE.match(author)
    if m:
        return m.group("name"), m.group("email")
    return author, f"{re.sub(r'[^a-zA-Z0-9._-]+', '-', author) or 'forgeflow'}@forgeflow.local"


def format_trailers(message: str, trailers: dict[str, str] | None) -> str:
    message = message.rstrip() + "\n"
    if trailers:
        message += "\n" + "".join(f"{k}: {v}\n" for k, v in trailers.items())
    return message


class GitEngine:
    name = "git"

    def __init__(self, git_binary: str = "git", timeout: float = 120.0) -> None:
        self.git_binary = git_binary
        self.timeout = timeout

    # ------------------------------------------------------------------ helpers
    def _run(
        self,
        cwd: Path,
        *args: str,
        input: bytes | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
        ok_codes: tuple[int, ...] = (0,),
    ) -> subprocess.CompletedProcess[bytes]:
        full_env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "GIT_CONFIG_NOSYSTEM": "1",
        }
        if env:
            full_env.update(env)
        proc = subprocess.run(
            [self.git_binary, *_BASE_CONFIG, *args],
            cwd=str(cwd),
            input=input,
            capture_output=True,
            env=full_env,
            timeout=self.timeout,
        )
        if check and proc.returncode not in ok_codes:
            raise VersionEngineError(
                f"git {' '.join(args)} failed ({proc.returncode}): "
                f"{proc.stderr.decode('utf-8', 'replace').strip()}"
            )
        return proc

    def _out(self, cwd: Path, *args: str, **kw) -> str:
        return self._run(cwd, *args, **kw).stdout.decode("utf-8", "replace")

    def _identity_env(self, author: str) -> dict[str, str]:
        name, email = _split_author(author)
        return {
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": "ForgeFlow",
            "GIT_COMMITTER_EMAIL": "control-plane@forgeflow.local",
        }

    def _lock(self, repo_path: Path) -> FileLock:
        return FileLock(str(repo_path / "forgeflow.lock"), timeout=60)

    # ------------------------------------------------------------- repositories
    def init_repository(
        self, repo_path: Path, default_branch: str = "main", initial_files: dict[str, bytes] | None = None
    ) -> str:
        repo_path.mkdir(parents=True, exist_ok=True)
        self._run(repo_path, "init", "--bare", "-q", "-b", default_branch, ".")
        files = initial_files or {"README.md": b"# New ForgeFlow repository\n"}
        tree = self._build_tree(repo_path, files)
        commit = self._out(
            repo_path, "commit-tree", tree, "-m", "Initial commit",
            env=self._identity_env("ForgeFlow <control-plane@forgeflow.local>"),
        ).strip()
        self._run(repo_path, "update-ref", f"refs/heads/{default_branch}", commit)
        return commit

    def _build_tree(self, repo_path: Path, files: dict[str, bytes]) -> str:
        with tempfile.TemporaryDirectory() as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            for rel, content in sorted(files.items()):
                blob = self._out(repo_path, "hash-object", "-w", "--stdin", input=content).strip()
                self._run(repo_path, "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}", env=env)
            return self._out(repo_path, "write-tree", env=env).strip()

    def import_repository(self, source: str, repo_path: Path) -> str:
        repo_path.parent.mkdir(parents=True, exist_ok=True)
        self._run(repo_path.parent, "clone", "--bare", "-q", "--no-hardlinks", source, str(repo_path))
        return self.resolve(repo_path, "HEAD")

    def default_branch(self, repo_path: Path) -> str:
        ref = self._out(repo_path, "symbolic-ref", "--short", "HEAD").strip()
        return ref or "main"

    def resolve(self, repo_path: Path, rev: str) -> str:
        return self._out(repo_path, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()

    def branch_head(self, repo_path: Path, branch: str) -> str | None:
        proc = self._run(repo_path, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
        out = proc.stdout.decode().strip()
        return out if proc.returncode == 0 and out else None

    def list_branches(self, repo_path: Path) -> dict[str, str]:
        out = self._out(repo_path, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads")
        result: dict[str, str] = {}
        for line in out.splitlines():
            if line.strip():
                name, sha = line.rsplit(" ", 1)
                result[name] = sha
        return result

    def is_ancestor(self, repo_path: Path, ancestor: str, descendant: str) -> bool:
        proc = self._run(repo_path, "merge-base", "--is-ancestor", ancestor, descendant, check=False)
        if proc.returncode not in (0, 1):
            raise VersionEngineError(proc.stderr.decode("utf-8", "replace"))
        return proc.returncode == 0

    def merge_base(self, repo_path: Path, a: str, b: str) -> str | None:
        proc = self._run(repo_path, "merge-base", a, b, check=False)
        return proc.stdout.decode().strip() or None

    # --------------------------------------------------------------- workspaces
    def create_worktree(self, repo_path: Path, worktree_path: Path, branch: str, base: str) -> None:
        worktree_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock(repo_path):
            self._run(repo_path, "worktree", "add", "-q", "-b", branch, str(worktree_path), base)

    def remove_worktree(self, repo_path: Path, worktree_path: Path, branch: str | None = None) -> None:
        with self._lock(repo_path):
            if worktree_path.exists():
                self._run(repo_path, "worktree", "remove", "--force", str(worktree_path), check=False)
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            self._run(repo_path, "worktree", "prune", check=False)
            if branch:
                self._run(repo_path, "branch", "-D", branch, check=False)

    def commit_all(
        self,
        worktree_path: Path,
        message: str,
        author: str,
        trailers: dict[str, str] | None = None,
        allow_empty: bool = False,
    ) -> str | None:
        self._run(worktree_path, "add", "-A")
        staged = self._run(worktree_path, "diff", "--cached", "--quiet", check=False).returncode != 0
        if not staged and not allow_empty:
            return None
        args = ["commit", "-q", "--no-verify", "-F", "-"]
        if allow_empty:
            args.append("--allow-empty")
        self._run(
            worktree_path, *args,
            input=format_trailers(message, trailers).encode(),
            env={**self._identity_env(author), "GIT_COMMITTER_NAME": _split_author(author)[0]},
        )
        return self._out(worktree_path, "rev-parse", "HEAD").strip()

    def reset_hard(self, worktree_path: Path, commit: str) -> None:
        self._run(worktree_path, "reset", "-q", "--hard", commit)
        self._run(worktree_path, "clean", "-q", "-fd")

    def has_uncommitted_changes(self, worktree_path: Path) -> bool:
        return bool(self._out(worktree_path, "status", "--porcelain").strip())

    def dirty_paths(self, worktree_path: Path) -> list[str]:
        """Paths with uncommitted changes (including untracked files)."""
        out = self._out(worktree_path, "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames")
        return sorted({entry[3:] for entry in out.split("\0") if len(entry) > 3})

    def head(self, worktree_path: Path) -> str:
        return self._out(worktree_path, "rev-parse", "HEAD").strip()

    # --------------------------------------------------------------- inspection
    def _parse_diff(self, cwd: Path, base: str, head_args: list[str], context: int, env=None) -> DiffResult:
        common = ["--no-renames", "--no-color", "--no-ext-diff"]
        numstat = self._out(cwd, "diff", *common, "--numstat", *head_args, env=env)
        name_status = self._out(cwd, "diff", *common, "--name-status", *head_args, env=env)
        patch = self._out(cwd, "diff", *common, f"-U{context}", *head_args, env=env)
        statuses: dict[str, str] = {}
        for line in name_status.splitlines():
            if "\t" in line:
                st, path = line.split("\t", 1)
                statuses[path] = st[0]
        files: list[FileChange] = []
        for line in numstat.splitlines():
            parts = line.split("\t", 2)
            if len(parts) != 3:
                continue
            add, dele, path = parts
            binary = add == "-"
            files.append(
                FileChange(
                    path=path,
                    status=statuses.get(path, "M"),
                    additions=0 if binary else int(add),
                    deletions=0 if binary else int(dele),
                    binary=binary,
                )
            )
        head = head_args[-1] if len(head_args) > 1 else "WORKTREE"
        return DiffResult(base=base, head=head, files=files, patch=patch)

    def diff(self, repo_path: Path, base: str, head: str, context: int = 3) -> DiffResult:
        return self._parse_diff(repo_path, base, [base, head], context)

    def diff_worktree(self, worktree_path: Path, base: str, context: int = 3) -> DiffResult:
        """Diff base against the worktree including untracked files, without touching the real index."""
        index = Path(self._out(worktree_path, "rev-parse", "--path-format=absolute", "--git-path", "index").strip())
        with tempfile.TemporaryDirectory() as tmp:
            tmp_index = Path(tmp) / "index"
            if index.exists():
                shutil.copyfile(index, tmp_index)
            env = {"GIT_INDEX_FILE": str(tmp_index)}
            self._run(worktree_path, "add", "-A", env=env)
            return self._parse_diff(worktree_path, base, ["--cached", base], context, env=env)

    def read_file(self, repo_path: Path, commit: str, path: str) -> bytes | None:
        proc = self._run(repo_path, "cat-file", "blob", f"{commit}:{path}", check=False)
        return proc.stdout if proc.returncode == 0 else None

    def list_files(self, repo_path: Path, commit: str) -> list[str]:
        out = self._out(repo_path, "ls-tree", "-r", "--name-only", "-z", commit)
        return [p for p in out.split("\0") if p]

    def tree_id(self, repo_path: Path, commit: str) -> str:
        return self._out(repo_path, "rev-parse", f"{commit}^{{tree}}").strip()

    _LOG_FORMAT = _FIELD_SEP.join(["%H", "%P", "%an <%ae>", "%ct", "%B", "%(trailers:only=true,unfold=true)"]) + _RECORD_SEP

    def _parse_log(self, out: str) -> list[CommitInfo]:
        commits = []
        for record in out.split(_RECORD_SEP):
            record = record.strip("\n")
            if not record:
                continue
            sha, parents, author, ts, body, trailer_block = record.split(_FIELD_SEP)
            trailers = {}
            for line in trailer_block.splitlines():
                if ":" in line:
                    k, v = line.split(":", 1)
                    trailers[k.strip()] = v.strip()
            commits.append(
                CommitInfo(
                    sha=sha.strip(),
                    parents=parents.split(),
                    author=author,
                    message=body.strip(),
                    timestamp=int(ts),
                    trailers=trailers,
                )
            )
        return commits

    def commit_info(self, repo_path: Path, commit: str) -> CommitInfo:
        return self._parse_log(self._out(repo_path, "log", "-1", f"--format={self._LOG_FORMAT}", commit))[0]

    def log(self, repo_path: Path, rev: str, limit: int = 50) -> list[CommitInfo]:
        return self._parse_log(self._out(repo_path, "log", f"-{limit}", f"--format={self._LOG_FORMAT}", rev))

    def blame(self, repo_path: Path, commit: str, path: str) -> list[BlameLine]:
        out = self._out(repo_path, "blame", "--porcelain", commit, "--", path)
        lines: list[BlameLine] = []
        current_sha = ""
        current_line = 0
        for raw in out.split("\n"):
            if raw.startswith("\t"):
                lines.append(BlameLine(line_no=current_line, commit=current_sha, content=raw[1:]))
                continue
            parts = raw.split(" ")
            if len(parts) >= 3 and _SHA_RE.match(parts[0]):
                current_sha = parts[0]
                current_line = int(parts[2])
        return lines

    # ------------------------------------------------------------------ merging
    def check_merge(self, repo_path: Path, ours: str, theirs: str) -> MergeCheck:
        proc = self._run(
            repo_path, "merge-tree", "--write-tree", "--name-only", ours, theirs, check=False, ok_codes=(0, 1)
        )
        if proc.returncode not in (0, 1):
            raise VersionEngineError(proc.stderr.decode("utf-8", "replace"))
        out = proc.stdout.decode("utf-8", "replace")
        tree, _, rest = out.partition("\n")
        if proc.returncode == 0:
            return MergeCheck(clean=True, tree=tree.strip())
        files_block, _, messages = rest.partition("\n\n")
        files = sorted({f for f in files_block.splitlines() if f.strip()})
        return MergeCheck(
            clean=False,
            tree=None,
            conflicting_files=files,
            messages=[m for m in messages.splitlines() if m.strip()],
        )

    def merge(
        self,
        repo_path: Path,
        target_branch: str,
        source: str,
        message: str,
        author: str,
        trailers: dict[str, str] | None = None,
        expected_head: str | None = None,
    ) -> str:
        with self._lock(repo_path):
            current = self.branch_head(repo_path, target_branch)
            if current is None:
                raise VersionEngineError(f"branch {target_branch} does not exist")
            if expected_head and current != expected_head:
                raise RefUpdateConflict(f"{target_branch} moved from {expected_head[:10]} to {current[:10]}")
            if self.is_ancestor(repo_path, source, current):
                return current
            check = self.check_merge(repo_path, current, source)
            if not check.clean or not check.tree:
                raise VersionEngineError(f"merge has conflicts: {', '.join(check.conflicting_files)}")
            commit = self._out(
                repo_path, "commit-tree", check.tree, "-p", current, "-p", source, "-F", "-",
                input=format_trailers(message, trailers).encode(),
                env=self._identity_env(author),
            ).strip()
            self._cas_update(repo_path, target_branch, commit, current)
            return commit

    def revert(
        self,
        repo_path: Path,
        target_branch: str,
        commit: str,
        message: str,
        author: str,
        trailers: dict[str, str] | None = None,
    ) -> str:
        with self._lock(repo_path):
            current = self.branch_head(repo_path, target_branch)
            if current is None:
                raise VersionEngineError(f"branch {target_branch} does not exist")
            parent = self.resolve(repo_path, f"{commit}^1")
            # A revert of C is a three-way merge of C^1 into HEAD using C as the base.
            proc = self._run(
                repo_path, "merge-tree", "--write-tree", "--name-only", f"--merge-base={commit}", current, parent,
                check=False, ok_codes=(0, 1),
            )
            if proc.returncode != 0:
                files = proc.stdout.decode().split("\n\n")[0].splitlines()[1:]
                raise VersionEngineError(f"revert conflicts: {', '.join(files)}")
            tree = proc.stdout.decode().splitlines()[0].strip()
            new = self._out(
                repo_path, "commit-tree", tree, "-p", current, "-F", "-",
                input=format_trailers(message, trailers).encode(),
                env=self._identity_env(author),
            ).strip()
            self._cas_update(repo_path, target_branch, new, current)
            return new

    def _cas_update(self, repo_path: Path, branch: str, new: str, old: str) -> None:
        proc = self._run(repo_path, "update-ref", f"refs/heads/{branch}", new, old, check=False)
        if proc.returncode != 0:
            raise RefUpdateConflict(proc.stderr.decode("utf-8", "replace").strip())

    def materialize(self, repo_path: Path, commit: str, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        data = self._run(repo_path, "archive", "--format=tar", commit).stdout
        with tarfile.open(fileobj=io.BytesIO(data)) as tar:
            tar.extractall(dest, filter="data")

    def create_detached_worktree(self, repo_path: Path, worktree_path: Path, commit: str) -> None:
        with self._lock(repo_path):
            self._run(repo_path, "worktree", "add", "-q", "--detach", str(worktree_path), commit)

    def commit_tree(self, repo_path: Path, tree: str, parents: list[str], message: str, author: str) -> str:
        args = ["commit-tree", tree]
        for p in parents:
            args += ["-p", p]
        return self._out(repo_path, *args, "-m", message, env=self._identity_env(author)).strip()
