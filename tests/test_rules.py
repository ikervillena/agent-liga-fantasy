"""The game mechanics. These are the functions that decide what money buys."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fantasy_agent.models import PlayerStatus, Position, SquadRole
from fantasy_agent.rules import (
    CLAUSE_LOCK,
    clause_premium,
    clause_reopens_at,
    cost_to_raise_clause,
    effective_clause,
    euros_per_average_point,
    exposure_deadline,
    is_clause_open,
    is_dead_capital,
    passes_squad_role_filter,
)

from .conftest import make_owned, make_player


class TestEffectiveClause:
    """The clause is a floor that rises with value, never a frozen price."""

    def test_holds_while_value_climbs_towards_it(self) -> None:
        assert effective_clause(11_000_000, 13_200_001) == 13_200_001

    def test_follows_the_value_once_overtaken(self) -> None:
        # Fran Garcia: clause 13.2 M, value climbed to 15.4 M, clause went with it.
        assert effective_clause(15_400_091, 13_200_001) == 15_400_091

    def test_a_player_at_par_carries_no_premium(self) -> None:
        assert clause_premium(43_148_521, 43_148_521) == pytest.approx(1.0)

    def test_a_stale_clause_below_value_still_reports_par(self) -> None:
        assert clause_premium(20_000_000, 15_000_000) == pytest.approx(1.0)


class TestRaisingAClause:
    def test_costs_half_of_the_increase(self) -> None:
        assert cost_to_raise_clause(11_351_598, 34_000_000) == 11_324_201

    def test_lowering_is_free_because_it_is_impossible(self) -> None:
        assert cost_to_raise_clause(30_000_000, 10_000_000) == 0


class TestWindows:
    def test_no_lock_means_open(self) -> None:
        assert is_clause_open(None, datetime.now(UTC))

    def test_reopens_fourteen_days_after_signing(self) -> None:
        signed = datetime(2026, 8, 31, 22, 15, tzinfo=UTC)
        assert clause_reopens_at(signed) == signed + CLAUSE_LOCK
        assert clause_reopens_at(signed).day == 14


class TestValueForMoney:
    def test_price_per_point_of_average_gained(self) -> None:
        assert euros_per_average_point(10_550_000, 5.33) == pytest.approx(1_979_362, rel=1e-3)

    def test_no_gain_is_infinitely_expensive(self) -> None:
        assert euros_per_average_point(50_000_000, 0.0) == float("inf")


class TestFilters:
    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            (SquadRole.KEY, True),
            (SquadRole.IMPORTANT, True),
            (SquadRole.ROTATION, False),
            (SquadRole.IMPACT_SUB, False),
            (SquadRole.BENCH, False),
            (SquadRole.UNKNOWN, False),
        ],
    )
    def test_only_genuine_starters_pass(self, role: SquadRole, expected: bool) -> None:
        assert passes_squad_role_filter(role) is expected

    def test_players_out_of_the_league_are_dead_capital(self) -> None:
        gone = make_player("1", "Gone", Position.MIDFIELDER, status=PlayerStatus.OUT_OF_LEAGUE)
        assert is_dead_capital(gone)


class TestExposure:
    def test_a_player_at_par_needs_shielding_before_his_lock_ends(self) -> None:
        lock_ends = datetime(2026, 9, 13, 23, 26, tzinfo=UTC)
        owned = make_owned(
            make_player("1", "Angel Perez", Position.FORWARD, value=11_351_598, average=10.0),
            locked_until=lock_ends,
        )
        assert exposure_deadline(owned) == lock_ends - timedelta(days=2)

    def test_a_player_with_a_real_premium_is_not_worth_shielding(self) -> None:
        owned = make_owned(
            make_player("2", "Riquelme", Position.MIDFIELDER, value=12_775_764),
            clause=23_728_492,
            locked_until=datetime(2026, 9, 13, tzinfo=UTC),
        )
        assert exposure_deadline(owned) is None
