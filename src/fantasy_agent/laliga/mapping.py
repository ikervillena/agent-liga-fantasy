"""Raw API payloads to domain objects.

Every assumption about the shape of LaLiga's JSON is confined to this file, so
when they rename a field — and they renamed most of them between 25/26 and
26/27 — there is exactly one place to fix and one set of tests to run.

Lookups are tolerant by design: `pick` tries several spellings and falls back
rather than raising. A single renamed field should degrade one attribute, not
take down the run that was going to shield an exposed player.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..models import (
    Fixture,
    Matchday,
    Offer,
    OwnedPlayer,
    Player,
    PlayerStatus,
    Position,
    Team,
)


def pick(source: Any, *names: str, default: Any = None) -> Any:
    if not isinstance(source, dict):
        return default
    for name in names:
        value = source.get(name)
        if value is not None:
            return value
    return default


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def as_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_status(value: Any) -> PlayerStatus:
    try:
        return PlayerStatus(str(value))
    except ValueError:
        return PlayerStatus.UNKNOWN


def to_player(raw: dict[str, Any]) -> Player:
    """A competition-wide player entry."""
    club = pick(raw, "team", default={}) or {}
    weeks = {
        as_int(pick(w, "weekNumber")): as_int(pick(w, "points"))
        for w in (pick(raw, "weekPoints", default=[]) or [])
        if isinstance(w, dict)
    }
    return Player(
        id=str(pick(raw, "id", default="")),
        name=str(pick(raw, "nickname", "name", default="?")),
        position=Position.from_api(as_int(pick(raw, "positionId"))),
        club_id=str(pick(raw, "teamId", default=pick(club, "id", default=""))),
        club=str(pick(club, "name", "shortName", default="")),
        market_value=as_int(pick(raw, "marketValue", "value")),
        total_points=as_int(pick(raw, "points")),
        average_points=round(as_float(pick(raw, "averagePoints")), 2),
        status=to_status(pick(raw, "playerStatus", default="unknown")),
        points_by_matchday=weeks,
    )


def to_owned_player(raw: dict[str, Any], team_id: str, manager: str) -> OwnedPlayer:
    """A squad entry, which nests the player under `playerMaster`.

    The clause we store is whatever the API reports. Turning that into the price
    a rival would pay today is `rules.effective_clause`'s job, not this file's:
    mapping records facts, rules interpret them.
    """
    inner = pick(raw, "playerMaster", "player", default=raw) or raw
    return OwnedPlayer(
        player=to_player(inner),
        team_id=team_id,
        manager=manager,
        player_team_id=str(pick(raw, "id", "playerTeamId", default="")),
        buyout_clause=as_int(pick(raw, "buyoutClause", "buyoutClauseValue")),
        clause_locked_until=as_datetime(
            pick(raw, "buyoutClauseLockedEndTime", "buyoutClauseLockedEndDate")
        ),
        is_shielded=bool(pick(raw, "isShielded", "shield", default=False)),
    )


def to_team(row: dict[str, Any], squad: list[dict[str, Any]]) -> Team:
    """One row of the standings plus the squad fetched for it."""
    inner = pick(row, "team", default=row) or row
    team_id = str(pick(inner, "id", "teamId", default=""))
    manager_raw = pick(inner, "manager", default={})
    manager = (
        str(pick(manager_raw, "managerName", "name", default=""))
        if isinstance(manager_raw, dict)
        else str(manager_raw)
    ) or "?"
    return Team(
        id=team_id,
        manager=manager,
        rank=as_int(pick(row, "position", "rank")),
        points=as_int(pick(row, "points")),
        squad=tuple(to_owned_player(p, team_id, manager) for p in squad if isinstance(p, dict)),
    )


def squad_entries(payload: Any) -> list[dict[str, Any]]:
    """Squad payloads have arrived as a bare list and as a wrapped object."""
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    entries = pick(payload, "players", "playerTeams", default=[]) or []
    return [p for p in entries if isinstance(p, dict)]


def to_matchday(raw: Any) -> Matchday | None:
    if not isinstance(raw, dict):
        return None
    return Matchday(
        number=as_int(pick(raw, "weekNumber")),
        is_live=bool(pick(raw, "isLive", default=False)),
        opens_at=as_datetime(pick(raw, "openingWeekDate")),
        closes_at=as_datetime(pick(raw, "closingWeekDate")),
    )


def to_fixtures(raw: Any, matchday: int) -> list[Fixture]:
    if not isinstance(raw, list):
        return []
    fixtures = []
    for match in raw:
        kickoff = as_datetime(pick(match, "matchDate", "date", "time"))
        if kickoff is None:
            continue
        fixtures.append(
            Fixture(
                matchday=matchday,
                kickoff=kickoff,
                home_club_id=str(pick(match, "localId", default="")),
                away_club_id=str(pick(match, "visitorId", default="")),
            )
        )
    return fixtures


def to_offers(raw: Any, market_id: str, player_name: str) -> list[Offer]:
    if not isinstance(raw, list):
        return []
    return [
        Offer(
            offer_id=str(pick(o, "id", "offerId", default="")),
            market_id=market_id,
            player_name=player_name,
            amount=as_int(pick(o, "money", "amount")),
        )
        for o in raw
        if isinstance(o, dict) and as_int(pick(o, "money", "amount")) > 0
    ]


__all__ = [
    "as_datetime",
    "as_float",
    "as_int",
    "pick",
    "squad_entries",
    "to_fixtures",
    "to_matchday",
    "to_offers",
    "to_owned_player",
    "to_player",
    "to_team",
]
