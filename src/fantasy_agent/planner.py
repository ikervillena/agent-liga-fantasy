"""Planning: turning the state of the league into dated, priced proposals.

The planner never touches the network and never executes anything. It takes a
snapshot, a policy and a role book, and returns intents. That makes the most
consequential logic in the project a pure function of its inputs, which is why
it is also the part with real tests.

The order of business encodes the strategy:

1. **Protect first.** Shielding an exposed player always costs half of what
   replacing him would. Anything of ours sitting at a x1.00 premium and about
   to come off its lock outranks every purchase.
2. **Convert dead capital.** Players who have left the competition keep a market
   value in the app but will never score again.
3. **Take the offers worth taking**, on players outside the starting eleven.
4. **Buy**, ranked by euros per point of average gained — never by sticker
   price, because what a signing costs is only meaningful against the player he
   displaces.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .intel.roles import RoleBook
from .intents import Conditions, Intent, IntentKind
from .models import Euros, LeagueState, OwnedPlayer, Position
from .policy import Policy
from .rules import (
    clause_premium,
    cost_to_raise_clause,
    effective_clause,
    euros_per_average_point,
    exposure_deadline,
    is_dead_capital,
)

#: How far ahead the planner looks. Clause locks run fourteen days, so a week
#: is enough to catch every window while keeping the brief readable.
HORIZON = timedelta(days=7)

#: Legal outfield shapes, as (defenders, midfielders, forwards).
FORMATIONS: tuple[tuple[int, int, int], ...] = (
    (3, 4, 3),
    (3, 5, 2),
    (4, 3, 3),
    (4, 4, 2),
    (4, 5, 1),
    (5, 3, 2),
    (5, 4, 1),
)


def best_eleven(squad: tuple[OwnedPlayer, ...]) -> tuple[OwnedPlayer, ...]:
    """The highest-scoring legal eleven available today.

    Tries every legal shape rather than assuming one, because the right
    formation is a consequence of who is fit, not a preference.
    """
    available = [p for p in squad if p.player.status.is_available]
    by_position: dict[Position, list[OwnedPlayer]] = {}
    for player in available:
        by_position.setdefault(player.player.position, []).append(player)
    for players in by_position.values():
        players.sort(key=lambda p: p.player.average_points, reverse=True)

    keepers = by_position.get(Position.GOALKEEPER, [])
    if not keepers:
        return ()

    best: tuple[OwnedPlayer, ...] = ()
    best_total = -1.0
    for defenders, midfielders, forwards in FORMATIONS:
        pool = {
            Position.DEFENDER: defenders,
            Position.MIDFIELDER: midfielders,
            Position.FORWARD: forwards,
        }
        eleven = [keepers[0]]
        legal = True
        for position, count in pool.items():
            candidates = by_position.get(position, [])
            if len(candidates) < count:
                legal = False
                break
            eleven.extend(candidates[:count])
        if not legal:
            continue
        total = sum(p.player.average_points for p in eleven)
        if total > best_total:
            best_total, best = total, tuple(eleven)
    return best


def weakest_in_position(eleven: tuple[OwnedPlayer, ...], position: Position) -> OwnedPlayer | None:
    candidates = [p for p in eleven if p.player.position is position]
    return min(candidates, key=lambda p: p.player.average_points, default=None)


def _passes_filters(
    owned: OwnedPlayer, policy: Policy, roles: RoleBook, now: datetime
) -> tuple[bool, str]:
    """Whether a rival's player is even worth considering. Returns (ok, reason)."""
    player = owned.player
    if player.status.value in policy.filters.exclude_status:
        return False, f"status is {player.status.value}"
    if player.average_points < policy.filters.min_average:
        return False, f"average {player.average_points:.2f} below the floor"

    premium = clause_premium(player.market_value, owned.buyout_clause)
    if premium > policy.filters.max_clause_premium:
        return False, f"clause premium x{premium:.2f} too rich"

    if policy.filters.starters_only:
        role = roles.role_of(player.name, player.id)
        if not role.is_starter:
            return False, f"role is {role.value}"

    if owned.clause_locked_until and owned.clause_locked_until > now + HORIZON:
        return False, "window opens beyond the horizon"
    return True, ""


def plan(
    state: LeagueState,
    policy: Policy,
    roles: RoleBook,
    now: datetime | None = None,
) -> list[Intent]:
    """Produce the intents worth putting in front of a human today."""
    now = now or state.fetched_at
    my_team = state.my_team
    if my_team is None:
        return []

    eleven = best_eleven(my_team.squad)
    starters = {p.id for p in eleven}
    intents: list[Intent] = []

    intents.extend(_protection_intents(my_team.squad, policy, now))
    intents.extend(_liquidation_intents(my_team.squad, starters, policy, now))
    intents.extend(_offer_intents(state, starters, policy, now))
    intents.extend(_purchase_intents(state, eleven, policy, roles, now))

    # Cheapest points first, then by how soon the window opens. A plan the
    # manager reads top to bottom should start with the best value.
    intents.sort(key=lambda i: (i.euros_per_point, i.execute_at))
    return intents


