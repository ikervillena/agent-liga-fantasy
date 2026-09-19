"""Matchday deadlines and solvency — the rules whose absence produced nonsense.

Each test here corresponds to advice the agent actually gave and should not
have: signing somebody to field him in a matchday that had already started,
and spending down to a negative balance as though it were a soft warning.
"""

from __future__ import annotations

from datetime import timedelta

from fantasy.domain.models import LeagueConfig, Matchday, OwnedPlayer, Position
from fantasy.domain.rules import (
    can_pay_clause,
    clause_block_begins,
    is_lineup_locked,
    lineup_deadline,
    projected_cash,
    shortfall,
    signing_deadline,
    will_score,
)

from .conftest import NOW, make_owned, make_player

KICKOFF = NOW + timedelta(days=2)

#: A matchday that opens in two days and runs for three. The gap between the
#: two dates is the whole point: only the first matters.
MATCHDAY = Matchday(number=5, opens_at=KICKOFF, closes_at=KICKOFF + timedelta(days=3))


class TestLineupDeadline:
    def test_the_deadline_is_the_first_kickoff_not_the_closing_date(self):
        assert lineup_deadline(MATCHDAY) == KICKOFF

    def test_open_before_kickoff(self):
        assert not is_lineup_locked(MATCHDAY, KICKOFF - timedelta(minutes=1))

    def test_locked_from_kickoff_onwards(self):
        assert is_lineup_locked(MATCHDAY, KICKOFF)
        assert is_lineup_locked(MATCHDAY, KICKOFF + timedelta(days=1))

    def test_no_matchday_means_no_deadline(self):
        assert lineup_deadline(None) is None
        assert not is_lineup_locked(None, NOW)


class TestClauseBlockWindow:
    def test_no_block_by_default(self):
        assert clause_block_begins(MATCHDAY, LeagueConfig()) is None

    def test_a_block_moves_the_signing_deadline_earlier(self):
        config = LeagueConfig(clause_block_hours=24)
        assert clause_block_begins(MATCHDAY, config) == KICKOFF - timedelta(hours=24)
        assert signing_deadline(MATCHDAY, config) == KICKOFF - timedelta(hours=24)

    def test_without_a_block_the_signing_deadline_is_the_kickoff(self):
        assert signing_deadline(MATCHDAY, LeagueConfig()) == KICKOFF


class TestCanPayClause:
    """The veto the judgment layer is shown, reason included."""

    def _open(self) -> OwnedPlayer:
        player = make_player("1", "Mandi", Position.DEFENDER)
        return make_owned(player, manager="rival", team_id="theirs")

    def test_an_open_unshielded_clause_is_payable(self):
        ok, reason = can_pay_clause(self._open(), NOW, MATCHDAY, LeagueConfig())
        assert ok and reason == ""

    def test_a_locked_clause_is_refused_with_the_date(self):
        owned = make_owned(
            make_player("1", "Mandi", Position.DEFENDER),
            manager="rival",
            team_id="theirs",
            locked_until=NOW + timedelta(days=3),
        )
        ok, reason = can_pay_clause(owned, NOW)
        assert not ok
        assert "locked until" in reason

    def test_a_shielded_player_is_refused(self):
        owned = self._open().model_copy(update={"is_shielded": True})
        ok, reason = can_pay_clause(owned, NOW)
        assert not ok
        assert "shielded" in reason

    def test_refused_inside_the_pre_matchday_block(self):
        """The case that produced "sign him for this matchday" a day too late."""
        config = LeagueConfig(clause_block_hours=24)
        ok, reason = can_pay_clause(self._open(), KICKOFF - timedelta(hours=20), MATCHDAY, config)
        assert not ok
        assert "blocked" in reason

    def test_allowed_just_before_the_block_opens(self):
        config = LeagueConfig(clause_block_hours=24)
        ok, _ = can_pay_clause(self._open(), KICKOFF - timedelta(hours=25), MATCHDAY, config)
        assert ok

    def test_refused_where_the_league_plays_without_clauses(self):
        ok, reason = can_pay_clause(self._open(), NOW, MATCHDAY, LeagueConfig(buyout_clauses=False))
        assert not ok
        assert "without buyout clauses" in reason


class TestSolvency:
    def test_spending_and_proceeds_net_out(self):
        assert projected_cash(30_000_000, spending=20_000_000, proceeds=5_000_000) == 15_000_000

    def test_a_solvent_squad_scores(self):
        assert will_score(1)
        assert will_score(0)

    def test_a_squad_in_the_red_scores_nothing(self):
        """Not a warning: zero points for the entire matchday."""
        assert not will_score(-1)

    def test_the_shortfall_is_what_has_to_be_raised(self):
        assert shortfall(-4_000_000) == 4_000_000
        assert shortfall(2_000_000) == 0

    def test_a_reserve_raises_the_bar(self):
        assert not will_score(1_000_000, reserve=5_000_000)
        assert shortfall(1_000_000, reserve=5_000_000) == 4_000_000
