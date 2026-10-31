from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FORGEFLOW_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path(".forgeflow"), description="Repositories, workspaces and local artifacts")
    database_url: str | None = Field(default=None, description="postgresql+psycopg://… in production")
    redis_url: str | None = None

    # artifacts: local directory unless an S3/MinIO endpoint is configured
    s3_endpoint: str | None = None
    s3_bucket: str = "forgeflow-artifacts"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"

    sandbox: str = Field(default="local", description="local | docker")
    sandbox_image: str = "forgeflow/sandbox:latest"
    network_policy: str = "none"
    command_timeout: float = 600.0

    auth_mode: str = Field(default="dev", description="dev: anonymous requests act as a local human user; "
                                                       "token: every request needs a bearer token")
    admin_token: str = "dev-admin-token"
    local_user: str = "local-user"

    auto_migrate: bool = True
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        self.data_dir.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{(self.data_dir / 'forgeflow.db').resolve().as_posix()}"

    @property
    def repos_dir(self) -> Path:
        return (self.data_dir / "repos").resolve()

    @property
    def workspaces_dir(self) -> Path:
        return (self.data_dir / "workspaces").resolve()

    @property
    def artifacts_dir(self) -> Path:
        return (self.data_dir / "artifacts").resolve()

    @property
    def scratch_dir(self) -> Path:
        return (self.data_dir / "scratch").resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
