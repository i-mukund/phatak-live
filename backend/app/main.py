"""ASGI application.

Startup order matters: logging → database → container → scheduler. Shutdown is
the reverse, and the scheduler is stopped before providers are closed so a job
cannot fire against a closed HTTP client.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import health
from app.api.v1.router import api_router
from app.container import build_container
from app.core.config import get_settings
from app.core.errors import PhatakError
from app.core.logging import configure_logging, get_logger, new_trace_id, trace_id_var
from app.db.migrate import run_migrations
from app.db.seed import seed_if_empty
from app.db.session import session_scope
from app.scheduler.runner import build_scheduler

logger = get_logger(__name__)

DESCRIPTION = """
Predicts when an Indian railway level crossing (*phatak*) will close and reopen.

This is **not** a train tracker and **not** a timetable. It answers one question:

> *Should I leave home now, or will the gate close before I reach it?*

Poll `GET /api/v1/crossings/{slug}/status`. Every instant in the response is an
absolute ISO-8601 timestamp — compute countdowns on the client.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    logger.info("starting %s (%s)", settings.app_name, settings.environment)

    run_migrations(settings)
    with session_scope() as session:
        seed_if_empty(session)

    container = build_container(settings)
    app.state.container = container

    scheduler = None
    if settings.scheduler_enabled:
        scheduler = build_scheduler(container)
        scheduler.start()
        # Run the first ingest immediately so a cold start is not blank.
        scheduler.get_job("ingest").modify(next_run_time=container.clock.now())
    app.state.scheduler = scheduler

    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await container.aclose()
        logger.info("shutdown complete")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=health.VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-Cache"],
    )

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("X-Request-ID") or new_trace_id()
        token = trace_id_var.set(trace_id)
        try:
            response = await call_next(request)
        finally:
            trace_id_var.reset(token)
        response.headers["X-Request-ID"] = trace_id
        return response

    @app.exception_handler(PhatakError)
    async def phatak_error_handler(_: Request, exc: PhatakError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "detail": exc.detail,
                "trace_id": trace_id_var.get(),
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "code": "validation_error",
                "message": "Request validation failed",
                "detail": exc.errors(),
                "trace_id": trace_id_var.get(),
            },
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "internal_error",
                "message": "Something went wrong on our side.",
                "trace_id": trace_id_var.get(),
            },
        )

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict:
        return {
            "name": settings.app_name,
            "question": "Should I leave home now, or will the gate close before I reach it?",
            "docs": "/docs",
            "status_example": f"{settings.api_prefix}/crossings/siraspur/status",
        }

    return app


app = create_app()
