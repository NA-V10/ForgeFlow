from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Query
from sqlalchemy import select

from ..core import NotFound, get_or_404
from ..deps import ForgeDep, PrincipalDep, SessionDep
from ..models import Repository
from ..schemas import CommitOut, RepositoryCreate, RepositoryOut, RepositorySettingsUpdate
from ..services import insight, registry

router = APIRouter(prefix="/repositories", tags=["repositories"])


def _out(forge, repo: Repository) -> RepositoryOut:
    out = RepositoryOut.model_validate(repo)
    out.head = forge.engine.branch_head(registry.repo_path(repo), repo.default_branch)
    return out


@router.post("", response_model=RepositoryOut, status_code=201, summary="Register a repository")
def create_repository(body: RepositoryCreate, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    repo = registry.create_repository(forge, s, p, **body.model_dump())
    s.commit()
    return _out(forge, repo)


@router.get("", response_model=list[RepositoryOut])
def list_repositories(forge: ForgeDep, s: SessionDep, _: PrincipalDep):
    return [_out(forge, r) for r in s.execute(select(Repository).order_by(Repository.created_at)).scalars()]


@router.get("/{ref}", response_model=RepositoryOut)
def get_repository(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep):
    return _out(forge, get_or_404(s, Repository, ref, "repository"))


@router.patch("/{ref}/settings", response_model=RepositoryOut)
def update_settings(ref: str, body: RepositorySettingsUpdate, forge: ForgeDep, s: SessionDep, p: PrincipalDep):
    repo = registry.update_repository_settings(s, p, get_or_404(s, Repository, ref, "repository"), body.settings)
    s.commit()
    return _out(forge, repo)


@router.get("/{ref}/branches", response_model=dict[str, str])
def branches(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep):
    return forge.engine.list_branches(registry.repo_path(get_or_404(s, Repository, ref, "repository")))


@router.get("/{ref}/commits", response_model=list[CommitOut])
def commits(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep, rev: str | None = None,
            limit: int = Query(50, le=500)):
    repo = get_or_404(s, Repository, ref, "repository")
    return [asdict(c) for c in forge.engine.log(registry.repo_path(repo), rev or repo.default_branch, limit)]


@router.get("/{ref}/files", response_model=list[str])
def files(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep, rev: str | None = None):
    repo = get_or_404(s, Repository, ref, "repository")
    commit = forge.engine.resolve(registry.repo_path(repo), rev or repo.default_branch)
    if not commit:
        raise NotFound(f"revision {rev} not found")
    return forge.engine.list_files(registry.repo_path(repo), commit)


@router.get("/{ref}/file")
def file_content(ref: str, path: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep, rev: str | None = None):
    repo = get_or_404(s, Repository, ref, "repository")
    data = forge.engine.read_file(registry.repo_path(repo), rev or repo.default_branch, path)
    if data is None:
        raise NotFound(f"{path} not found")
    return {"path": path, "content": data.decode("utf-8", "replace"), "size": len(data)}


@router.get("/{ref}/provenance", summary="Why does this line exist?")
def provenance(ref: str, path: str, line: int, forge: ForgeDep, s: SessionDep, _: PrincipalDep,
               rev: str | None = None):
    """Trace a line: line → file → commit → change → execution → agent → task → model."""
    return insight.trace(forge, s, get_or_404(s, Repository, ref, "repository"), path, line, rev)


@router.get("/{ref}/blame", summary="Per-line provenance for a file")
def blame(ref: str, path: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep, rev: str | None = None):
    return insight.file_provenance(forge, s, get_or_404(s, Repository, ref, "repository"), path, rev)


@router.get("/{ref}/graph", summary="Repository → branches → tasks → agents → workspaces → changes → merges")
def graph(ref: str, forge: ForgeDep, s: SessionDep, _: PrincipalDep):
    return insight.repository_graph(forge, s, get_or_404(s, Repository, ref, "repository"))
