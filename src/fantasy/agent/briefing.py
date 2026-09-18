"""Assembling what the model is shown.

The old planner's problem was not that it lacked data — it is that it ranked
candidates by one flat number, the season scoring average, and then reported
whatever came out. Two consequences: a player whose average is depressed by an
injury he has recovered from was filtered out before anything could reason
about him, and appreciation was invisible.

So a briefing is assembled per candidate: the operation, what it costs, the
player's role at his club, where his price is going, and how his squad already
looks. Small on purpose. The candidate list has already been narrowed by the
rules and the budget, so this is tens of lines rather than the seven hundred
players in the competition, and it stays inside a cached prefix.

Rendered as text rather than JSON. The content is a table of facts and reads
better as one — and it keeps the token count low enough that the whole briefing
can sit under a cache breakpoint.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from fantasy.analysis.valuation import Trend, Valuation
from fantasy.domain.intents import Intent
from fantasy.domain.models import LeagueState, OwnedPlayer, SquadRole
from fantasy.domain.policy import Policy
from fantasy.domain.rules import lineup_deadline

#: How the trend reads to the model. Spanish, because the model answers in it.
_TREND_ES: dict[Trend, str] = {
    Trend.RISING: "subiendo",
    Trend.FALLING: "bajando",
    Trend.FLAT: "plano",
    Trend.UNKNOWN: "sin datos",
}

_ROLE_ES: dict[SquadRole, str] = {
    SquadRole.KEY: "clave",
    SquadRole.IMPORTANT: "importante",
    SquadRole.ROTATION: "rotacion",
    SquadRole.IMPACT_SUB: "revulsivo",
    SquadRole.BENCH: "suplente",
    SquadRole.UNKNOWN: "desconocido",
}


class Candidate(BaseModel):
    """One legal, affordable operation, with the evidence for judging it."""

    model_config = ConfigDict(frozen=True)

    intent: Intent
    role: SquadRole = SquadRole.UNKNOWN
    valuation: Valuation | None = None

    @property
    def key(self) -> str:
        return self.intent.key


def millions(amount: float) -> str:
    """Spanish convention: comma decimal, two places, in millions."""
    return f"{amount / 1e6:.2f}".replace(".", ",") + " M"


def render(
    state: LeagueState,
    policy: Policy,
    candidates: list[Candidate],
    *,
    now: datetime,
    already_said: list[str] | None = None,
) -> str:
    """The user-turn text for one decision moment."""
    parts = [
        _situation(state, policy, now),
        _squad(state),
        _candidates(candidates),
    ]
    if already_said:
        parts.append(_already_said(already_said))
    return "\n\n".join(p for p in parts if p)


def _situation(state: LeagueState, policy: Policy, now: datetime) -> str:
    lines = ["## Situación", f"Ahora: {now:%A %d/%m %H:%M}"]

    me = state.my_team
    if me is not None:
        lines.append(f"Vas {me.rank}º con {me.points} puntos.")
        if not me.can_punctuate:
            lines.append(
                "ATENCIÓN: el equipo NO puntúa ahora mismo (saldo negativo). "
                "Si sigue así al primer partido, la jornada entera vale cero."
            )
    lines.append(f"Caja: {millions(state.cash)}")

    deadline = lineup_deadline(state.matchday)
    if deadline is not None and state.matchday is not None:
        hours = (deadline - now).total_seconds() / 3600
        when = f"en {hours:.0f} h" if hours > 0 else "ya cerrada"
        lines.append(f"Jornada {state.matchday.number}: cierra {deadline:%d/%m %H:%M} ({when}).")

    if not state.config.captain and not state.config.bench:
        lines.append(
            "Esta liga NO tiene capitán, banquillo, formaciones libres ni entrenador. "
            "No los menciones."
        )
    lines.append(
        f"Límites: máximo {millions(policy.limits.max_per_operation)} por operación, "
        f"{millions(policy.limits.max_per_run)} por ejecución."
    )
    return "\n".join(lines)


def _squad(state: LeagueState) -> str:
    me = state.my_team
    if me is None or not me.squad:
        return ""

    lines = ["## Tu plantilla", "Posición | Jugador | Media | Valor | Cláusula"]
    for player in sorted(me.squad, key=_squad_order):
        lines.append(
            f"{player.player.position.value} | {player.name} | "
            f"{player.player.average_points:.2f} | "
            f"{millions(player.player.market_value)} | "
            f"{millions(player.buyout_clause)}"
        )
    lines.append(
        "Mira dónde estás fuerte y dónde flojo: un cuarto delantero bueno vale "
        "menos que un defensa que te falta."
    )
    return "\n".join(lines)


def _squad_order(player: OwnedPlayer) -> tuple[str, float]:
    return (player.player.position.value, -player.player.average_points)


def _candidates(candidates: list[Candidate]) -> str:
    if not candidates:
        return "## Candidatos\nNinguno hoy."

    lines = ["## Candidatos", "Todos son legales y caben en el presupuesto. Elige."]
    for candidate in candidates:
        lines.append("")
        lines.append(f"### {candidate.key}")
        lines.append(_candidate_body(candidate))
    return "\n".join(lines)


def _candidate_body(candidate: Candidate) -> str:
    intent = candidate.intent
    rows = [
        f"Operación: {intent.kind.value} · {intent.player_name or intent.market_id}",
        f"Importe: {millions(intent.amount)}",
        f"Rol en su club: {_ROLE_ES[candidate.role]}",
    ]
    if intent.expected_gain:
        rows.append(f"Gana {intent.expected_gain:.2f} de media sobre quien desplaza.")

    value = candidate.valuation
    if value is not None and value.days_observed:
        rows.append(
            f"Valor {_TREND_ES[value.trend]}: {millions(value.velocity)}/día, "
            f"{millions(value.delta_7d)} en 7 días, {millions(value.delta_30d)} en 30. "
            f"({value.days_observed} días observados)"
        )
        if value.acceleration > 0 and value.trend is Trend.RISING:
            rows.append("La subida se está acelerando.")
    if intent.anchor is not None:
        rows.append(f"Ventana: {intent.anchor:%d/%m %H:%M}")
    return "\n".join(rows)


def _already_said(keys: list[str]) -> str:
    return (
        "## Ya comunicado\n"
        "Esto ya se le dijo al manager y no ha cambiado. NO lo repitas:\n"
        + "\n".join(f"- {key}" for key in keys)
    )


__all__ = ["Candidate", "millions", "render"]
