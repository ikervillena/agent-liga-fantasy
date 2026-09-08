"""Planning: which eleven we field, and which signings are worth proposing."""

from __future__ import annotations

from datetime import datetime, timedelta

from fantasy_agent.intel.roles import RoleBook
from fantasy_agent.intents import IntentKind
from fantasy_agent.models import (
    LeagueState,
    OwnedPlayer,
    PlayerStatus,
    Position,
    SquadRole,
)
from fantasy_agent.planner import best_eleven, plan, weakest_in_position
from fantasy_agent.policy import Policy

from .conftest import make_owned, make_player

ROLES = RoleBook({"star": SquadRole.KEY})


def policy(**overrides: object) -> Policy:
    return Policy.model_validate({"league_id": "L", "team_id": "mine", **overrides})


class TestBestEleven:
    def test_picks_a_legal_shape_and_fills_it(self, squad: tuple[OwnedPlayer, ...]) -> None:
        eleven = best_eleven(squad)
        assert len(eleven) == 11
        assert sum(1 for p in eleven if p.player.position is Position.GOALKEEPER) == 1

    def test_drops_the_weakest_when_there_is_a_choice(self, squad: tuple[OwnedPlayer, ...]) -> None:
        # With exactly eleven players every shape is forced; add a twelfth and
        # the selector has to actually choose.
        spare = make_owned(make_player("12", "Mid D", Position.MIDFIELDER, average=9.0))
        names = {p.name for p in best_eleven((*squad, spare))}
        assert "Mid D" in names
        assert "Mid C" not in names

    def test_a_squad_with_no_keeper_cannot_be_fielded(self, squad: tuple[OwnedPlayer, ...]) -> None:
        outfield = tuple(p for p in squad if p.player.position is not Position.GOALKEEPER)
        assert best_eleven(outfield) == ()

    def test_injured_players_are_not_selected(self, squad: tuple[OwnedPlayer, ...]) -> None:
        hurt = make_owned(
            make_player(
                "20", "Crocked", Position.FORWARD, average=20.0, status=PlayerStatus.INJURED
            )
        )
        assert "Crocked" not in {p.name for p in best_eleven((*squad, hurt))}

    def test_weakest_link_is_the_baseline_for_an_upgrade(
        self, squad: tuple[OwnedPlayer, ...]
    ) -> None:
        weakest = weakest_in_position(best_eleven(squad), Position.MIDFIELDER)
        assert weakest is not None
        assert weakest.player.average_points == 2.0


class TestPlanning:
    def test_proposes_a_rival_starter_who_would_improve_the_eleven(
        self, league: LeagueState
    ) -> None:
        intents = plan(league, policy(), ROLES)
        purchases = [i for i in intents if i.kind is IntentKind.PAY_CLAUSE]
        assert [i.player_name for i in purchases] == ["Star"]
        assert purchases[0].expected_gain > 0

    def test_an_unknown_role_is_never_proposed(self, league: LeagueState) -> None:
        intents = plan(league, policy(), RoleBook({}))
        assert not [i for i in intents if i.kind is IntentKind.PAY_CLAUSE]

    def test_nothing_is_proposed_beyond_the_cash_we_hold(self, league: LeagueState) -> None:
        broke = league.model_copy(update={"cash": 1_000})
        assert not [i for i in plan(broke, policy(), ROLES) if i.kind is IntentKind.PAY_CLAUSE]

    def test_an_exposed_starter_gets_a_shielding_intent(
        self, league: LeagueState, now: datetime
    ) -> None:
        me = league.my_team
        assert me is not None
        star = me.squad[8]  # Fwd A, 10.0 average, clause at par
        exposed = star.model_copy(update={"clause_locked_until": now + timedelta(days=1)})
        squad = (*me.squad[:8], exposed, *me.squad[9:])
        state = league.model_copy(
            update={
                "teams": tuple(
                    t.model_copy(update={"squad": squad}) if t.id == "mine" else t
                    for t in league.teams
                )
            }
        )
        shields = [i for i in plan(state, policy(), ROLES) if i.kind is IntentKind.RAISE_CLAUSE]
        assert [i.player_name for i in shields] == ["Fwd A"]

    def test_dead_capital_is_listed_for_sale(self, league: LeagueState) -> None:
        me = league.my_team
        assert me is not None
        gone = make_owned(
            make_player("77", "Departed", Position.MIDFIELDER, status=PlayerStatus.OUT_OF_LEAGUE)
        )
        state = league.model_copy(
            update={
                "teams": tuple(
                    t.model_copy(update={"squad": (*t.squad, gone)}) if t.id == "mine" else t
                    for t in league.teams
                )
            }
        )
        sales = [i for i in plan(state, policy(), ROLES) if i.kind is IntentKind.SELL]
        assert [i.player_name for i in sales] == ["Departed"]

    def test_cheapest_points_are_proposed_first(self, league: LeagueState) -> None:
        intents = plan(league, policy(), ROLES)
        costs = [i.euros_per_point for i in intents]
        assert costs == sorted(costs)
