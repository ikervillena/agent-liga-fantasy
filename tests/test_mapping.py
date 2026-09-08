"""Mapping is where a LaLiga rename would break us, so it is tested on shapes
we have actually seen, including the ones that arrive half-empty."""

from __future__ import annotations

from fantasy_agent.laliga.mapping import (
    as_int,
    pick,
    squad_entries,
    to_matchday,
    to_owned_player,
    to_player,
)
from fantasy_agent.models import PlayerStatus, Position

RAW_PLAYER = {
    "id": "2932",
    "nickname": "Angel Perez",
    "positionId": "4",
    "teamId": "21",
    "marketValue": "11351598",
    "points": 40,
    "averagePoints": 10.0,
    "playerStatus": "ok",
    "weekPoints": [{"weekNumber": 4, "points": 12}, {"weekNumber": 3, "points": 7}],
}


class TestPlayerMapping:
    def test_reads_the_fields_we_depend_on(self) -> None:
        player = to_player(RAW_PLAYER)
        assert player.name == "Angel Perez"
        assert player.position is Position.FORWARD
        assert player.market_value == 11_351_598
        assert player.points_by_matchday == {3: 7, 4: 12}

    def test_an_unfamiliar_status_degrades_instead_of_raising(self) -> None:
        player = to_player({**RAW_PLAYER, "playerStatus": "brand_new_state"})
        assert player.status is PlayerStatus.UNKNOWN

    def test_an_empty_payload_still_produces_a_player(self) -> None:
        assert to_player({}).name == "?"


class TestSquadMapping:
    def test_reads_a_nested_squad_entry(self) -> None:
        owned = to_owned_player(
            {
                "id": "55054262",
                "playerMaster": RAW_PLAYER,
                "buyoutClause": 11_351_598,
                "buyoutClauseLockedEndTime": "2026-09-13T23:26:16+02:00",
            },
            team_id="38611081",
            manager="iker_villena",
        )
        assert owned.name == "Angel Perez"
        assert owned.buyout_clause == 11_351_598
        assert owned.clause_locked_until is not None
        assert owned.clause_locked_until.day == 13

    def test_accepts_both_shapes_the_squad_endpoint_has_returned(self) -> None:
        assert len(squad_entries([{"a": 1}, "junk"])) == 1
        assert len(squad_entries({"players": [{"a": 1}]})) == 1
        assert squad_entries(None) == []


class TestHelpers:
    def test_pick_tries_each_spelling_in_turn(self) -> None:
        assert pick({"money": 5}, "teamMoney", "money") == 5
        assert pick({}, "a", "b", default="fallback") == "fallback"

    def test_as_int_survives_the_strings_the_api_sends(self) -> None:
        assert as_int("11351598") == 11_351_598
        assert as_int(None) == 0
        assert as_int("not a number", default=-1) == -1

    def test_matchday_carries_the_closing_time_the_planner_needs(self) -> None:
        matchday = to_matchday(
            {"weekNumber": 5, "isLive": False, "closingWeekDate": "2026-09-11T21:00:00+02:00"}
        )
        assert matchday is not None
        assert matchday.number == 5
        assert matchday.closes_at is not None
