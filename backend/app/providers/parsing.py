"""Tolerant parsing helpers for provider payloads.

Upstream APIs omit fields, change types, and occasionally return ``"null"`` as
a string. These helpers never raise on a single bad field; the provider decides
whether the *record* is salvageable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.core.clock import IST, ensure_aware


def dig(payload: Any, *path: str, default: Any = None) -> Any:
    """Safely walk nested dicts: ``dig(p, "data", "train", "number")``."""
    cur = payload
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return default if cur is None else cur


def as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or isinstance(value, bool):
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_str(value: Any, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return default


def parse_datetime(value: Any) -> datetime | None:
    """Parse ISO-8601, tolerating a trailing ``Z`` (Python 3.10 does not)."""
    if isinstance(value, datetime):
        return ensure_aware(value)
    text = as_str(value)
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return ensure_aware(datetime.fromisoformat(text))
    except ValueError:
        return None


def parse_clock_time(value: Any, on_day: date, *, tz: object = IST) -> datetime | None:
    """Parse an ``HH:MM`` wall-clock string into an aware datetime on ``on_day``."""
    text = as_str(value)
    if not text or ":" not in text:
        return None
    parts = text.split(":")
    try:
        hour, minute = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (0 <= hour <= 47 and 0 <= minute <= 59):
        return None
    base = datetime(on_day.year, on_day.month, on_day.day, 0, 0, tzinfo=tz)  # type: ignore[arg-type]
    return base + timedelta(hours=hour, minutes=minute)
