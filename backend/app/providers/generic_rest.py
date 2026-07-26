"""Generic REST provider.

A configurable adapter for indianrailapi.com-shaped services, and the worked
example for "how do I add a source?" (ADR 0001). Field locations are declared
as dotted paths so a new vendor is a *config* change, not a code change.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.core.cache import Cache
from app.core.errors import ProviderError
from app.core.logging import get_logger
from app.domain import (
    Direction,
    ProviderHealth,
    RunStatus,
    TrainSighting,
    classify_train,
)
from app.providers.base import BaseProvider, FetchContext
from app.providers.http import RestClient
from app.providers.parsing import as_int, as_str, parse_datetime

logger = get_logger(__name__)

DEFAULT_FIELD_MAP: dict[str, str] = {
    "records": "data.trains",
    "train_number": "train.number",
    "train_name": "train.name",
    "train_type": "train.type",
    "pass_time": "live.expectedDepartureTime",
    "delay_minutes": "live.delayMinutes",
    "direction": "live.direction",
}


class GenericRestProvider(BaseProvider):
    name = "generic_rest"
    trust = 0.6

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        path_template: str = "/stations/{station}/live",
        field_map: dict[str, str] | None = None,
        timeout: float = 8.0,
        cache: Cache | None = None,
        cache_ttl: int = 60,
        client: Any | None = None,
        trust: float | None = None,
    ) -> None:
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._path_template = path_template
        self._fields = {**DEFAULT_FIELD_MAP, **(field_map or {})}
        if trust is not None:
            self.trust = trust
        self._client = RestClient(
            provider=self.name,
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            cache=cache,
            cache_ttl=cache_ttl,
            client=client,
        )

    async def fetch_sightings(self, ctx: FetchContext) -> list[TrainSighting]:
        path = self._path_template.format(station=ctx.crossing.prev_station_code)
        payload = await self._client.get_json(path)
        records = _dotted(payload, self._fields["records"])
        if records is None:
            return []
        if not isinstance(records, list):
            raise ProviderError(self.name, "records path did not yield a list", retryable=False)

        horizon_end = ctx.now + timedelta(minutes=ctx.horizon_minutes)
        out: list[TrainSighting] = []
        for record in records:
            sighting = self._parse(record, ctx)
            if sighting is None or sighting.direct_pass_estimate is None:
                continue
            if ctx.now - timedelta(minutes=10) <= sighting.direct_pass_estimate <= horizon_end:
                out.append(sighting)
        return out

    def _parse(self, record: Any, ctx: FetchContext) -> TrainSighting | None:
        number = as_str(_dotted(record, self._fields["train_number"]))
        if not number:
            return None
        pass_at = parse_datetime(_dotted(record, self._fields["pass_time"]))
        if pass_at is None:
            return None
        name = as_str(_dotted(record, self._fields["train_name"]), number) or number
        train_type = as_str(_dotted(record, self._fields["train_type"]))
        raw_dir = (as_str(_dotted(record, self._fields["direction"]), "") or "").lower()
        direction = (
            Direction(raw_dir)
            if raw_dir in Direction._value2member_map_
            else Direction.UNKNOWN
        )
        return TrainSighting(
            train_number=number,
            train_name=name,
            provider=self.name,
            provider_trust=self.trust,
            observed_at=ctx.now,
            train_class=classify_train(train_type, name),
            train_type=train_type,
            status=RunStatus.RUNNING,
            delay_minutes=as_int(_dotted(record, self._fields["delay_minutes"]), 0),
            direct_pass_estimate=pass_at,
            direct_direction=direction,
            raw={"source": "generic_rest"},
        )

    async def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, healthy=True, detail="configured")

    async def close(self) -> None:
        await self._client.close()


def _dotted(payload: Any, path: str) -> Any:
    cur = payload
    for key in path.split("."):
        if isinstance(cur, dict) and key in cur:
            cur = cur[key]
        else:
            return None
    return cur
