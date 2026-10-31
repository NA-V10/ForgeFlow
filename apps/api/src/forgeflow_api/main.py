"""ForgeFlow API application factory."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ff_policy import DEFAULT_POLICY_YAML
from ff_version import GitEngine, VersionEngineError
from sqlalchemy import select

from . import __version__
from .auth import Forbidden
from .config import Settings, get_settings
from .core import Forge, ForgeError
from .db import make_engine, make_session_factory
from .events import EventBus, InMemoryBus, RedisBus
from .models import ImmutableEventError, Policy
from .routers import agents, executions, governance, merges, observability, repositories, tasks, workspaces
from .storage import ArtifactStore, LocalArtifactStore, S3ArtifactStore

log = logging.getLogger("forgeflow")

TAGS = [
    {"name": "repositories", "description": "Git-backed repositories, history, files and line provenance"},
    {"name": "agents", "description": "Agent identities and credentials"},
    {"name": "tasks", "description": "Units of work assigned to agents"},
    {"name": "workspaces", "description": "Isolated git worktrees, diffs and checkpoints"},
    {"name": "executions", "description": "Agent runs and mediated tool calls"},
    {"name": "reviews", "description": "Review submission, semantic diff and risk"},
    {"name": "approvals", "description": "Human approval gates"},
    {"name": "policies", "description": "YAML policy documents and evaluation"},
    {"name": "merges", "description": "Merge queue and the 7-step merge gate"},
    {"name": "observability", "description": "Events, real-time stream, dashboard and settings"},
]


def migrate(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    here = Path(__file__).parent
    cfg = Config()
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


def build_forge(settings: Settings) -> Forge:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    for d in (settings.repos_dir, settings.workspaces_dir, settings.scratch_dir):
        d.mkdir(parents=True, exist_ok=True)
    url = settings.resolved_database_url
    if settings.auto_migrate:
        migrate(url)
    engine = make_engine(url)
    store: ArtifactStore
    if settings.s3_endpoint:
        store = S3ArtifactStore(settings.s3_endpoint, settings.s3_bucket, settings.s3_access_key,
                                settings.s3_secret_key, settings.s3_region)
    else:
        store = LocalArtifactStore(settings.artifacts_dir)
    bus: EventBus = RedisBus(settings.redis_url) if settings.redis_url else InMemoryBus()
    forge = Forge(settings=settings, engine=GitEngine(), store=store, bus=bus,
                  session_factory=make_session_factory(engine))
    with forge.session() as s:
        if s.execute(select(Policy).where(Policy.scope == "global")).first() is None:
            s.add(Policy(scope="global", version=1, document=DEFAULT_POLICY_YAML, created_by="system"))
            s.commit()
    return forge


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.forge.bus.close()

    app = FastAPI(
        title="ForgeFlow API",
        version=__version__,
        description="Agent-native version control and software delivery control plane. "
                    "Authenticate with `Authorization: Bearer <token>` (agent tokens or the admin token).",
        openapi_tags=TAGS,
        lifespan=lifespan,
    )
    app.state.forge = build_forge(settings)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                       allow_methods=["*"], allow_headers=["*"])

    @app.exception_handler(ForgeError)
    async def forge_error(_: Request, exc: ForgeError):
        return JSONResponse(status_code=exc.status_code,
                            content={"error": exc.code, "message": exc.message, "details": exc.details})

    @app.exception_handler(Forbidden)
    async def forbidden(_: Request, exc: Forbidden):
        return JSONResponse(status_code=403, content={"error": "forbidden", "message": str(exc), "details": {}})

    @app.exception_handler(VersionEngineError)
    async def vcs_error(_: Request, exc: VersionEngineError):
        return JSONResponse(status_code=409, content={"error": "version_engine", "message": str(exc), "details": {}})

    @app.exception_handler(ImmutableEventError)
    async def immutable(_: Request, exc: ImmutableEventError):
        return JSONResponse(status_code=409, content={"error": "immutable", "message": str(exc), "details": {}})

    @app.get("/health", tags=["observability"])
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    prefix = "/api/v1"
    for r in (repositories, agents, tasks, workspaces, executions, governance, merges, observability):
        app.include_router(r.router, prefix=prefix)
    return app
