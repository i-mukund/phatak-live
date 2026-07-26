"""Shared response primitives."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

from app.core.clock import to_ist

#: Serialise every timestamp as IST with an explicit offset. The API is read by
#: people standing at a level crossing in India; UTC would be a small cruelty.
#: Values remain real ``datetime`` objects in Python, so arithmetic is unaffected.
ISTDateTime = Annotated[
    datetime,
    PlainSerializer(
        lambda v: to_ist(v).isoformat(timespec="seconds"),
        return_type=str,
        when_used="json",
    ),
]


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class ErrorResponse(ApiModel):
    code: str = Field(examples=["not_found"])
    message: str
    detail: object | None = None
    trace_id: str | None = None


class HealthResponse(ApiModel):
    status: str
    version: str
    environment: str
    time: ISTDateTime


class ReadinessResponse(ApiModel):
    status: str
    database: bool
    providers: list[dict]
    scheduler_last_tick: ISTDateTime | None = None
    degraded: bool = False
