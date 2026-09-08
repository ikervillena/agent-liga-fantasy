"""The mechanics of LaLiga Fantasy, as pure functions.

Every rule here was verified against live league data rather than taken from
documentation, because the official rules are vague and the app is the only
real specification. The comments record what the evidence was, since that is
the part a future reader cannot re-derive.

Nothing in this module does I/O. That is deliberate: these are the decisions
that cost real money, so they are the ones worth testing exhaustively.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import Euros, OwnedPlayer, Player, SquadRole

#: Raising a buyout clause costs half of the increase: pay X, the clause grows 2X.
CLAUSE_RAISE_FACTOR = 2.0

#: A signing locks the player's clause for fourteen days. This is what makes the
#: game plannable: every opportunity has a known opening instant.
CLAUSE_LOCK = timedelta(days=14)


def effective_clause(player_value: Euros, recorded_clause: Euros) -> Euros:
    """The clause a rival would actually pay today.

    The clause is a *floor*, not a frozen price. It stays put while the market
    value climbs towards it, and once the value overtakes it the clause rises
    with the value from then on. Verified across every owned player in the
    league: not one had a clause below their market value.

    The consequence that matters: a player at a x1.00 ratio has no premium at
    all, so he can be taken at market price — and equally, his owner collects
    no premium when it happens.
    """
    return max(recorded_clause, player_value)


def clause_premium(player_value: Euros, clause: Euros) -> float:
    """Clause divided by value. 1.00 means no premium; 1.30 means paying 30% over."""
    if player_value <= 0:
        return float("inf")
    return effective_clause(player_value, clause) / player_value


def cost_to_raise_clause(
    current_clause: Euros,
    target_clause: Euros,
    factor: float = CLAUSE_RAISE_FACTOR,
) -> Euros:
    """What it costs to lift a clause to `target_clause`.

    You pay half of the increase. Protecting a player is therefore always
    cheaper than replacing him, which is why shielding outranks buying whenever
    an exposed asset is about to come off its lock.
    """
    if target_clause <= current_clause:
        return 0
    return int((target_clause - current_clause) / factor)


def is_clause_open(locked_until: datetime | None, now: datetime) -> bool:
    """Whether the clause can be paid right now."""
    return locked_until is None or locked_until <= now


def clause_reopens_at(signed_at: datetime) -> datetime:
    """When a player signed at `signed_at` becomes takeable again.

    Useful in both directions: it tells us when a rival's new signing becomes
    reachable, and when a player somebody took from us can be won back.
    """
    return signed_at + CLAUSE_LOCK


def euros_per_average_point(price: Euros, average_gained: float) -> float:
    """Cost of one point of matchday average, the yardstick for every signing.

    Absolute price is a bad guide. What matters is what a signing adds over the
    player he displaces from the starting eleven, which is why this takes a
    delta rather than the incoming player's average.
    """
    if average_gained <= 0:
        return float("inf")
    return price / average_gained


def is_dead_capital(player: Player) -> bool:
    """Value tied up in a player who cannot score again.

    Players who leave the competition keep a market value in the app long after
    they stop being worth anything, which makes a squad look richer than it is.
    """
    from .models import PlayerStatus

    return player.status is PlayerStatus.OUT_OF_LEAGUE


def passes_squad_role_filter(role: SquadRole) -> bool:
    """Only players who genuinely start for their club.

    This filter has rejected more good-looking signings than any other rule:
    high averages built on a handful of substitute appearances regress hard.
    Unknown roles fail closed — if we could not confirm he plays, we do not buy.
    """
    return role.is_starter


def exposure_deadline(
    owned: OwnedPlayer, warning: timedelta = timedelta(days=2)
) -> datetime | None:
    """When one of our own players needs shielding, or None if he is not exposed.

    Only players at (or under) a x1.00 premium are worth protecting: anyone with
    a real premium already costs a rival more than he is worth on the market.
    """
    if owned.clause_locked_until is None:
        return None
    if clause_premium(owned.player.market_value, owned.buyout_clause) > 1.02:
        return None
    return owned.clause_locked_until - warning


def upgrade_gain(incoming: Player, outgoing_average: float) -> float:
    """Points of average gained by swapping `outgoing_average` for `incoming`."""
    return incoming.average_points - outgoing_average


__all__ = [
    "CLAUSE_LOCK",
    "CLAUSE_RAISE_FACTOR",
    "clause_premium",
    "clause_reopens_at",
    "cost_to_raise_clause",
    "effective_clause",
    "euros_per_average_point",
    "exposure_deadline",
    "is_clause_open",
    "is_dead_capital",
    "passes_squad_role_filter",
    "upgrade_gain",
]
