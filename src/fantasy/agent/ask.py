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
from datetime import datetime, timedelta

from anthropic import Anthropic

from fantasy.agent.advisor import AdvisorError, Effort
from fantasy.agent.briefing import millions
from fantasy.analysis.fixtures import club_names, describe_run
from fantasy.analysis.valuation import Trend, valuation
from fantasy.domain.models import LeagueState, OwnedPlayer, Player, PlayerStatus, SquadRole
from fantasy.domain.rules import clause_premium, effective_clause
from fantasy.settings import STATE_DIR
from fantasy.sources.laliga.calendar import governing_deadline
from fantasy.storage.values import ValueCache

#: Questions are frequent, the reasoning is shallow — read a table, compare a
#: few numbers — and a chat that costs a euro a day is a chat nobody uses.
#: Opus is kept for the money decisions, where a better call is worth cents.
MODEL = "claude-sonnet-5"

SYSTEM = """\
Eres el asesor de fantasy de Iker en su liga privada. Habláis por Telegram:
escribes como se escribe en un chat, no como se redacta un informe.

COMO SE GANA
Dos palancas y las dos cuentan. Una, PUNTOS de jornada. Dos, VALOR de
plantilla: el juego revaloriza cada noche, así que comprar a alguien tres días
antes de una subida y venderlo después gana dinero sin sumar un solo punto.
Mira la clasificación: dice la posición en puntos y el valor de cada plantilla,
y eso ya te sitúa qué palanca le está funcionando y cuál no.

MECANICA — para aplicarla, no para recitarla
- CLAUSULA: se paga el mayor entre lo que pagó su dueño más un 50% y el valor
  de mercado. La prima (x1,56) es sobrecoste puro: pagar 52 M por un jugador
  que vale 33 M destruye 19 M de valor contable en el acto. Solo compensa si el
  salto de media sobre el jugador al que sustituye es grande, o si el jugador
  se va a revalorizar por encima de lo que pagas.
- Un fichaje bloquea la cláusula 14 días. Por eso toda oportunidad tiene hora
  conocida de apertura, y por eso esperar es a veces la jugada. Ese bloqueo
  cubre que no TE lo quiten. Si además impide revenderlo antes de plazo, no lo
  sé: cuando una jugada dependa de revender rápido a un recién fichado, dilo
  como condición a confirmar y no lo des por hecho.
- SUBIR una cláusula cuesta la mitad del incremento: pagas X y sube 2X. Blindar
  a un jugador tuyo casi siempre sale más barato que reemplazarlo si te lo
  clausulan. BAJARLA bloquea subirla 48 h y se publica en el tablón de la liga.
- La MEDIA engaña. Tienes pts(jornadas) y el rol: úsalos. 6,86 en 2 jornadas es
  ruido; 6,86 en 7 siendo clave es real. Media alta con rol suplente o rotación
  regresa a la media, siempre.
- Un LESIONADO o SANCIONADO no puntúa: su media es historia, no previsión.
- La TENDENCIA viene en euros/día y en % diario. El porcentaje es el que
  compara: 1 M/día en un jugador de 140 M es ruido, en uno de 20 M es una mina.
- SALDO: lo único que importa es estar en positivo en el instante en que
  arranca la próxima jornada. Antes da igual. Ponerse en rojo para coger una
  revalorización es jugada legítima si quedan días para vender. Arrancar la
  jornada en negativo es no puntuar NADA esa jornada.
- Tus propios jugadores con la cláusula abierta están expuestos: un rival puede
  llevárselos pagándola. Aparece en tu tabla.
- Esta liga no tiene capitán, banquillo, formaciones libres ni entrenador. No
  los menciones.

CUANDO IKER PROPONE ALGO
Evalúas SU idea, no contestas otra pregunta. Coges su propuesta, la pasas por
los números del informe y dices si sale o no sale y por cuánto. Si es buena,
dilo y da el dato que la confirma. Si falla, di exactamente dónde falla, con la
cifra, no en general. Si te falta un dato para juzgarla, dilo en media frase y
responde con lo que sí tienes. Nunca respondas con consejo genérico a una
propuesta concreta.

FORMA
- Español de España, tuteo, directo. Sin saludos, sin despedidas, sin "¡Vamos!".
- PRESUPUESTO DURO: toda la respuesta junta, máximo 4 frases y unas 400
  letras. No es una sugerencia. Si no te cabe, no es que necesites más sitio:
  es que estás explicando de más. Da el número y la conclusión, y calla.
- La conclusión primero, el porqué después.
- Nada de títulos, viñetas ni negritas. Es un chat, se escribe seguido.
- Como mucho dos ideas, separadas por una línea en blanco: cada bloque se manda
  como un mensaje distinto.
- Cifras concretas siempre, pero solo las que sostienen la conclusión. "Sube
  0,89 M/día, un 5,9% diario" vale; "buena oportunidad" no vale nada. No
  enseñes la cuenta entera: enseña el resultado.
- Nada de avisos genéricos. "Ojo, la tendencia puede cambiar" no aporta: o el
  riesgo tiene número, o no se menciona.
- Solo datos del informe. Nunca inventes un nombre, un precio ni una fecha.
- Si no hay nada que decir, una frase y punto.
- Un emoji como mucho, y la mayoría de respuestas no llevan ninguno.

Iker decide. Tú recomiendas, das el número y avisas del riesgo.
"""