def _protection_intents(
    squad: tuple[OwnedPlayer, ...], policy: Policy, now: datetime
) -> list[Intent]:
    intents: list[Intent] = []
    configured = {item.player_id: item for item in policy.protect}

    for owned in squad:
        deadline = exposure_deadline(owned)
        if deadline is None or deadline > now + HORIZON:
            continue

        override = configured.get(owned.id)
        current = effective_clause(owned.player.market_value, owned.buyout_clause)
        target = override.raise_to if override else current * 3
        cost = cost_to_raise_clause(current, target)
        if cost <= 0:
            continue

        intents.append(
            Intent(
                kind=IntentKind.RAISE_CLAUSE,
                execute_at=max(deadline, now),
                player_id=owned.id,
                player_name=owned.name,
                amount=cost,
                payload={"increase": target - current, "target_clause": target},
                expected_gain=owned.player.average_points,
                rationale=(
                    f"{owned.name} averages {owned.player.average_points:.2f} with no clause "
                    f"premium and comes off his lock on "
                    f"{owned.clause_locked_until:%d/%m %H:%M}. Replacing him would cost "
                    f"several times this."
                ),
                fallback="Leave him exposed and reinvest the fee if somebody takes him.",
                conditions=Conditions(
                    price=cost,
                    average_points=owned.player.average_points,
                    player_status=owned.player.status.value,
                ),
            )
        )
    return intents


def _liquidation_intents(
    squad: tuple[OwnedPlayer, ...], starters: set[str], policy: Policy, now: datetime
) -> list[Intent]:
    intents: list[Intent] = []
    for owned in squad:
        if owned.id in starters and policy.objective.protect_starters:
            continue
        if not is_dead_capital(owned.player):
            continue
        intents.append(
            Intent(
                kind=IntentKind.SELL,
                execute_at=now,
                player_id=owned.id,
                player_name=owned.name,
                amount=owned.player.market_value,
                expected_gain=0.0,
                rationale=(
                    f"{owned.name} has left the competition and cannot score again. "
                    f"He is holding {owned.player.market_value / 1e6:.2f} M of squad value hostage."
                ),
                fallback="If nobody bids, he costs nothing to keep listed.",
                conditions=Conditions(price=owned.player.market_value),
            )
        )
    return intents


def _offer_intents(
    state: LeagueState, starters: set[str], policy: Policy, now: datetime
) -> list[Intent]:
    """Accept bids that beat market value on players we are not starting."""
    intents: list[Intent] = []
    my_team = state.my_team
    if my_team is None:
        return intents
    by_name = {p.name: p for p in my_team.squad}

    for offer in state.offers:
        owned = by_name.get(offer.player_name)
        if owned is None:
            continue
        if owned.id in starters and policy.objective.protect_starters:
            continue
        if offer.amount <= owned.player.market_value:
            continue
        surplus = (offer.amount - owned.player.market_value) / owned.player.market_value
        intents.append(
            Intent(
                kind=IntentKind.ACCEPT_OFFER,
                execute_at=now,
                market_id=offer.market_id,
                offer_id=offer.offer_id,
                player_id=owned.id,
                player_name=owned.name,
                amount=offer.amount,
                expected_gain=0.0,
                rationale=(
                    f"{surplus:+.1%} over market value for a player outside the eleven "
                    f"(average {owned.player.average_points:.2f})."
                ),
                fallback="Let the offer lapse and keep him listed.",
                conditions=Conditions(price=offer.amount),
            )
        )
    return intents


def _purchase_intents(
    state: LeagueState,
    eleven: tuple[OwnedPlayer, ...],
    policy: Policy,
    roles: RoleBook,
    now: datetime,
) -> list[Intent]:
    intents: list[Intent] = []
    budget: Euros = state.cash

    for rival in state.rivals():
        for owned in rival.squad:
            ok, _ = _passes_filters(owned, policy, roles, now)
            if not ok:
                continue

            price = effective_clause(owned.player.market_value, owned.buyout_clause)
            if price > policy.limits.max_per_operation:
                continue

            displaced = weakest_in_position(eleven, owned.player.position)
            baseline = displaced.player.average_points if displaced else 0.0
            gain = owned.player.average_points - baseline
            if gain <= 0:
                continue

            opens_at = owned.clause_locked_until or now
            intents.append(
                Intent(
                    kind=IntentKind.PAY_CLAUSE,
                    execute_at=max(opens_at, now),
                    player_id=owned.id,
                    player_name=owned.name,
                    amount=price,
                    expected_gain=gain,
                    rationale=(
                        f"{owned.name} ({owned.player.club or owned.player.position.value}) "
                        f"averages "
                        f"{owned.player.average_points:.2f} against "
                        f"{baseline:.2f} from {displaced.name if displaced else 'an empty slot'}. "
                        f"{euros_per_average_point(price, gain) / 1e6:.2f} M per point of average, "
                        f"held by {rival.manager}."
                    ),
                    fallback=(
                        "Skip if the budget went elsewhere; the window reopens in fourteen days."
                    ),
                    conditions=Conditions(
                        price=price,
                        average_points=owned.player.average_points,
                        player_status=owned.player.status.value,
                        squad_role=roles.role_of(owned.player.name, owned.player.id).value,
                    ),
                )
            )

    # Rank by value for money, then keep only what the cash could plausibly reach.
    intents.sort(key=lambda i: i.euros_per_point)
    affordable: list[Intent] = []
    for intent in intents:
        if intent.amount > budget:
            continue
        affordable.append(intent)
        budget -= intent.amount
    return affordable


__all__ = [
    "FORMATIONS",
    "HORIZON",
    "best_eleven",
    "plan",
    "weakest_in_position",
]
