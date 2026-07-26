"""Structured logging with request-scoped trace ids."""

from __future__ import annotations

import contextvars
import logging
import sys
import uuid
from typing import Any

from pythonjsonlogger import jsonlogger

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def new_trace_id() -> str:
    return uuid.uuid4().hex[:16]


class TraceFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = trace_id_var.get()
        return True


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(TraceFilter())
    if fmt == "json":
        handler.setFormatter(
            jsonlogger.JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(trace_id)s %(message)s",
                rename_fields={"asctime": "ts", "levelname": "level"},
            )
        )
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s [%(trace_id)s] %(name)s: %(message)s")
        )
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("apscheduler.executors.default", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Emit a structured event. Keeps log call sites uniform and greppable."""
    logger.info(event, extra={"event": event, **fields})
