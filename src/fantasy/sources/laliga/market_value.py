"""Price history: the API's answer mapped onto `ValueSeries`.

Kept apart from the rest of the adapter for one reason worth stating. This is
the only endpoint in the project that needs no bearer at all, and it returns the
whole season in a single response. Together those two facts mean history is
never something the agent has to accumulate by polling and can never lose by
missing a night — it is simply asked for again.

An earlier design in this project assumed the opposite, and warned in its README
that every uncaptured day was "lost for ever". It was not.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from fantasy.domain.models import ValuePoint, ValueSeries
from fantasy.sources.laliga.client import FantasyClient


def parse_series(player_id: str, payload: Any) -> ValueSeries:
    """Map the raw response onto a series, oldest first.

    Deliberately forgiving: a row without a readable date or value is dropped
    rather than raised on. A single malformed day must not deny the agent the
    other eighty, and the alternative — failing the whole run — is how a price
    signal silently disappears at the worst moment.
    """
    rows = payload if isinstance(payload, list) else []
    points: list[ValuePoint] = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        day = _as_date(row.get("date"))
        value = _as_int(row.get("marketValue"))
        if day is None or value is None:
            continue
        points.append(ValuePoint(date=day, value=value, bids=_as_int(row.get("bids")) or 0))

    points.sort(key=lambda p: p.date)
    return ValueSeries(player_id=str(player_id), points=tuple(points))


def fetch_series(client: FantasyClient, player_id: str) -> ValueSeries:
    return parse_series(player_id, client.market_value(player_id))


def _as_date(raw: Any) -> date | None:
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


def _as_int(raw: Any) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


__all__ = ["fetch_series", "parse_series"]
