"""Schema bootstrap.

Development and tests use ``create_all`` because it is instant and the schema
is disposable. Production runs Alembic, because a database with real history
deserves versioned, reversible migrations.

Which path runs is decided by configuration, never guessed.
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import create_all

logger = get_logger(__name__)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def run_migrations(settings: Settings) -> None:
    """Bring the database up to date, using the right tool for the environment."""
    if not settings.auto_migrate:
        logger.info("auto-migrate disabled; assuming the schema is already current")
        return

    if settings.environment != "production":
        create_all()
        logger.info("schema ensured via create_all (%s)", settings.environment)
        return

    try:
        from alembic.config import Config

        from alembic import command
    except ImportError:  # pragma: no cover - alembic is a hard dependency in prod
        logger.error("alembic is not installed; falling back to create_all")
        create_all()
        return

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
    logger.info("alembic migrations applied to head")
