"""The status payload — the only response most users ever see.

Every instant is an absolute ISO-8601 timestamp with an offset. Countdowns are
computed on the client, because a cached "closes in 240 seconds" is a lie the
moment it is stored.
"""

from __future__ import annotations

from pydantic import Field

from app.schemas.common import ApiModel, ISTDateTime
from app.schemas.crossing import CrossingSummary


class TrainCauseOut(ApiModel):
    train_number: str
    train_name: str
    train_class: str
    direction: str
    pass_at: ISTDateTime
    speed_kmph: float
    delay_minutes: int
    provider: str
    estimator: str


class ClosureWindowOut(ApiModel):
    close_at: ISTDateTime
    open_at: ISTDateTime
    duration_seconds: float
    confidence: float
    causes: list[TrainCauseOut] = Field(default_factory=list)


class ConfidenceOut(ApiModel):
    score: float = Field(ge=0.0, le=1.0)
    label: str = Field(examples=["high"])
    factors: dict[str, float] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class ApproachingTrainOut(ApiModel):
    train_number: str
    train_name: str
    train_class: str
    direction: str
    pass_at: ISTDateTime
    speed_kmph: float
    delay_minutes: int


class TodaySummaryOut(ApiModel):
    date: str
    closure_count: int
    total_closed_seconds: float
    longest_closure_seconds: float
    closures: list[ClosureWindowOut] = Field(default_factory=list)


class DataQualityOut(ApiModel):
    providers_used: list[str] = Field(default_factory=list)
    degraded: bool = False
    stale: bool = False
    freight_risk: float = 0.0
    last_updated_at: ISTDateTime | None = None
    notes: list[str] = Field(default_factory=list)


class LeaveAdviceOut(ApiModel):
    """Direct answer to "should I leave now?"."""

    travel_seconds: int
    arrival_at: ISTDateTime
    can_cross: bool
    verdict: str
    reason: str


class CrossingStatusOut(ApiModel):
    crossing: CrossingSummary
    generated_at: ISTDateTime
    server_time: ISTDateTime
    state: str = Field(examples=["open", "closed", "closing_soon"])
    seconds_until_close: float | None = None
    seconds_until_open: float | None = None
    current_closure: ClosureWindowOut | None = None
    next_closure: ClosureWindowOut | None = None
    upcoming: list[ClosureWindowOut] = Field(default_factory=list)
    approaching_train: ApproachingTrainOut | None = None
    confidence: ConfidenceOut
    today: TodaySummaryOut
    data: DataQualityOut
    advice: LeaveAdviceOut | None = None


class RefreshResultOut(ApiModel):
    """Result of a user-triggered refresh, plus the resulting status so the
    client updates in a single round trip."""

    refreshed: bool
    outcome: str = Field(examples=["refreshed", "already_fresh", "budget_protected"])
    reason: str
    data_age_seconds: float | None = None
    next_refresh_at: ISTDateTime | None = None
    status: CrossingStatusOut


class GateReportIn(ApiModel):
    state: str = Field(pattern="^(open|closed)$")
    note: str | None = Field(default=None, max_length=280)
    #: Random id generated and stored by the browser. Hashed server-side and
    #: never stored raw; identifies a browser for deduplication, not a person.
    client_id: str | None = Field(default=None, max_length=64)


class GateReportOut(ApiModel):
    accepted: bool
    outcome: str = Field(
        examples=["corroborated", "unexplained", "duplicate", "rate_limited"]
    )
    message: str
    reported_at: ISTDateTime
    #: When this client may report again. Drives the button cooldown.
    next_report_at: ISTDateTime | None = None
    #: Distinct clients reporting the same state in the corroboration window.
    corroborations: int = 0
    id: int | None = None


class AccuracyOut(ApiModel):
    crossing_slug: str
    summary: dict
    calibration: list[dict] = Field(default_factory=list)
