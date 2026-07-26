"""Alembic environment.

The database URL comes from :class:`Settings`, so migrations and the app can
never disagree about which database they are talking to.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import build_engine

# Importing the models module registers every table on Base.metadata.
from app.db import models  # noqa: F401

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
settings = get_settings()


def render_item(type_: str, obj: object, autogen_context: object) -> object:
    """Render :class:`UtcDateTime` as a plain timezone-aware ``DateTime``.

    The decorator only adds bind/result processing, which migrations do not
    need — and emitting it would force every migration to import application
    code, coupling schema history to the codebase that generated it.
    """
    from app.db.base import UtcDateTime

    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rewrites tables.
        render_as_batch=settings.is_sqlite,
        compare_type=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = build_engine(settings)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=settings.is_sqlite,
            compare_type=True,
            render_item=render_item,
            poolclass=pool.NullPool,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
