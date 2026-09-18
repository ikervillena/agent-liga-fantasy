"""Turning a judgment back into operations.

This is the seam where the model's answer re-enters typed territory, so it is
where the answer stops being trusted. A pick is a lookup, not an instruction: a
key that matches nothing is dropped and reported, never guessed at. The
operations that come out are the exact `Intent` objects the domain built, with
the model's reasoning attached for the manager to read.

The consequence worth being explicit about: the worst a confused or adversarial
answer can do here is select a legal operation that was already on the table,
or none at all. It cannot conjure one.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from fantasy.agent.briefing import Candidate
from fantasy.agent.schemas import Judgment
from fantasy.domain.intents import Intent


class Selection(BaseModel):
    """What the judgment resolved to, plus what could not be resolved."""

    model_config = ConfigDict(frozen=True)

    intents: tuple[Intent, ...] = ()
    #: Keys the model returned that match no candidate. Always a bug or a
    #: hallucination, so they are surfaced rather than silently ignored.
    unknown_keys: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not self.intents


def resolve(judgment: Judgment, candidates: list[Candidate]) -> Selection:
    """Map picks onto the candidates they name, most urgent first."""
    by_key = {candidate.key: candidate for candidate in candidates}
    chosen: list[Intent] = []
    unknown: list[str] = []

    for pick in sorted(judgment.picks, key=lambda p: p.priority):
        candidate = by_key.get(pick.key)
        if candidate is None:
            unknown.append(pick.key)
            continue
        chosen.append(candidate.intent.model_copy(update={"rationale": pick.reasoning}))

    return Selection(intents=tuple(chosen), unknown_keys=tuple(unknown))


__all__ = ["Selection", "resolve"]
