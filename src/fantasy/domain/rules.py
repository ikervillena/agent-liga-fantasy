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

from fantasy.domain.models import Euros, LeagueConfig, Matchday, OwnedPlayer, Player, SquadRole

#: Raising a buyout clause costs half of the increase: pay X, the clause grows 2X.
CLAUSE_RAISE_FACTOR = 2.0

#: A signing locks the player's clause for fourteen days. This is what makes the
#: game plannable: every opportunity has a known opening instant.
CLAUSE_LOCK = timedelta(days=14)

#: Lowering a clause bars raising it again for two days, and the cut is published
#: on the league board. Freeing cash that way is therefore not reversible inside
#: a matchday: it advertises the player and leaves him cheap until the lock lifts.
CLAUSE_LOWERING_LOCK = timedelta(hours=48)


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
    from fantasy.domain.models import PlayerStatus

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


# ---------------------------------------------------------------------------
# Matchday deadlines
#
# Everything below exists because the agent used to reason as if a matchday
# were a period rather than a wall. It is a wall: the eleven freezes at the
# first kick-off, and nothing bought or sold afterwards counts for that week.
# ---------------------------------------------------------------------------


def lineup_deadline(matchday: Matchday | None) -> datetime | None:
    """The instant the eleven freezes: the first kick-off of the matchday.

    Not the closing date. `closes_at` is when the last match ends, which is
    days later and has no bearing on any decision — confusing the two is what
    produces advice like "sign him so you can field him this week" about a
    matchday that started yesterday.
    """
    return matchday.opens_at if matchday else None


def is_lineup_locked(matchday: Matchday | None, now: datetime) -> bool:
    """Whether the eleven for this matchday can still be changed."""
    deadline = lineup_deadline(matchday)
    return deadline is not None and now >= deadline


def clause_block_begins(matchday: Matchday | None, config: LeagueConfig) -> datetime | None:
    """When this league stops accepting clause payments before a matchday.

    Leagues may bar clause signings for 24 to 72 hours before the first
    kick-off. Where the setting is off the answer is None and clauses stay
    payable until the whistle, but where it is on it moves the last useful
    moment to sign anybody a full day or more earlier than the lineup deadline.
    """
    deadline = lineup_deadline(matchday)
    if deadline is None or config.clause_block_hours <= 0:
        return None
    return deadline - timedelta(hours=config.clause_block_hours)


def signing_deadline(matchday: Matchday | None, config: LeagueConfig) -> datetime | None:
    """The last instant a signing can still affect this matchday."""
    return clause_block_begins(matchday, config) or lineup_deadline(matchday)


def can_pay_clause(
    owned: OwnedPlayer,
    now: datetime,
    matchday: Matchday | None = None,
    config: LeagueConfig | None = None,
) -> tuple[bool, str]:
    """Whether this clause can legally be paid right now, and why not if it cannot.

    The reason matters as much as the verdict: it is what the judgment layer is
    shown so that it reasons *with* the constraint instead of proposing
    something the game will reject.
    """
    config = config or LeagueConfig()

    if not config.buyout_clauses:
        return False, "this league plays without buyout clauses"
    if owned.is_shielded:
        return False, f"{owned.name} is shielded"
    if not is_clause_open(owned.clause_locked_until, now):
        return False, f"clause locked until {owned.clause_locked_until:%d/%m %H:%M}"

    blocked_from = clause_block_begins(matchday, config)
    if blocked_from is not None and now >= blocked_from:
        return False, (
            f"clauses are blocked for {config.clause_block_hours}h before kick-off "
            f"(since {blocked_from:%d/%m %H:%M})"
        )
    return True, ""


# ---------------------------------------------------------------------------
# Solvency
#
# A negative balance is not a soft warning. A squad in the red when the
# matchday opens scores zero for the week, however good the eleven is — which
# makes "will this still be solvent at kick-off?" a precondition on every
# purchase, not a footnote.
# ---------------------------------------------------------------------------


def projected_cash(cash: Euros, spending: Euros = 0, proceeds: Euros = 0) -> Euros:
    """The balance left after a set of operations settles."""
    return cash - spending + proceeds


def will_score(projected: Euros, *, reserve: Euros = 0) -> bool:
    """Whether a squad holding `projected` euros at kick-off scores at all."""
    return projected >= reserve


def shortfall(projected: Euros, *, reserve: Euros = 0) -> Euros:
    """How much has to be raised before kick-off to score at all. Zero when solvent."""
    return max(0, reserve - projected)


__all__ = [
    "CLAUSE_LOCK",
    "CLAUSE_LOWERING_LOCK",
    "CLAUSE_RAISE_FACTOR",
    "can_pay_clause",
    "clause_block_begins",
    "clause_premium",
    "clause_reopens_at",
    "cost_to_raise_clause",
    "effective_clause",
    "euros_per_average_point",
    "exposure_deadline",
    "is_clause_open",
    "is_dead_capital",
    "is_lineup_locked",
    "lineup_deadline",
    "passes_squad_role_filter",
    "projected_cash",
    "shortfall",
    "signing_deadline",
    "upgrade_gain",
    "will_score",
]
