"""Perception: assembling a `LeagueState` from the API.

One round trip per team plus a handful of competition-wide calls, paced so we
stay a polite guest. Failures are contained per call — losing the fixture list
should not cost us the squad data that was about to shield an exposed player —
so anything that fails is logged and left empty rather than raised.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fantasy.domain.models import LeagueState, MarketListing, Offer, Player, Team
from fantasy.sources.laliga.calendar import matchday_from
from fantasy.sources.laliga.client import ApiError, FantasyClient
from fantasy.sources.mapping import (
    as_int,
    pick,
    squad_entries,
    to_fixtures,
    to_matchday,
    to_offers,
    to_team,
)
from fantasy.sources.scouting.roles import RoleBook


def _safe(label: str, call: Any, *args: Any, **kwargs: Any) -> Any:
    try:
        return call(*args, **kwargs)
    except (ApiError, OSError) as exc:
        print(f"warning: {label} failed ({exc})")
        return None


def _apply_roles(team: Team, roles: RoleBook) -> Team:
    """Attach scouting roles to every player in a squad."""
    enriched = tuple(
        owned.model_copy(
            update={
                "player": owned.player.model_copy(
                    update={"role": roles.role_of(owned.player.name, owned.player.id)}
                )
            }
        )
        for owned in team.squad
    )
    return team.model_copy(update={"squad": enriched})


def fetch_state(
    client: FantasyClient,
    league_id: str,
    team_id: str,
    roles: RoleBook,
) -> LeagueState:
    matchday_raw = _safe("current matchday", client.current_matchday)
    matchday = to_matchday(matchday_raw)

    standings = _safe("standings", client.standings, league_id) or []
    rows = (
        standings if isinstance(standings, list) else pick(standings, "standings", default=[]) or []
    )

    teams: list[Team] = []
    for row in rows:
        inner = pick(row, "team", default=row) or row
        this_id = str(pick(inner, "id", "teamId", default=""))
        if not this_id:
            continue
        squad_raw = _safe(f"squad {this_id}", client.team, league_id, this_id)
        teams.append(_apply_roles(to_team(row, squad_entries(squad_raw)), roles))
    teams.sort(key=lambda t: t.rank or 99)

    cash_raw = _safe("cash", client.cash, team_id) or {}
    cash = as_int(pick(cash_raw, "teamMoney", "money"))

    raw_market = _safe("market", client.market, league_id)
    market = _fetch_market(raw_market)
    # An offer is accepted against the *market* id, not the player's. They are
    # different identifiers and the only place that links them is the market
    # listing, so it is resolved here rather than guessed downstream.
    offers = _fetch_offers(client, league_id, teams, team_id, _market_ids(raw_market))

    # Whether the squad scores at all is the game's own verdict, and it lives
    # on the leagues endpoint rather than on the standings row.
    teams = _apply_scoring_status(teams, team_id, _can_punctuate(client, team_id))
    fixtures = _fetch_fixtures(client, matchday.number if matchday else 0)
    # Once the current matchday has started, the deadline that binds any new
    # decision belongs to the next one, and only the calendar knows when it is.
    upcoming = matchday_from(
        [f for f in fixtures if matchday and f.matchday == matchday.number + 1],
        matchday.number + 1 if matchday else 0,
    )

    return LeagueState(
        fetched_at=datetime.now(UTC),
        league_id=league_id,
        my_team_id=team_id,
        matchday=matchday,
        next_matchday=upcoming,
        cash=cash,
        teams=tuple(teams),
        market=tuple(market),
        offers=tuple(offers),
        fixtures=tuple(fixtures),
    )


def _can_punctuate(client: FantasyClient, team_id: str) -> bool:
    """The API's verdict on our own squad. Absent data is read optimistically:
    a false warning every run would train the manager to ignore a real one."""
    raw = _safe("leagues", client.leagues)
    entries = raw if isinstance(raw, list) else [raw]
    for entry in entries:
        team = pick(entry, "team", default={}) or {}
        if str(pick(team, "id", default="")) == team_id:
            return bool(pick(team, "canPunctuate", default=True))
    return True


def _apply_scoring_status(teams: list[Team], team_id: str, scores: bool) -> list[Team]:
    return [t.model_copy(update={"can_punctuate": scores}) if t.id == team_id else t for t in teams]


def _market_ids(raw: Any) -> dict[str, str]:
    """`playerTeamId` to the market id its listing carries."""
    if not isinstance(raw, list):
        return {}
    found: dict[str, str] = {}
    for row in raw:
        player_team = pick(row, "playerTeam", default={}) or {}
        ptid = str(pick(player_team, "playerTeamId", "id", default=""))
        market_id = str(pick(row, "id", default=""))
        if ptid and market_id:
            found[ptid] = market_id
    return found


def _fetch_market(raw: Any) -> list[MarketListing]:
    if not isinstance(raw, list):
        return []
    listings: list[MarketListing] = []
    for row in raw:
        inner = pick(row, "playerMaster", "player", default={}) or {}
        if not inner:
            continue
        from fantasy.sources.mapping import (  # local: avoids a cycle at import time
            as_datetime,
            to_player,
        )

        listings.append(
            MarketListing(
                market_id=str(pick(row, "id", "marketId", default="")),
                player=to_player(inner),
                asking_price=as_int(
                    pick(row, "salePrice", "price", default=pick(inner, "marketValue"))
                ),
                expires_at=as_datetime(pick(row, "expirationDate", "expiration")),
                seller=pick(pick(row, "discr", default={}), "manager")
                if isinstance(row, dict)
                else None,
            )
        )
    return listings


def _fetch_offers(
    client: FantasyClient,
    league_id: str,
    teams: list[Team],
    my_team_id: str,
    market_ids: dict[str, str],
) -> list[Offer]:
    """Bids rivals have placed on players we listed.

    Only our own squad is queried: a 404 here simply means that player is not
    on the market, which is the common case and not worth logging.
    """
    mine = next((t for t in teams if t.id == my_team_id), None)
    if mine is None:
        return []

    offers: list[Offer] = []
    for owned in mine.squad:
        if not owned.player_team_id:
            continue
        try:
            raw = client.offers_for(league_id, owned.player_team_id)
        except ApiError:
            continue
        # No market id means the player is not actually listed, so an offer on
        # him could not be accepted even if one were reported.
        market_id = market_ids.get(owned.player_team_id)
        if market_id:
            offers.extend(to_offers(raw, market_id, owned.name))
    return offers


def _fetch_fixtures(client: FantasyClient, current: int) -> list[Any]:
    """The next few matchdays, for fixture-weighted decisions."""
    if not current:
        return []
    fixtures = []
    for matchday in range(current, current + 4):
        raw = _safe(f"calendar {matchday}", client.calendar, matchday)
        fixtures.extend(to_fixtures(raw, matchday))
    return fixtures


def catalogue(client: FantasyClient) -> list[Player]:
    """Every player in the competition, owned or not.

    Public endpoint — this is what surfaces free agents, by subtracting the
    owned set from it.
    """
    from fantasy.sources.mapping import to_player

    raw = _safe("catalogue", client.players)
    if not isinstance(raw, list):
        return []
    return [to_player(row) for row in raw if isinstance(row, dict)]


__all__ = ["catalogue", "fetch_state"]
