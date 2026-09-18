"""Reading price history, checked against a real captured season.

The fixture is Mandi's actual history as the API served it: thirty-four days in
which he went from 9.45 M to 12.87 M. He is a useful specimen precisely because
the naive view of him is wrong — he was bought on a 7.33 average and has since
appreciated 36%, which no points-based metric in the old planner could see.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from fantasy.analysis.valuation import Trend, valuation
from fantasy.domain.models import ValuePoint, ValueSeries
from fantasy.sources.laliga.market_value import parse_series

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "laliga" / "market_value_3174.json"


@pytest.fixture
def mandi() -> ValueSeries:
    return parse_series("3174", json.loads(FIXTURE.read_text(encoding="utf-8")))


def series(*values: int, start: date = date(2026, 9, 1)) -> ValueSeries:
    """A synthetic series, one point per day from `start`."""
    return ValueSeries(
        player_id="x",
        points=tuple(
            ValuePoint(date=start + timedelta(days=i), value=v) for i, v in enumerate(values)
        ),
    )


class TestParsing:
    def test_reads_the_whole_captured_season(self, mandi: ValueSeries):
        assert len(mandi.points) == 34
        assert mandi.points[0].value == 9_454_867
        assert mandi.latest is not None
        assert mandi.latest.value == 12_869_602

    def test_points_come_out_oldest_first(self, mandi: ValueSeries):
        dates = [p.date for p in mandi.points]
        assert dates == sorted(dates)

    def test_a_malformed_row_is_dropped_not_fatal(self):
        """One bad night must not cost the agent the other eighty."""
        payload = [
            {"date": "2026-09-01T00:00:00+02:00", "marketValue": 1_000_000, "bids": 0},
            {"date": "not a date", "marketValue": 1_000_000},
            {"date": "2026-09-02T00:00:00+02:00", "marketValue": None},
            {"date": "2026-09-03T00:00:00+02:00", "marketValue": 1_200_000},
        ]
        parsed = parse_series("x", payload)
        assert [p.value for p in parsed.points] == [1_000_000, 1_200_000]

    def test_an_unexpected_payload_yields_an_empty_series(self):
        assert parse_series("x", {"error": "nope"}).points == ()
        assert parse_series("x", None).points == ()


class TestGapsInHistory:
    def test_a_missing_day_falls_back_to_the_last_known(self):
        sparse = ValueSeries(
            player_id="x",
            points=(
                ValuePoint(date=date(2026, 9, 1), value=1_000_000),
                ValuePoint(date=date(2026, 9, 5), value=1_500_000),
            ),
        )
        found = sparse.on_or_before(date(2026, 9, 3))
        assert found is not None
        assert found.value == 1_000_000

    def test_asking_before_the_series_starts_yields_nothing(self):
        assert series(1_000_000).on_or_before(date(2026, 8, 1)) is None


class TestVelocityAndTrend:
    def test_a_steady_climb_reads_as_rising(self):
        v = valuation(series(1_000_000, 1_100_000, 1_200_000, 1_300_000), window=3)
        assert v.trend is Trend.RISING
        assert v.velocity == pytest.approx(100_000)

    def test_a_steady_slide_reads_as_falling(self):
        v = valuation(series(1_300_000, 1_200_000, 1_100_000, 1_000_000), window=3)
        assert v.trend is Trend.FALLING
        assert v.velocity == pytest.approx(-100_000)

    def test_valuation_noise_reads_as_flat(self):
        """A static player still wanders a few thousand a night. That is not a trend."""
        v = valuation(series(10_000_000, 10_002_000, 9_999_000, 10_001_000), window=3)
        assert v.trend is Trend.FLAT

    def test_an_empty_series_says_unknown_rather_than_zero(self):
        v = valuation(ValueSeries(player_id="x"))
        assert v.trend is Trend.UNKNOWN
        assert v.days_observed == 0

    def test_mandi_is_appreciating_on_the_real_history(self, mandi: ValueSeries):
        v = valuation(mandi)
        assert v.trend is Trend.RISING
        assert v.velocity > 0
        assert v.delta_30d > 2_000_000
        assert v.days_observed == 34


class TestAcceleration:
    def test_a_rise_that_speeds_up_accelerates(self):
        # +10k/day for three days, then +100k/day for three.
        v = valuation(series(1_000_000, 1_010_000, 1_020_000, 1_120_000, 1_220_000), window=2)
        assert v.acceleration > 0

    def test_a_rise_that_stalls_decelerates(self):
        v = valuation(series(1_000_000, 1_100_000, 1_200_000, 1_205_000, 1_206_000), window=2)
        assert v.acceleration < 0


class TestComparability:
    def test_percentage_velocity_compares_across_price_brackets(self):
        """200k a day is spectacular on a cheap player and noise on a dear one."""
        cheap = valuation(series(5_000_000, 5_200_000), window=1)
        dear = valuation(series(100_000_000, 100_200_000), window=1)
        assert cheap.velocity == dear.velocity
        assert cheap.velocity_pct > dear.velocity_pct * 10

    def test_projection_is_a_straight_line(self):
        v = valuation(series(1_000_000, 1_100_000), window=1)
        assert v.projected(3) == pytest.approx(1_400_000, abs=1)
