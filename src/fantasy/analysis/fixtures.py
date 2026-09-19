"""Who a player faces next.

`objective.fixture_lookahead` sat in the policy from the beginning and was read
by nothing: the fixtures were fetched on every sync and then ignored. This is
what makes it mean something.

What is deliberately *not* here is a difficulty model. The obvious move is to
score each opponent — by squad value, by league position, by some hand-tuned
table — and fold that into the ranking. It would be a worse answer. Any such
table is a guess about football that goes stale the week a side changes
manager, and the judgment layer already knows what Barcelona away means without
being told. So this resolves the fixtures and says who, when and where; the
weighing happens where the football knowledge is.
"""

from __future__ import annotations

from fantasy.domain.models import LeagueState


class Opponent:
    """One upcoming match, from a given club's point of view."""

    __slots__ = ("at_home", "matchday", "name")

    def __init__(self, matchday: int, name: str, *, at_home: bool) -> None:
        self.matchday = matchday
        self.name = name
        self.at_home = at_home

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Opponent(J{self.matchday}, {self.name}, {'H' if self.at_home else 'A'})"

    def describe(self) -> str:
        return f"J{self.matchday} {'vs' if self.at_home else 'en'} {self.name}"


def club_names(state: LeagueState) -> dict[str, str]:
    """Club id to club name, learned from the players we already hold.

    The fixture list names clubs by id only. Every owned player carries both,
    so the lookup comes free rather than costing another request.
    """
    names: dict[str, str] = {}
    for owned in state.owned_players:
        player = owned.player
        if player.club_id and player.club:
            names.setdefault(player.club_id, player.club)
    return names


def next_opponents(state: LeagueState, club_id: str, *, count: int = 3) -> list[Opponent]:
    """The next `count` fixtures for a club, soonest first.

    Only fixtures ahead of the current matchday: a run of hard games matters
    for what a player is about to do, not for what he already did.
    """
    if not club_id:
        return []

    from_matchday = state.matchday.number if state.matchday else 0
    names = club_names(state)

    upcoming = sorted(
        (f for f in state.fixtures if f.matchday > from_matchday),
        key=lambda f: (f.matchday, f.kickoff),
    )

    found: list[Opponent] = []
    for fixture in upcoming:
        if fixture.home_club_id == club_id:
            rival, home = fixture.away_club_id, True
        elif fixture.away_club_id == club_id:
            rival, home = fixture.home_club_id, False
        else:
            continue
        found.append(Opponent(fixture.matchday, names.get(rival, f"equipo {rival}"), at_home=home))
        if len(found) >= count:
            break
    return found


def describe_run(state: LeagueState, club_id: str, *, count: int = 3) -> str:
    """The next few fixtures as one readable line, or empty when unknown."""
    return " · ".join(o.describe() for o in next_opponents(state, club_id, count=count))


__all__ = ["Opponent", "club_names", "describe_run", "next_opponents"]
