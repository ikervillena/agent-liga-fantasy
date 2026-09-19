"""Answering a question the manager asks in his own words.

This is a different job from the scheduled proposals, and the difference is
what shapes the code. A proposal is the agent deciding what is worth raising,
so the candidate list is narrow and the answer is a structured selection. A
question is the manager deciding what matters — "is there a clausulazo worth
taking right now?", "who is going to appreciate over the international break?"
— and the agent cannot know in advance which players the answer turns on.

So the briefing here is the whole league rather than a shortlist: every owned
player with his clause, his lock, his role and where his price is going. It is
larger than the proposal briefing on purpose, and it is why the price histories
are cached rather than fetched on the spot.

The answer is free text, not a schema. Nothing here executes anything, so there
is nothing to validate a structure against — and forcing prose into a schema
would only make it worse to read.
"""

from __future__ import annotations

import os
from datetime import datetime

from anthropic import Anthropic

from fantasy.agent.advisor import AdvisorError, Effort
from fantasy.agent.briefing import millions
from fantasy.analysis.valuation import Trend, valuation
from fantasy.domain.models import LeagueState, OwnedPlayer, SquadRole
from fantasy.domain.rules import clause_premium, effective_clause, lineup_deadline
from fantasy.storage.values import ValueCache

MODEL = "claude-opus-5"

SYSTEM = """\
Eres el asesor de Iker en su liga privada de LaLiga Fantasy. Te escribe él
directamente para preguntarte algo concreto.

Responde en español de España, directo y sin adornos. Nada de saludos ni
despedidas. Vas al grano: primero la respuesta, después el porqué.

Reglas:

- Responde SOLO con los datos del informe. Si algo no está, dilo claramente en
  vez de suponerlo. Nunca te inventes un nombre, un precio ni una fecha.
- Cita cifras concretas. "Sube 380.000 al día y su cláusula está a x1,00" vale;
  "buena oportunidad" no vale nada.
- Si la respuesta es que no hay nada interesante, dilo y ya. No rellenes.
- Esta liga no tiene capitán, banquillo, formaciones libres ni entrenador: no
  los menciones.
- Iker decide. Tú recomiendas y explicas el riesgo, incluido el de quedarse en
  negativo: si empieza la jornada en rojos no puntúa esa jornada entera, así
  que una inversión que lo deje en negativo solo tiene sentido si da tiempo a
  volver a positivo antes del primer partido.
- Si te pregunta por algo que requiere datos que no tienes (prensa, lesiones de
  última hora, alineaciones probables), dilo en una línea en vez de fingir.

Extensión: lo que haga falta y ni una palabra más. Normalmente cuatro o cinco
líneas.
"""


def answer(
    question: str,
    state: LeagueState,
    values: ValueCache,
    *,
    now: datetime,
    client: Anthropic | None = None,
    effort: Effort = "high",
) -> str:
    """Answer one question against the current league."""
    brief = league_digest(state, values, now=now)
    api = client or Anthropic()
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()

    try:
        response = api.messages.create(
            model=MODEL,
            max_tokens=4000,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": f"{brief}\n\n## Pregunta de Iker\n{question}"}],
            extra_headers={"anthropic-workspace-id": workspace} if workspace else {},
        )
    except Exception as exc:
        raise AdvisorError(f"could not answer: {exc}") from exc

    if getattr(response, "stop_reason", None) == "refusal":
        raise AdvisorError("the model declined to answer")

    text = "\n".join(
        str(getattr(block, "text", ""))
        for block in response.content
        if getattr(block, "type", "") == "text"
    ).strip()
    if not text:
        raise AdvisorError("the answer was empty")
    return text


def league_digest(state: LeagueState, values: ValueCache, *, now: datetime) -> str:
    """Everything a question might turn on, in one compact table."""
    lines = [
        "# Estado de la liga",
        f"Ahora: {now:%A %d/%m %H:%M}",
        f"Tu caja: {millions(state.cash)}",
    ]

    me = state.my_team
    if me is not None:
        lines.append(f"Vas {me.rank}º con {me.points} puntos.")
        if not me.can_punctuate:
            lines.append("ATENCIÓN: ahora mismo NO puntúas (saldo negativo).")

    deadline = lineup_deadline(state.matchday)
    if deadline is not None and state.matchday is not None:
        hours = (deadline - now).total_seconds() / 3600
        remaining = f"quedan {hours:.0f} h" if hours > 0 else "ya cerrada"
        lines.append(
            f"Jornada {state.matchday.number}: cierra {deadline:%d/%m %H:%M} ({remaining})."
        )

    lines += ["", "## Clasificación", "Pos | Manager | Puntos | Valor plantilla"]
    for team in sorted(state.teams, key=lambda t: t.rank or 99):
        mine = " (TÚ)" if team.id == state.my_team_id else ""
        lines.append(
            f"{team.rank} | {team.manager}{mine} | {team.points} | {millions(team.squad_value)}"
        )

    lines += [
        "",
        "## Todos los jugadores con dueño",
        "Columnas: jugador · pos · dueño · media · valor · cláusula · prima · "
        "se abre · rol · tendencia de valor",
    ]
    for owned in sorted(state.owned_players, key=_ordering):
        lines.append(_player_row(owned, values, now=now, mine=owned.team_id == state.my_team_id))

    if state.market:
        lines += ["", "## Mercado libre ahora", "jugador · pos · valor · precio"]
        for listing in state.market:
            lines.append(
                f"{listing.player.name} · {listing.player.position.value} · "
                f"{millions(listing.player.market_value)} · {millions(listing.asking_price)}"
            )

    if state.offers:
        lines += ["", "## Ofertas que has recibido"]
        for offer in state.offers:
            lines.append(f"{offer.player_name}: {millions(offer.amount)}")

    return "\n".join(lines)


def _ordering(owned: OwnedPlayer) -> tuple[str, float]:
    return (owned.manager, -owned.player.average_points)


_TREND_ES = {
    Trend.RISING: "subiendo",
    Trend.FALLING: "bajando",
    Trend.FLAT: "plano",
    Trend.UNKNOWN: "?",
}

_ROLE_ES = {
    SquadRole.KEY: "clave",
    SquadRole.IMPORTANT: "importante",
    SquadRole.ROTATION: "rotacion",
    SquadRole.IMPACT_SUB: "revulsivo",
    SquadRole.BENCH: "suplente",
    SquadRole.UNKNOWN: "?",
}


def _player_row(owned: OwnedPlayer, values: ValueCache, *, now: datetime, mine: bool) -> str:
    player = owned.player
    clause = effective_clause(player.market_value, owned.buyout_clause)
    premium = clause_premium(player.market_value, owned.buyout_clause)

    if owned.is_shielded:
        window = "BLINDADO"
    elif owned.clause_locked_until is None or owned.clause_locked_until <= now:
        window = "ABIERTA"
    else:
        window = f"{owned.clause_locked_until:%d/%m %H:%M}"

    trend = "?"
    series = values.get(player.id)
    if series is not None and series.points:
        read = valuation(series)
        trend = (
            f"{_TREND_ES[read.trend]} {millions(read.velocity)}/dia, 7d {millions(read.delta_7d)}"
        )

    owner = f"{owned.manager}{' (TÚ)' if mine else ''}"
    return (
        f"{player.name} · {player.position.value} · {owner} · "
        f"{player.average_points:.2f} · {millions(player.market_value)} · "
        f"{millions(clause)} · x{premium:.2f} · {window} · "
        f"{_ROLE_ES.get(player.role, '?')} · {trend}"
    )


__all__ = ["MODEL", "SYSTEM", "answer", "league_digest"]
