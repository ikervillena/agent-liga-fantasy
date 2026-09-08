"""Shared fixtures. Everything here is built by hand, never fetched.

The point of the domain/adapter split is that the interesting logic can be
exercised without a network, so no test in this suite makes a request.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fantasy_agent.models import (
    LeagueState,
    OwnedPlayer,
    Player,
    PlayerStatus,
    Position,
    SquadRole,
    Team,
)

NOW = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def make_player(
    player_id: str,
    name: str,
    position: Position,
    *,
    value: int = 10_000_000,
    average: float = 6.0,
    status: PlayerStatus = PlayerStatus.OK,
    role: SquadRole = SquadRole.KEY,
) -> Player:
    return Player(
        id=player_id,
        name=name,
        position=position,
        club_id="1",
        market_value=value,
        average_points=average,
        status=status,
        role=role,
    )


def make_owned(
    player: Player,
    *,
    manager: str = "iker",
    team_id: str = "mine",
    clause: int | None = None,
    locked_until: datetime | None = None,
) -> OwnedPlayer:
    return OwnedPlayer(
        player=player,
        team_id=team_id,
        manager=manager,
        player_team_id=f"pt-{player.id}",
        buyout_clause=player.market_value if clause is None else clause,
        clause_locked_until=locked_until,
    )


@pytest.fixture
def now() -> datetime:
    return NOW


@pytest.fixture
def squad() -> tuple[OwnedPlayer, ...]:
    """A legal 4-3-3 with a clear weakest link in each line."""
    spec = [
        ("1", "Keeper", Position.GOALKEEPER, 5.0),
        ("2", "Back A", Position.DEFENDER, 7.0),
        ("3", "Back B", Position.DEFENDER, 6.0),
        ("4", "Back C", Position.DEFENDER, 4.0),
        ("5", "Back D", Position.DEFENDER, 3.0),
        ("6", "Mid A", Position.MIDFIELDER, 8.0),
        ("7", "Mid B", Position.MIDFIELDER, 7.0),
        ("8", "Mid C", Position.MIDFIELDER, 2.0),
        ("9", "Fwd A", Position.FORWARD, 10.0),
        ("10", "Fwd B", Position.FORWARD, 6.0),
        ("11", "Fwd C", Position.FORWARD, 5.0),
    ]
    return tuple(
        make_owned(make_player(pid, name, pos, average=avg)) for pid, name, pos, avg in spec
    )


@pytest.fixture
def league(squad: tuple[OwnedPlayer, ...]) -> LeagueState:
    mine = Team(id="mine", manager="iker", rank=3, points=128, squad=squad)
    rival_player = make_player("99", "Star", Position.MIDFIELDER, value=20_000_000, average=9.0)
    rival = Team(
        id="theirs",
        manager="rival",
        rank=1,
        points=147,
        squad=(
            make_owned(
                rival_player,
                manager="rival",
                team_id="theirs",
                locked_until=NOW + timedelta(days=2),
            ),
        ),
    )
    return LeagueState(
        fetched_at=NOW,
        league_id="L",
        my_team_id="mine",
        cash=30_000_000,
        teams=(rival, mine),
    )
