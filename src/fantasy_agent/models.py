"""Domain types.

These are the vocabulary the rest of the codebase speaks. They know nothing
about HTTP, Telegram or files: the adapters in `laliga/` and `intel/` map
whatever the outside world returns onto these, and everything downstream works
against them. That boundary is what makes the interesting logic testable
without a network.

Money is always euros as an integer. The game deals in whole euros and floats
would eventually cost us a cent on a comparison that decides a signing.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

Euros = int


class Position(StrEnum):
    GOALKEEPER = "GK"
    DEFENDER = "DF"
    MIDFIELDER = "MF"
    FORWARD = "FW"
    COACH = "CO"

    @classmethod
    def from_api(cls, position_id: int | str) -> Position:
        return _POSITION_BY_ID.get(int(position_id), cls.COACH)


_POSITION_BY_ID: dict[int, Position] = {
    1: Position.GOALKEEPER,
    2: Position.DEFENDER,
    3: Position.MIDFIELDER,
    4: Position.FORWARD,
    5: Position.COACH,
}


class PlayerStatus(StrEnum):
    """Availability as LaLiga reports it.

    Anything other than OK means the player cannot be relied on for the next
    matchday, and OUT_OF_LEAGUE means he has left the competition entirely and
    will never score again — dead capital that has to be liquidated.
    """

    OK = "ok"
    DOUBTFUL = "doubtful"
    INJURED = "injured"
    SUSPENDED = "suspended"
    OUT_OF_LEAGUE = "out_of_league"
    UNKNOWN = "unknown"

    @property
    def is_available(self) -> bool:
        return self is PlayerStatus.OK


class SquadRole(StrEnum):
    """How much a player actually plays for his club.

    Not from the game API — this comes from scouting sources. It is the single
    most valuable filter we have: a high scoring average earned in three
    substitute appearances is noise, and buying it has burned us before.
    """

    KEY = "key"
    IMPORTANT = "important"
    ROTATION = "rotation"
    IMPACT_SUB = "impact_sub"
    BENCH = "bench"
    UNKNOWN = "unknown"

    @property
    def is_starter(self) -> bool:
        return self in (SquadRole.KEY, SquadRole.IMPORTANT)


class Player(BaseModel):
    """A player as the competition sees him, independent of who owns him."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    position: Position
    club_id: str
    club: str = ""
    market_value: Euros = 0
    total_points: int = 0
    average_points: float = 0.0
    status: PlayerStatus = PlayerStatus.UNKNOWN
    points_by_matchday: dict[int, int] = Field(default_factory=dict)
    role: SquadRole = SquadRole.UNKNOWN

    @property
    def matchdays_played(self) -> int:
        return len(self.points_by_matchday)


class OwnedPlayer(BaseModel):
    """A player inside somebody's squad, with his buyout clause attached.

    `clause_locked_until` is the instant the clause becomes payable by rivals.
    It is set to fourteen days after the current owner signed him, and it is
    the axis the whole planner turns on: every opportunity in this game has a
    known opening time.
    """

    model_config = ConfigDict(frozen=True)

    player: Player
    team_id: str
    manager: str
    player_team_id: str = ""
    buyout_clause: Euros = 0
    clause_locked_until: datetime | None = None
    is_shielded: bool = False

    @property
    def id(self) -> str:
        return self.player.id

    @property
    def name(self) -> str:
        return self.player.name


class Team(BaseModel):
    """A rival manager's team, as it stands in the league table."""

    model_config = ConfigDict(frozen=True)

    id: str
    manager: str
    rank: int = 0
    points: int = 0
    squad: tuple[OwnedPlayer, ...] = ()
    cash: Euros | None = None  # the API only ever reveals our own balance

    @property
    def squad_value(self) -> Euros:
        return sum(p.player.market_value for p in self.squad)

    @property
    def total_clauses(self) -> Euros:
        return sum(p.buyout_clause for p in self.squad)


class Matchday(BaseModel):
    model_config = ConfigDict(frozen=True)

    number: int
    is_live: bool = False
    opens_at: datetime | None = None
    closes_at: datetime | None = None


class Fixture(BaseModel):
    model_config = ConfigDict(frozen=True)

    matchday: int
    kickoff: datetime
    home_club_id: str
    away_club_id: str


class MarketListing(BaseModel):
    """A player on the daily free-agent market, or one a rival has put up."""

    model_config = ConfigDict(frozen=True)

    market_id: str
    player: Player
    asking_price: Euros
    expires_at: datetime | None = None
    seller: str | None = None


class Offer(BaseModel):
    """A bid a rival has placed on one of our listed players."""

    model_config = ConfigDict(frozen=True)

    offer_id: str
    market_id: str
    player_name: str
    amount: Euros


class LeagueState(BaseModel):
    """Everything the agent knows about the league at one instant.

    This is the input to planning. It is assembled once per run and never
    mutated, so a plan can always be traced back to the exact picture that
    produced it.
    """

    model_config = ConfigDict(frozen=True)

    fetched_at: datetime
    league_id: str
    my_team_id: str
    matchday: Matchday | None = None
    cash: Euros = 0
    teams: tuple[Team, ...] = ()
    market: tuple[MarketListing, ...] = ()
    offers: tuple[Offer, ...] = ()
    fixtures: tuple[Fixture, ...] = ()

    @property
    def my_team(self) -> Team | None:
        return next((t for t in self.teams if t.id == self.my_team_id), None)

    @property
    def owned_players(self) -> tuple[OwnedPlayer, ...]:
        return tuple(p for t in self.teams for p in t.squad)

    def rivals(self) -> tuple[Team, ...]:
        return tuple(t for t in self.teams if t.id != self.my_team_id)


__all__ = [
    "Euros",
    "Fixture",
    "LeagueState",
    "MarketListing",
    "Matchday",
    "Offer",
    "OwnedPlayer",
    "Player",
    "PlayerStatus",
    "Position",
    "SquadRole",
    "Team",
]
