"""The daily brief.

One message a day that answers four questions in the order a manager cares
about them: where do I stand, what moved, what is coming, and what needs me.

Written to be read on a phone: short lines, money in millions with comma
decimals, no tables that wrap. Anything longer than a screen is a sign the
agent is reporting noise rather than signal.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .approvals import Approval, ApprovalState
from .intents import Intent
from .models import LeagueState, OwnedPlayer
from .notifier import millions
from .planner import HORIZON, best_eleven
from .rules import clause_premium, effective_clause

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def when(moment: datetime) -> str:
    return f"{DAYS[moment.weekday()]} {moment:%d %H:%M}"


def compose(
    state: LeagueState,
    previous: LeagueState | None,
    intents: list[Intent],
    approvals: list[Approval],
    now: datetime | None = None,
) -> str:
    now = now or state.fetched_at
    lines: list[str] = []

    lines.extend(_standing(state, now))
    lines.extend(_movements(state, previous))
    lines.extend(_windows(state, now))
    lines.extend(_exposure(state, now))
    lines.extend(_offers(state))
    lines.extend(_pending(approvals))
    lines.extend(_proposals(intents, approvals))

    return "\n".join(lines).strip()


def _standing(state: LeagueState, now: datetime) -> list[str]:
    lines = [f"<b>Daily brief · {now:%d/%m}</b>"]
    me = state.my_team
    if me and state.teams:
        leader = state.teams[0]
        gap = leader.points - me.points
        position = f"{me.rank}." if me.rank else "-"
        behind = "level with the leader" if gap <= 0 else f"{gap} behind {leader.manager}"
        lines.append(f"{position} with {me.points} points · {behind}")
    lines.append(f"Cash: <b>{millions(state.cash)}</b>")
    if state.matchday and state.matchday.closes_at:
        lines.append(f"Matchday {state.matchday.number} closes {when(state.matchday.closes_at)}")
    return lines


def _movements(state: LeagueState, previous: LeagueState | None) -> list[str]:
    """What changed since the last snapshot: value swings and transfers."""
    if previous is None:
        return []

    before = {p.id: p for p in previous.owned_players}
    risers: list[tuple[OwnedPlayer, float]] = []
    moved: list[OwnedPlayer] = []

    for owned in state.owned_players:
        was = before.get(owned.id)
        if was is None:
            moved.append(owned)
            continue
        if was.manager != owned.manager:
            moved.append(owned)
        old_value = was.player.market_value
        if old_value and abs(owned.player.market_value - old_value) / old_value >= 0.05:
            risers.append((owned, (owned.player.market_value - old_value) / old_value))

    lines: list[str] = []
    if risers:
        lines.append("")
        lines.append("<b>Value moves</b>")
        risers.sort(key=lambda pair: abs(pair[1]), reverse=True)
        for owned, change in risers[:6]:
            arrow = "↑" if change > 0 else "↓"
            lines.append(
                f"{arrow} {owned.name} {change:+.0%} → {millions(owned.player.market_value)}"
                f" ({owned.manager})"
            )
    if moved:
        lines.append("")
        lines.append("<b>Changed hands</b>")
        for owned in moved[:6]:
            lines.append(f"· {owned.name} → {owned.manager}")
    return lines


def _windows(state: LeagueState, now: datetime) -> list[str]:
    """Rival players whose clause opens inside the horizon."""
    opening: list[tuple[datetime, OwnedPlayer]] = []
    for team in state.rivals():
        for owned in team.squad:
            if not owned.player.status.is_available or owned.player.average_points < 5.5:
                continue
            if clause_premium(owned.player.market_value, owned.buyout_clause) > 1.15:
                continue
            opens = owned.clause_locked_until or now
            if opens <= now + HORIZON:
                opening.append((max(opens, now), owned))

    if not opening:
        return []

    opening.sort(key=lambda pair: (pair[0], -pair[1].player.average_points))
    lines = ["", "<b>Clause windows this week</b>"]
    for opens, owned in opening[:10]:
        price = effective_clause(owned.player.market_value, owned.buyout_clause)
        premium = clause_premium(owned.player.market_value, owned.buyout_clause)
        label = "open now" if opens <= now else when(opens)
        lines.append(
            f"· <b>{owned.name}</b> {owned.player.position.value} · "
            f"avg {owned.player.average_points:.2f} · {millions(price)} · "
            f"x{premium:.2f} · {label} ({owned.manager})"
        )
    return lines


def _exposure(state: LeagueState, now: datetime) -> list[str]:
    """Our own players anyone could take at market price."""
    me = state.my_team
    if me is None:
        return []

    eleven = {p.id for p in best_eleven(me.squad)}
    at_risk = []
    for owned in me.squad:
        if clause_premium(owned.player.market_value, owned.buyout_clause) > 1.02:
            continue
        deadline = owned.clause_locked_until
        if deadline is not None and deadline > now + timedelta(days=3):
            continue
        at_risk.append((deadline, owned, owned.id in eleven))

    if not at_risk:
        return []

    lines = ["", "<b>Yours with no premium</b>"]
    for deadline, owned, starting in sorted(at_risk, key=lambda row: row[0] or now):
        state_label = (
            "exposed now" if deadline is None or deadline <= now else f"safe until {when(deadline)}"
        )
        clause = effective_clause(owned.player.market_value, owned.buyout_clause)
        mark = " ⚑" if starting else ""
        lines.append(
            f"· <b>{owned.name}</b>{mark} avg {owned.player.average_points:.2f} · "
            f"clause {millions(clause)} · {state_label}"
        )
    return lines


def _offers(state: LeagueState) -> list[str]:
    if not state.offers:
        return []
    lines = ["", "<b>Offers on your listings</b>"]
    for offer in state.offers:
        lines.append(f"· {offer.player_name}: {millions(offer.amount)}")
    return lines


def _pending(approvals: list[Approval]) -> list[str]:
    waiting = [a for a in approvals if a.state is ApprovalState.PENDING]
    if not waiting:
        return []
    lines = ["", "<b>Waiting on you</b>"]
    for approval in waiting:
        lines.append(f"· {approval.intent.describe()} · {when(approval.intent.execute_at)}")
    return lines


def _proposals(intents: list[Intent], approvals: list[Approval]) -> list[str]:
    known = {a.key for a in approvals}
    fresh = [i for i in intents if i.key not in known]
    if not fresh:
        return ["", "<i>Nothing new to propose today.</i>"]

    lines = ["", "<b>Proposed</b>"]
    for intent in fresh[:6]:
        per_point = (
            f" · {intent.euros_per_point / 1e6:.2f} M per point" if intent.expected_gain > 0 else ""
        )
        lines.append(f"· {intent.describe()} · {when(intent.execute_at)}{per_point}")
        lines.append(f"  <i>{intent.rationale}</i>")
    return lines


def ask_text(intent: Intent) -> str:
    """The message that accompanies the approve/reject buttons."""
    parts = [
        f"<b>{intent.describe()}</b>",
        f"Execute: {when(intent.execute_at)}",
        "",
        intent.rationale,
    ]
    if intent.expected_gain > 0:
        parts.append(
            f"Expected: {intent.expected_gain:+.2f} points of average, "
            f"{intent.euros_per_point / 1e6:.2f} M per point."
        )
    if intent.fallback:
        parts.append(f"If not: {intent.fallback}")
    return "\n".join(parts)


__all__ = ["ask_text", "compose", "when"]
