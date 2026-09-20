"""What the briefing actually shows the model.

The agent's advice was generic for a reason that had nothing to do with the
model: the briefing gave it a hundred and forty players sorted by their owner's
name, with our own fourteen scattered among them in identical formatting, and
never mentioned whether any of them was injured. No amount of prompting fixes
a briefing that cannot express the answer.

These tests pin the three facts that were missing, because each of them was
absent for weeks without a single test failing.
"""

from __future__ import annotations

from datetime import timedelta

from fantasy.agent.ask import league_digest
from fantasy.domain.models import LeagueState, PlayerStatus, Position, SquadRole, Team
from fantasy.storage.values import ValueCache

from .conftest import NOW, make_owned, make_player


def league() -> LeagueState:
    """One of ours, one rival worth signing, one rival who is noise."""
    mine = make_owned(
        make_player("1", "Nuestro", Position.DEFENDER, value=2_000_000, average=2.3),
        manager="iker",
        team_id="mine",
    )
    rival = make_owned(
        make_player("2", "Estrella", Position.FORWARD, value=40_000_000, average=8.0),
        manager="rival",
        team_id="theirs",
    )
    noise = make_owned(
        make_player(
            "3",
            "Suplente",
            Position.MIDFIELDER,
            value=400_000,
            average=0.5,
            role=SquadRole.BENCH,
        ),
        manager="rival",
        team_id="theirs",
    )
    return LeagueState(
        league_id="L",
        my_team_id="mine",
        fetched_at=NOW,
        cash=1_000_000,
        teams=(
            Team(id="mine", manager="iker", rank=1, squad=(mine,)),
            Team(id="theirs", manager="rival", rank=2, squad=(rival, noise)),
        ),
    )


def with_squads(state: LeagueState, mine: tuple, theirs: tuple) -> LeagueState:
    """Rebuild the state with replaced squads — the teams own the players."""
    return state.model_copy(
        update={
            "teams": (
                state.teams[0].model_copy(update={"squad": mine}),
                state.teams[1].model_copy(update={"squad": theirs}),
            )
        }
    )


def digest() -> str:
    return league_digest(league(), ValueCache(), now=NOW)


def test_our_squad_is_its_own_section() -> None:
    """Ours must be separable from theirs by looking, not by parsing a column.

    They used to share one table under a heading that said "your squad", so a
    question like "what am I short of?" had no answer available in the text.
    """
    body = digest()
    ours = body.index("## TU PLANTILLA")
    theirs = body.index("## CLAUSULAS ALCANZABLES")
    assert ours < theirs
    assert "Nuestro" in body[ours:theirs]
    assert "Estrella" not in body[ours:theirs]


def test_our_clause_is_framed_as_exposure() -> None:
    """For a player we hold, the clause is what a rival pays to take him."""
    assert "te lo quitan por" in digest()


def test_rivals_are_ordered_by_average_not_by_owner() -> None:
    """A signing question is asked in order of who is good, not of who owns him."""
    body = digest()
    section = body[body.index("## CLAUSULAS ALCANZABLES") :]
    assert section.index("Estrella") < section.index("Resto de la liga")


def test_a_bench_rival_below_the_floor_drops_to_the_short_row() -> None:
    """He cannot be the answer to a signing question, so he does not pay for a full row."""
    body = digest()
    assert "Suplente" in body
    assert "Suplente" in body[body.index("## Resto de la liga") :]


def test_availability_reaches_the_briefing() -> None:
    """An injury was invisible, so recommending an injured player was inevitable."""
    state = league()
    ours = state.teams[0].squad[0]
    hurt = ours.model_copy(
        update={"player": ours.player.model_copy(update={"status": PlayerStatus.INJURED})}
    )
    body = league_digest(with_squads(state, (hurt,), state.teams[1].squad), ValueCache(), now=NOW)
    assert "LESIONADO" in body


def test_the_average_is_reported_with_the_matchdays_behind_it() -> None:
    """Six a game over two appearances and over seven are opposite decisions."""
    assert "pts(" in digest()


def test_matchdays_are_recovered_when_the_api_withholds_them() -> None:
    """`weekPoints` is absent on squad entries, so every player we hold read as zero.

    The total and the average are both present, so the count divides out.
    """
    player = make_player("9", "Alguien", Position.FORWARD, average=7.5).model_copy(
        update={"total_points": 45}
    )
    assert player.matchdays_played == 6


def test_a_player_who_has_not_scored_reports_no_matchdays() -> None:
    """Dividing by a zero average must not raise, and must not invent a count."""
    player = make_player("9", "Nadie", Position.FORWARD, average=0.0)
    assert player.matchdays_played == 0


def test_a_locked_rival_stays_out_of_the_reachable_table() -> None:
    """Beyond the window he cannot be signed in any decision taken now."""
    state = league()
    star, noise = state.teams[1].squad
    locked = star.model_copy(update={"clause_locked_until": NOW + timedelta(days=30)})
    body = league_digest(
        with_squads(state, state.teams[0].squad, (locked, noise)), ValueCache(), now=NOW
    )
    reachable = body[body.index("## CLAUSULAS ALCANZABLES") : body.index("## Resto de la liga")]
    assert "Estrella" not in reachable
