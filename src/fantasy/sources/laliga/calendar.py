"""The fixture list, and the deadline that actually governs a decision.

`week/current` answers "which matchday is running", which is not the same
question as "by when does this have to be done". Once a matchday has kicked
off, its own deadline is behind us and everything being decided now is for the
*next* one — whose opening instant only the calendar knows.

The distinction is not academic. Between matchday 7 and matchday 8 of this
season there are three weeks, because of an international break. An agent that
believes the deadline has passed will refuse to consider a signing for
twenty-two days; one that knows the real date can see that a squad has three
weeks to go into the red on an appreciating player and climb back out before it
costs a single point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fantasy.domain.models import Fixture, Matchday
from fantasy.sources.laliga.client import ApiError, FantasyClient
from fantasy.sources.mapping import as_datetime, pick


def fixtures_for(client: FantasyClient, number: int) -> list[Fixture]:
    """Every fixture in a matchday. Empty when the calendar is not published."""
    try:
        payload = client.calendar(number)
    except ApiError:
        return []
    return parse_fixtures(payload, number)


def parse_fixtures(payload: Any, number: int) -> list[Fixture]:
    rows = payload if isinstance(payload, list) else (payload or {}).get("data") or []
    found: list[Fixture] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        kickoff = as_datetime(pick(row, "matchDate", "date", "time"))
        if kickoff is None:
            continue
        found.append(
            Fixture(
                matchday=number,
                kickoff=kickoff,
                home_club_id=str(pick(row, "localId", default="")),
                away_club_id=str(pick(row, "visitorId", default="")),
            )
        )
    return found


def matchday_from(fixtures: list[Fixture], number: int) -> Matchday | None:
    """A matchday whose `opens_at` is its earliest kick-off.

    Earliest rather than nominal: the fixture list is not in chronological
    order, and it is the first whistle anywhere that freezes the squad.
    """
    if not fixtures:
        return None
    kickoffs = sorted(f.kickoff for f in fixtures)
    return Matchday(number=number, opens_at=kickoffs[0], closes_at=kickoffs[-1])


def next_matchday(client: FantasyClient, current: Matchday | None) -> Matchday | None:
    """The matchday a decision taken now is actually for."""
    if current is None:
        return None
    return matchday_from(fixtures_for(client, current.number + 1), current.number + 1)


def governing_deadline(
    current: Matchday | None, upcoming: Matchday | None, now: datetime
) -> datetime | None:
    """The instant that constrains a decision being taken right now.

    While the current matchday is still ahead, that is the wall. Once it has
    started, its squad is frozen and the next one is what matters.
    """
    if current is not None and current.opens_at is not None and now < current.opens_at:
        return current.opens_at
    return upcoming.opens_at if upcoming else None


__all__ = [
    "fixtures_for",
    "governing_deadline",
    "matchday_from",
    "next_matchday",
    "parse_fixtures",
]
