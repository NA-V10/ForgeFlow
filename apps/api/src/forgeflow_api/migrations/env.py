"""Alembic environment. The URL comes from the caller (forgeflow_api.main.migrate) or FORGEFLOW_DATABASE_URL."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from forgeflow_api.config import get_settings
from forgeflow_api.models import Base

config = context.config
url = config.get_main_option("sqlalchemy.url") or get_settings().resolved_database_url
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config({"sqlalchemy.url": url}, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=connection.dialect.name == "sqlite")
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
