"""FastAPI dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.container import Container
from app.core.errors import UnauthorizedError
from app.db.session import session_scope


def get_container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:  # pragma: no cover - only during a failed startup
        raise RuntimeError("application container is not initialised")
    return container


def get_db() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def get_now(container: Container = Depends(get_container)) -> datetime:
    """Inject the current instant so every handler shares one consistent view."""
    return container.clock.now()


def require_admin(
    container: Container = Depends(get_container),
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """Admin endpoints are locked unless ADMIN_API_KEY is set *and* matched.

    Fails closed in production, open in development — an unset key in prod
    would otherwise silently expose write endpoints.
    """
    expected = container.settings.admin_api_key
    if not expected:
        if container.settings.environment == "production":
            raise UnauthorizedError("Admin API is disabled: ADMIN_API_KEY is not configured")
        return
    if x_admin_key != expected:
        raise UnauthorizedError("Invalid or missing X-Admin-Key header")
