"""Upcoming fixtures — the signal the policy asked for and never got.

`fixture_lookahead` sat in the policy from the start while the fixtures were
fetched every sync and then dropped. What is tested here is the resolution:
who a club plays next, in order, named rather than numbered. How hard those
games are is deliberately not modelled — see the module docstring.
"""

from __future__ import annotations

from datetime import timedelta

from fantasy.analysis.fixtures import club_names, describe_run, next_opponents
from fantasy.domain.models import Fixture, LeagueState, Matchday, Position, Team

from .conftest import NOW, make_owned, make_player


def league_with_fixtures() -> LeagueState:
    squad = (
        make_owned(make_player("1", "Mío", Position.MIDFIELDER)),
        make_owned(make_player("2", "Otro", Position.DEFENDER)),
    )
    # Two players, two clubs, so the id-to-name lookup has something to learn.
    squad = (
        squad[0].model_copy(
            update={
                "player": squad[0].player.model_copy(update={"club_id": "1", "club": "Levante"})
            }
        ),
        squad[1].model_copy(
            update={"player": squad[1].player.model_copy(update={"club_id": "2", "club": "Alavés"})}
        ),
    )
    fixtures = (
        Fixture(matchday=7, kickoff=NOW - timedelta(days=1), home_club_id="1", away_club_id="2"),
        Fixture(matchday=8, kickoff=NOW + timedelta(days=7), home_club_id="1", away_club_id="2"),
        Fixture(matchday=9, kickoff=NOW + timedelta(days=14), home_club_id="3", away_club_id="1"),
        Fixture(matchday=10, kickoff=NOW + timedelta(days=21), home_club_id="1", away_club_id="2"),
    )
    return LeagueState(
        fetched_at=NOW,
        league_id="L",
        my_team_id="mine",
        matchday=Matchday(number=7),
        teams=(Team(id="mine", manager="iker", squad=squad),),
        fixtures=fixtures,
    )


class TestUpcomingOnly:
    def test_a_finished_matchday_is_not_upcoming(self):
        found = next_opponents(league_with_fixtures(), "1")
        assert [o.matchday for o in found] == [8, 9, 10]

    def test_it_stops_at_the_lookahead(self):
        assert len(next_opponents(league_with_fixtures(), "1", count=2)) == 2

    def test_an_unknown_club_has_no_fixtures(self):
        assert next_opponents(league_with_fixtures(), "99") == []
        assert next_opponents(league_with_fixtures(), "") == []


class TestHomeAndAway:
    def test_it_knows_which_side_of_the_tie_we_are_on(self):
        found = next_opponents(league_with_fixtures(), "1")
        assert found[0].at_home is True
        assert found[1].at_home is False

    def test_the_opponent_is_the_other_club(self):
        assert next_opponents(league_with_fixtures(), "1")[0].name == "Alavés"


class TestNaming:
    def test_club_names_are_learned_from_the_squads(self):
        assert club_names(league_with_fixtures()) == {"1": "Levante", "2": "Alavés"}

    def test_an_unnamed_club_still_reads_sensibly(self):
        """Falls back to the id rather than dropping the fixture."""
        assert "equipo 3" in describe_run(league_with_fixtures(), "1")

    def test_the_run_reads_as_one_line(self):
        assert describe_run(league_with_fixtures(), "1", count=2) == "J8 vs Alavés · J9 en equipo 3"
