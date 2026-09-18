"""A cache of price histories, so questions can be answered in a second.

Answering "who is about to appreciate?" means looking at a lot of players at
once, and the price endpoint is per player. At the polite request interval that
is minutes of waiting for a question asked in a chat window, which is the
difference between a tool somebody uses and one they do not.

So the histories are fetched once by the scheduled ingest and kept here. The
endpoint returns the whole season every time, so this cache is a convenience
and never a source of truth: deleting it costs nothing but time, and a gap in
it cannot corrupt anything downstream.

Stored as one file with sorted keys, like the rest of the state, so a commit
diff shows which players actually moved.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path

from fantasy.domain.models import ValuePoint, ValueSeries
from fantasy.settings import STATE_DIR
from fantasy.sources.laliga.client import ApiError, FantasyClient
from fantasy.sources.laliga.market_value import fetch_series


class ValueCache:
    """Price histories by player id."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (STATE_DIR / "values.json")
        self._series: dict[str, ValueSeries] = {}
        self.fetched_on: date | None = None

    # -- persistence ---------------------------------------------------------
    def load(self) -> ValueCache:
        if not self.path.exists():
            return self
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self

        stamp = raw.get("fetched_on")
        if isinstance(stamp, str):
            try:
                self.fetched_on = date.fromisoformat(stamp)
            except ValueError:
                self.fetched_on = None

        for player_id, points in (raw.get("series") or {}).items():
            self._series[str(player_id)] = ValueSeries(
                player_id=str(player_id),
                points=tuple(
                    ValuePoint(
                        date=date.fromisoformat(p["date"]),
                        value=int(p["value"]),
                        bids=int(p.get("bids", 0)),
                    )
                    for p in points
                ),
            )
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "fetched_on": (self.fetched_on or date.today()).isoformat(),
            "series": {
                player_id: [
                    {"date": p.date.isoformat(), "value": p.value, "bids": p.bids}
                    for p in series.points
                ]
                for player_id, series in sorted(self._series.items())
            },
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    # -- access --------------------------------------------------------------
    def get(self, player_id: str) -> ValueSeries | None:
        return self._series.get(str(player_id))

    def __len__(self) -> int:
        return len(self._series)

    def is_stale(self, *, today: date | None = None) -> bool:
        """Values are recomputed nightly, so a cache from yesterday is stale."""
        return self.fetched_on != (today or date.today())

    def refresh(
        self,
        client: FantasyClient,
        player_ids: Iterable[str],
        *,
        today: date | None = None,
    ) -> int:
        """Fetch histories for `player_ids`. Returns how many were updated.

        A player whose fetch fails keeps whatever history is already cached
        rather than being dropped: stale prices beat no prices, and the
        valuation carries the observation count so downstream can tell.
        """
        updated = 0
        for player_id in player_ids:
            try:
                series = fetch_series(client, str(player_id))
            except (ApiError, OSError):
                continue
            if series.points:
                self._series[str(player_id)] = series
                updated += 1
        self.fetched_on = today or datetime.now().date()
        return updated


__all__ = ["ValueCache"]
