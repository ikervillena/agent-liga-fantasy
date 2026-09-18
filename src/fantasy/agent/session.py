"""One decision moment, end to end.

The pipeline, and the order matters:

    candidates (deterministic, legal, affordable)
        → enriched with role and price history
        → minus whatever was already communicated
        → briefing
        → Claude
        → resolved back onto the planner's own intents

Every narrowing happens before the model is involved, and every result is
validated after it. The model sits in the middle doing the only part that is
actually judgment.

Price history is fetched per candidate, which is why the narrowing has to come
first: one request per player is fine for a handful of candidates and would be
antisocial for seven hundred.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from fantasy.agent.advisor import Advisor, AdvisorError
from fantasy.agent.briefing import Candidate, render
from fantasy.agent.schemas import Judgment
from fantasy.agent.selection import Selection, resolve
from fantasy.analysis.valuation import Valuation, valuation
from fantasy.channel.ledger import Ledger, fingerprint
from fantasy.domain.intents import Intent
from fantasy.domain.models import LeagueState
from fantasy.domain.policy import Policy
from fantasy.sources.laliga.client import ApiError, FantasyClient
from fantasy.sources.laliga.market_value import fetch_series
from fantasy.sources.scouting.roles import RoleBook

#: Price buckets for the ledger fingerprint. A candidate whose price moved less
#: than this is the same news, and re-announcing it is the repetition this whole
#: mechanism exists to prevent.
FINGERPRINT_BUCKET = 1_000_000


class Outcome(BaseModel):
    """What one decision moment produced."""

    model_config = ConfigDict(frozen=True)

    judgment: Judgment | None = None
    selection: Selection = Selection()
    candidates_considered: int = 0
    suppressed: tuple[str, ...] = ()
    error: str = ""

    @property
    def should_send(self) -> bool:
        return bool(self.judgment and self.judgment.worth_saying and self.judgment.message)

    @property
    def message(self) -> str:
        return self.judgment.message if self.judgment else ""


def enrich(
    intents: list[Intent],
    roles: RoleBook,
    *,
    client: FantasyClient | None = None,
) -> list[Candidate]:
    """Attach role and price history to each candidate.

    A failed price lookup leaves the candidate without a valuation rather than
    failing the run: the model can still judge on role and points, and losing
    one signal beats losing the decision.
    """
    enriched: list[Candidate] = []
    for intent in intents:
        role = roles.role_of(intent.player_name, intent.player_id or "")
        enriched.append(
            Candidate(
                intent=intent,
                role=role,
                valuation=_valuation_for(intent, client),
            )
        )
    return enriched


def fingerprint_of(candidate: Candidate) -> str:
    """The facts a statement about this candidate rests on."""
    return fingerprint(
        candidate.intent.kind.value,
        candidate.intent.player_id or "",
        candidate.intent.amount // FINGERPRINT_BUCKET,
        candidate.role.value,
    )


def deliberate(
    state: LeagueState,
    policy: Policy,
    candidates: list[Candidate],
    *,
    now: datetime,
    advisor: Advisor,
    ledger: Ledger | None = None,
) -> Outcome:
    """Put the candidates to the model and validate what comes back."""
    ledger = ledger or Ledger()
    suppressed = ledger.suppress(
        {c.key: fingerprint_of(c) for c in candidates},
        now=now,
    )
    fresh = [c for c in candidates if c.key not in suppressed]

    if not fresh:
        return Outcome(candidates_considered=0, suppressed=tuple(suppressed))

    briefing = render(state, policy, fresh, now=now, already_said=suppressed)
    try:
        judgment = advisor.judge(briefing)
    except AdvisorError as exc:
        return Outcome(
            candidates_considered=len(fresh),
            suppressed=tuple(suppressed),
            error=str(exc),
        )

    return Outcome(
        judgment=judgment,
        selection=resolve(judgment, fresh),
        candidates_considered=len(fresh),
        suppressed=tuple(suppressed),
    )


def remember(outcome: Outcome, candidates: list[Candidate], *, at: datetime) -> None:
    """Record what was communicated so the next run does not say it again."""
    if not outcome.should_send:
        return
    ledger = Ledger()
    by_key = {c.key: c for c in candidates}
    for intent in outcome.selection.intents:
        candidate = by_key.get(intent.key)
        if candidate is not None:
            ledger.record(intent.key, at=at, fingerprint=fingerprint_of(candidate))


def _valuation_for(intent: Intent, client: FantasyClient | None) -> Valuation | None:
    if client is None or not intent.player_id:
        return None
    try:
        return valuation(fetch_series(client, intent.player_id))
    except (ApiError, OSError):
        return None


__all__ = [
    "FINGERPRINT_BUCKET",
    "Outcome",
    "deliberate",
    "enrich",
    "fingerprint_of",
    "remember",
]