def answer(
    question: str,
    state: LeagueState,
    values: ValueCache,
    *,
    now: datetime,
    client: Anthropic | None = None,
    effort: Effort = "medium",
) -> str:
    """Answer one question against the current league."""
    brief = league_digest(state, values, now=now)
    api = client or Anthropic()
    workspace = os.environ.get("ANTHROPIC_WORKSPACE_ID", "").strip()

    try:
        response = api.messages.create(
            model=MODEL,
            # Headroom, not a target. Adaptive thinking on a question like "does
            # this signing make sense" spends eleven or twelve hundred tokens
            # before it writes anything, and the cap counts both: at 1500 the
            # answer was getting truncated mid-sentence and, twice in testing,
            # never started at all — the run failed with "the answer was empty"
            # when the model had simply run out of room to speak. Nothing is
            # billed for room left unused, and the persona is what keeps the
            # reply short.
            max_tokens=3000,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            # The digest goes in the cached prefix rather than in the turn. It
            # is identical between syncs, so a follow-up question re-reads it
            # at a tenth of the price instead of paying full freight again:
            # measured at $0.0405 for the first question and $0.0109 for the
            # next, on the same league.
            system=[
                {"type": "text", "text": SYSTEM},
                {"type": "text", "text": brief, "cache_control": {"type": "ephemeral"}},
            ],
            messages=[{"role": "user", "content": question}],
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


def publish_briefing(state: LeagueState, values: ValueCache, *, now: datetime) -> int:
    """Write the digest and the persona to disk for the chat relay to read.

    The relay that answers Telegram runs somewhere always-on, which this agent
    is not, and rewriting the digest logic there would mean two implementations
    of what the agent knows — drifting apart from the first change onwards.

    So the relay is given no logic at all. It fetches these two files and posts
    them to the model verbatim. Everything about what the agent knows and how it
    speaks stays in this repository, in one language, covered by these tests.
    """
    digest = league_digest(state, values, now=now)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    (STATE_DIR / "digest.txt").write_text(digest, encoding="utf-8")
    (STATE_DIR / "persona.txt").write_text(SYSTEM, encoding="utf-8")
    return len(digest)


def league_digest(
    state: LeagueState, values: ValueCache, *, now: datetime, lookahead: int = 3
) -> str:
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

    lines.extend(_deadlines(state, now))

    lines += ["", "## Clasificación", "Pos | Manager | Puntos | Valor plantilla"]
    for team in sorted(state.teams, key=lambda t: t.rank or 99):
        mine = " (TÚ)" if team.id == state.my_team_id else ""
        lines.append(
            f"{team.rank} | {team.manager}{mine} | {team.points} | {millions(team.squad_value)}"
        )

    # Fixtures are listed once per club rather than once per player. A hundred
    # and forty-four players share twenty clubs, so repeating the run on every
    # row was the same handful of facts written seven times over — half the
    # size of the whole briefing, and paid for on every question.
    lines += ["", "## Próximos partidos por club"]
    for club_id, name in sorted(club_names(state).items(), key=lambda kv: kv[1]):
        run = describe_run(state, club_id, count=lookahead)
        if run:
            lines.append(f"{name}: {run}")

    lines.extend(_squad_tables(state, values, now=now))

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


def _deadlines(state: LeagueState, now: datetime) -> list[str]:
    """When the squad next freezes, which is what every decision is measured against.

    Both matchdays are stated because the gap between them is the whole
    question during an international break: a signing that leaves the balance
    negative is ruinous with a day to recover and perfectly sensible with three
    weeks.
    """
    lines: list[str] = []
    current = state.matchday
    if current is not None and current.opens_at is not None:
        started = "EN CURSO" if now >= current.opens_at else "aún no ha empezado"
        lines.append(
            f"Jornada {current.number}: empezó {current.opens_at:%d/%m %H:%M} ({started})."
        )

    binding = governing_deadline(current, state.next_matchday, now)
    if binding is None:
        lines.append("No tengo la fecha de la próxima jornada.")
        return lines

    days = (binding - now).total_seconds() / 86400
    upcoming = state.next_matchday.number if state.next_matchday else "?"
    lines.append(
        f"PLAZO QUE MANDA: la jornada {upcoming} arranca el {binding:%d/%m a las %H:%M}, "
        f"dentro de {days:.1f} días. Tu saldo tiene que estar en positivo en ese instante, "
        f"no antes: hasta entonces puedes estar en negativo sin perder nada."
    )
    return lines


#: A clause opening within this window is a live opportunity and gets the full
#: row. Beyond it, the player cannot be signed in any decision being taken now.
OPPORTUNITY_WINDOW = timedelta(days=10)


#: Below this average, and not a starter for his club, a rival's player cannot
#: be the answer to a question about signings: paying a clause premium for him
#: would not improve on the weakest player we already field. He keeps the short
#: row, which still carries the price trend a revaluation question needs.
NOISE_AVERAGE = 3.0

_POSITIONS = ("GK", "DF", "MF", "FW")


def _squad_tables(state: LeagueState, values: ValueCache, *, now: datetime) -> list[str]:
    """The players, grouped by what a question can actually turn on.

    This was one undifferentiated block sorted by manager, in which our own
    fourteen players sat scattered among a hundred and forty rivals in exactly
    the same format — under a heading that said "your squad". The model could
    not see the squad as a squad, so it could not reason about what the squad
    was short of, which of our own players a rival could take, or who was
    carrying it. That was the largest single reason its advice read as generic.

    So the squad comes first and alone, by position, with the points and the
    clause exposure that only mean something for players we hold. Rivals follow
    in order of scoring average rather than of their owner's name, because that
    is the order in which a signing question gets asked.
    """
    mine: list[OwnedPlayer] = []
    live: list[OwnedPlayer] = []
    rest: list[OwnedPlayer] = []

    for owned in state.owned_players:
        if owned.team_id == state.my_team_id:
            mine.append(owned)
            continue
        player = owned.player
        opens = owned.clause_locked_until
        reachable = opens is None or opens <= now + OPPORTUNITY_WINDOW
        noise = player.average_points < NOISE_AVERAGE and not player.role.is_starter
        if reachable and not owned.is_shielded and not noise:
            live.append(owned)
        else:
            rest.append(owned)

    lines = [
        "",
        f"## TU PLANTILLA ({len(mine)} jugadores)",
        "pos · jugador · club · pts(jornadas) · media · valor · tendencia · rol · "
        "[estado] · cláusula que pagaría un rival · si está expuesto ya",
        *(_own_row(owned, values, now=now) for owned in sorted(mine, key=_by_position)),
    ]

    lines += [
        "",
        f"## CLAUSULAS ALCANZABLES ({len(live)}) — de mayor a menor media",
        "jugador · pos · club · dueño · pts(jornadas) · media · valor · "
        "[cláusula · prima si no es x1,00] · se abre · rol · [estado] · tendencia",
        *(_full_row(owned, values, now=now) for owned in sorted(live, key=_by_average)),
    ]

    if rest:
        lines += [
            "",
            "## Resto de la liga (no fichable ahora, o irrelevante)",
            "Cláusula bloqueada más de 10 días, blindado, o media baja sin ser titular. "
            "jugador · club · dueño · valor · tendencia",
            *(_brief_row(owned, values) for owned in sorted(rest, key=_by_average)),
        ]
    return lines


def _by_position(owned: OwnedPlayer) -> tuple[int, float]:
    """Goalkeepers, defenders, midfielders, forwards — how a squad is read."""
    position = owned.player.position.value
    rank = _POSITIONS.index(position) if position in _POSITIONS else len(_POSITIONS)
    return (rank, -owned.player.average_points)


def _by_average(owned: OwnedPlayer) -> float:
    return -owned.player.average_points


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


_STATUS_ES = {
    PlayerStatus.DOUBTFUL: "DUDA",
    PlayerStatus.INJURED: "LESIONADO",
    PlayerStatus.SUSPENDED: "SANCIONADO",
    PlayerStatus.OUT_OF_LEAGUE: "FUERA DE LA LIGA",
}


def _record(player: Player) -> str:
    """Points, the matchdays that earned them, and only then the average.

    The average alone was all the briefing carried, and it is the field most
    likely to mislead: six points a game across two substitute appearances and
    across seven starts are the same number and opposite decisions. The count
    is what makes the average readable, and it cost one field to add.
    """
    return f"{player.total_points}pts({player.matchdays_played}j) {player.average_points:.2f}"


def _status(player: Player) -> str:
    """Stated only when it is not fine — an available player needs no word for it.

    Nothing about availability reached the chat before this, so an injured man
    appeared as his last healthy average and nothing else. Recommending him was
    not a failure of judgment; it was the only thing the briefing allowed.
    """
    label = _STATUS_ES.get(player.status)
    return f"{label} " if label else ""


def _trend(owned: OwnedPlayer, values: ValueCache) -> str:
    series = values.get(owned.player.id)
    if series is None or not series.points:
        return "?"
    read = valuation(series)
    sign = "+" if read.velocity >= 0 else ""
    # Euros a day does not compare across prices — two hundred thousand a day is
    # spectacular on a five million player and noise on a hundred million one —
    # so the percentage goes alongside it. That comparison is the whole point of
    # the column and it was missing.
    #
    # `Valuation.bids` is deliberately *not* here. It is documented in three
    # places as the only demand signal the game exposes, and it is zero in all
    # 9,574 observations on record: the endpoint does not return the field.
    # Printing it would tell the model that nobody in the league wants anybody.
    percent = f" ({read.velocity_pct * 100:+.1f}%/d)" if abs(read.velocity_pct) >= 0.002 else ""
    return f"{sign}{read.velocity / 1e6:.2f}/d{percent}".replace(".", ",")


def _brief_row(owned: OwnedPlayer, values: ValueCache) -> str:
    player = owned.player
    return (
        f"{player.name} {player.club or '?'} {owned.manager} "
        f"{millions(player.market_value)} {_trend(owned, values)}"
    )


def _own_row(owned: OwnedPlayer, values: ValueCache, *, now: datetime) -> str:
    """One of ours. The clause here is what a rival would pay to take him.

    Which is the fact the old briefing never stated in a form anyone could act
    on: our own players carried the same clause column as everyone else's, so
    the number read as a price to buy rather than as an exposure to cover.
    """
    player = owned.player
    clause = effective_clause(player.market_value, owned.buyout_clause)

    if owned.is_shielded:
        exposure = "BLINDADO"
    elif owned.clause_locked_until is None or owned.clause_locked_until <= now:
        exposure = "EXPUESTO YA"
    else:
        exposure = f"a salvo hasta {owned.clause_locked_until:%d/%m %H:%M}"

    return (
        f"{player.position.value} {player.name} {player.club or '?'} "
        f"{_record(player)} {millions(player.market_value)} {_trend(owned, values)} "
        f"{_ROLE_ES.get(player.role, '?')} {_status(player)}"
        f"te lo quitan por {millions(clause)} {exposure}"
    )


def _full_row(owned: OwnedPlayer, values: ValueCache, *, now: datetime) -> str:
    player = owned.player
    clause = effective_clause(player.market_value, owned.buyout_clause)
    premium = clause_premium(player.market_value, owned.buyout_clause)

    if owned.is_shielded:
        window = "BLINDADO"
    elif owned.clause_locked_until is None or owned.clause_locked_until <= now:
        window = "ABIERTA"
    else:
        window = f"{owned.clause_locked_until:%d/%m %H:%M}"

    # The clause and its premium are only stated when they differ from the
    # value. At x1.00 they repeat a number already on the line, and most of
    # the league sits at x1.00.
    priced = "" if abs(premium - 1.0) < 0.005 else f"{millions(clause)} x{premium:.2f} "
    return (
        f"{player.name} {player.position.value} {player.club or '?'} {owned.manager} "
        f"{_record(player)} {millions(player.market_value)} {priced}"
        f"{window} {_ROLE_ES.get(player.role, '?')} {_status(player)}{_trend(owned, values)}"
    )


__all__ = ["MODEL", "SYSTEM", "answer", "league_digest", "publish_briefing"]
