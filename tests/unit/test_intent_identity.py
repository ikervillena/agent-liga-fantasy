"""Identity of an intent, which is what stops the agent repeating itself.

This is a regression suite before it is a unit suite. The agent used to put the
same signing to the manager over and over — fifteen messages for one decision —
and the cause was not the approval machinery but the identity function feeding
it. Two things moved underneath it: the market value of every player changes
every night, and `execute_at` collapses to "now" for an opportunity that is
already live. Either was enough to mint a fresh identity and ask again.

So these tests pin the two properties that matter: the same opportunity keeps
its key while the world drifts around it, and genuinely different
opportunities never collide.
"""

from __future__ import annotations

from datetime import timedelta

from fantasy.analysis.candidates import plan
from fantasy.domain.intents import Conditions, Intent, IntentKind
from fantasy.domain.models import LeagueState, OwnedPlayer

from .conftest import NOW, ROLES, make_policy


def _intent(**overrides: object) -> Intent:
    base: dict[str, object] = {
        "kind": IntentKind.PAY_CLAUSE,
        "execute_at": NOW,
        "rationale": "because",
        "player_id": "99",
        "amount": 20_000_000,
        "anchor": NOW + timedelta(days=2),
    }
    return Intent.model_validate(base | overrides)


class TestPriceIsNotIdentity:
    """A price that moves is the same deal until the tolerance says otherwise."""

    def test_nightly_value_drift_keeps_the_same_key(self):
        cheap = _intent(amount=12_998_678)
        dearer = _intent(amount=12_869_602)  # four nights later, observed live
        assert cheap.key == dearer.key

    def test_the_drift_is_still_visible_where_it_belongs(self):
        """Excluding price from identity must not hide it from revalidation."""
        conditions = Conditions(price=12_998_678, price_tolerance=0.05)
        assert conditions.price_still_acceptable(12_869_602)
        assert not conditions.price_still_acceptable(20_000_000)


class TestPollingDoesNotMintNewIdentities:
    def test_execute_at_does_not_affect_the_key(self):
        first = _intent(execute_at=NOW)
        later = _intent(execute_at=NOW + timedelta(minutes=15))
        assert first.key == later.key

    def test_planning_twice_over_a_polling_cycle_is_idempotent(self, league: LeagueState):
        """The end-to-end property: poll again, get the same decisions.

        Fifteen minutes on and a one percent value move is exactly what the
        live workflow does all day. It must produce no new work.
        """

        before = {i.key for i in plan(league, make_policy(), ROLES, now=NOW)}
        drifted = _with_values_moved(league, 1.01)
        later = NOW + timedelta(minutes=15)
        after = {i.key for i in plan(drifted, make_policy(), ROLES, now=later)}

        assert before == after
        assert before, "the fixture must produce at least one intent for this to mean anything"


class TestDistinctOpportunitiesStayDistinct:
    def test_different_players_differ(self):
        assert _intent(player_id="1").key != _intent(player_id="2").key

    def test_different_operations_on_one_player_differ(self):
        pay = _intent(kind=IntentKind.PAY_CLAUSE)
        raise_ = _intent(kind=IntentKind.RAISE_CLAUSE)
        assert pay.key != raise_.key

    def test_a_later_window_on_the_same_player_is_a_new_opportunity(self):
        """A clause reopening in a fortnight is a fresh decision, not the old one."""
        this_window = _intent(anchor=NOW + timedelta(days=2))
        next_window = _intent(anchor=NOW + timedelta(days=16))
        assert this_window.key != next_window.key

    def test_distinct_offers_differ(self):
        first = _intent(kind=IntentKind.ACCEPT_OFFER, offer_id="a", anchor=None)
        second = _intent(kind=IntentKind.ACCEPT_OFFER, offer_id="b", anchor=None)
        assert first.key != second.key


def _with_values_moved(state: LeagueState, factor: float) -> LeagueState:
    """The same league a night later: every market value nudged by `factor`."""

    def move(owned: OwnedPlayer) -> OwnedPlayer:
        player = owned.player.model_copy(
            update={"market_value": int(owned.player.market_value * factor)}
        )
        return owned.model_copy(update={"player": player})

    teams = tuple(
        team.model_copy(update={"squad": tuple(move(p) for p in team.squad)})
        for team in state.teams
    )
    return state.model_copy(update={"teams": teams})
