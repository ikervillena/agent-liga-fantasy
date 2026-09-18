"""Reading a price series: who is appreciating, who is bleeding.

This is the lever the agent was missing entirely. Points win matchdays, but
appreciation wins seasons: a player bought before a run of rises funds the next
signing without scoring a single point, and one bought after it has already
peaked quietly taxes the squad every night.

Everything here is a pure function of a `ValueSeries`, so it is tested against
real captured history rather than reasoned about.
"""

from __future__ import annotations

from datetime import date, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from fantasy.domain.models import Euros, ValueSeries


class Trend(StrEnum):
    """A deliberately coarse verdict.

    Fine-grained slopes invite false precision on a series that is recomputed
    by somebody else's model overnight. Four buckets are enough to act on, and
    the threshold below is what separates a real move from valuation noise.
    """

    RISING = "rising"
    FLAT = "flat"
    FALLING = "falling"
    UNKNOWN = "unknown"


#: Daily drift under a tenth of a percent is noise, not a trend. Observed on
#: real series: a static player still wanders a few thousand euros a night.
FLAT_BAND = 0.001


class Valuation(BaseModel):
    """What a price series says about a player, in the terms decisions need."""

    model_config = ConfigDict(frozen=True)

    player_id: str
    value: Euros = 0
    #: Euros per day over the recent window. The headline number.
    velocity: float = 0.0
    #: Change in velocity: positive means the rise itself is speeding up.
    acceleration: float = 0.0
    trend: Trend = Trend.UNKNOWN
    delta_7d: Euros = 0
    delta_30d: Euros = 0
    #: Offers standing on the player in the latest observation. Demand leads price.
    bids: int = 0
    days_observed: int = 0

    @property
    def velocity_pct(self) -> float:
        """Daily move as a fraction of value, which is how it compares across prices.

        Two hundred thousand a day is spectacular on a five million player and
        irrelevant on a hundred million one.
        """
        return self.velocity / self.value if self.value else 0.0

    def projected(self, days: int) -> Euros:
        """Naive straight-line extrapolation.

        Straight-line on purpose: the series is driven by other managers'
        behaviour, and pretending to model that with a curve would dress up a
        guess as a forecast. Useful for "roughly what does holding him earn",
        not for anything load-bearing.
        """
        return int(self.value + self.velocity * days)


def valuation(series: ValueSeries, *, window: int = 7, today: date | None = None) -> Valuation:
    """Summarise a series over the last `window` days."""
    latest = series.latest
    if latest is None:
        return Valuation(player_id=series.player_id)

    today = today or latest.date
    velocity = _velocity(series, window, today)
    previous = _velocity(series, window, today - timedelta(days=window))

    return Valuation(
        player_id=series.player_id,
        value=latest.value,
        velocity=velocity,
        acceleration=velocity - previous,
        trend=_trend(velocity, latest.value),
        delta_7d=_delta(series, 7, today),
        delta_30d=_delta(series, 30, today),
        bids=latest.bids,
        days_observed=len(series.points),
    )


def _velocity(series: ValueSeries, window: int, today: date) -> float:
    """Euros per day between the window's endpoints.

    Endpoints rather than a fitted slope: the series is a step function of
    somebody else's nightly job, and the only question being asked is how much
    the price actually moved over the period.
    """
    end = series.on_or_before(today)
    start = series.on_or_before(today - timedelta(days=window))
    if end is None or start is None:
        return 0.0
    elapsed = (end.date - start.date).days
    if elapsed <= 0:
        return 0.0
    return (end.value - start.value) / elapsed


def _delta(series: ValueSeries, days: int, today: date) -> Euros:
    end = series.on_or_before(today)
    start = series.on_or_before(today - timedelta(days=days))
    if end is None or start is None:
        return 0
    return end.value - start.value


def _trend(velocity: float, value: Euros) -> Trend:
    if not value:
        return Trend.UNKNOWN
    if abs(velocity) / value < FLAT_BAND:
        return Trend.FLAT
    return Trend.RISING if velocity > 0 else Trend.FALLING


__all__ = ["FLAT_BAND", "Trend", "Valuation", "valuation"]
