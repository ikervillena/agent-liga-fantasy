"""The brief is what the manager actually reads, so it gets tested like output
that matters: the right facts, in the right order, with nothing invented."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fantasy_agent.approvals import Approval, ApprovalState
from fantasy_agent.brief import ask_text, compose, when
from fantasy_agent.intents import Intent, IntentKind
from fantasy_agent.models import LeagueState, PlayerStatus, Position

from .conftest import make_owned, make_player

NOW = datetime(2026, 9, 8, 20, 0, tzinfo=UTC)


def sample_intent() -> Intent:
    return Intent(
        kind=IntentKind.PAY_CLAUSE,
        execute_at=NOW + timedelta(days=1),
        player_id="99",
        player_name="Star",
        amount=20_000_000,
        expected_gain=2.0,
        rationale="Starter with no premium.",
        fallback="Skip and revisit in a fortnight.",
    )


class TestHeadline:
    def test_opens_with_position_and_the_gap_to_the_leader(self, league: LeagueState) -> None:
        text = compose(league, None, [], [], NOW)
        assert "19 behind rival" in text
        assert "30,00 M" in text  # cash, in the format the app uses

    def test_money_uses_the_spanish_decimal_comma(self, league: LeagueState) -> None:
        assert "30.00 M" not in compose(league, None, [], [], NOW)


class TestSections:
    def test_reports_a_rival_window_opening_this_week(self, league: LeagueState) -> None:
        assert "Clause windows this week" in compose(league, None, [], [], NOW)
        assert "Star" in compose(league, None, [], [], NOW)

    def test_flags_our_own_players_with_no_premium(self, league: LeagueState) -> None:
        assert "Yours with no premium" in compose(league, None, [], [], NOW)

    def test_reports_value_moves_against_the_previous_snapshot(self, league: LeagueState) -> None:
        me = league.my_team
        assert me is not None
        cheaper = tuple(
            p.model_copy(update={"player": p.player.model_copy(update={"market_value": 5_000_000})})
            for p in me.squad
        )
        before = league.model_copy(
            update={
                "teams": tuple(
                    t.model_copy(update={"squad": cheaper}) if t.id == "mine" else t
                    for t in league.teams
                )
            }
        )
        assert "Value moves" in compose(league, before, [], [], NOW)

    def test_says_so_plainly_when_there_is_nothing_to_propose(self, league: LeagueState) -> None:
        assert "Nothing new to propose" in compose(league, None, [], [], NOW)

    def test_lists_what_is_waiting_on_the_manager(self, league: LeagueState) -> None:
        waiting = Approval(intent=sample_intent())
        waiting.transition(ApprovalState.PENDING, NOW, "asked")
        text = compose(league, None, [], [waiting], NOW)
        assert "Waiting on you" in text
        assert "Star" in text

    def test_an_unavailable_player_is_not_offered_as_an_opportunity(
        self, league: LeagueState
    ) -> None:
        hurt = make_owned(
            make_player(
                "98", "Crocked", Position.MIDFIELDER, average=12.0, status=PlayerStatus.INJURED
            ),
            manager="rival",
            team_id="theirs",
        )
        state = league.model_copy(
            update={
                "teams": tuple(
                    t.model_copy(update={"squad": (*t.squad, hurt)}) if t.id == "theirs" else t
                    for t in league.teams
                )
            }
        )
        assert "Crocked" not in compose(state, None, [], [], NOW)


class TestApprovalRequest:
    def test_carries_the_decision_a_manager_needs(self) -> None:
        text = ask_text(sample_intent())
        assert "Star" in text
        assert "Starter with no premium." in text
        assert "per point" in text
        assert "If not:" in text


def test_dates_read_as_a_day_and_a_time() -> None:
    assert when(datetime(2026, 9, 11, 21, 0, tzinfo=UTC)) == "Fri 11 21:00"
