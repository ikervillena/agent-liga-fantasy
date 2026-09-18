"""The contract the judgment layer answers with.

The shape here is the safety mechanism, not just a serialisation detail. The
model is never asked what to do — it is handed operations the domain has
already ruled legal and affordable, and asked which of them are worth doing and
how to explain them. So a pick carries a *reference* to a candidate, never a
player and a price of its own invention.

That makes a whole class of failure impossible rather than merely unlikely. A
model that hallucinates a player, a price, or an operation the game would
reject cannot express it in this schema: an unknown key resolves to nothing and
is dropped. Nothing downstream has to trust the model's arithmetic.

`worth_saying` exists for the same reason in the opposite direction. Most hours
of most days there is nothing to report, and the old agent's habit of filling
that silence with a restated league table is what made it unreadable. Saying
nothing is a valid, first-class answer.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Pick(BaseModel):
    """One candidate the model judges worth putting to the manager."""

    model_config = ConfigDict(frozen=True)

    key: str = Field(description="The candidate key exactly as given in the briefing.")
    priority: int = Field(
        default=5,
        ge=1,
        le=10,
        description="1 is most urgent. Rank by what would be lost by not acting today.",
    )
    reasoning: str = Field(
        description=(
            "Why this is worth doing, in Spanish, addressed to the manager. "
            "One or two sentences. Name the specific evidence — form, price "
            "trend, role, fixtures — never generic praise."
        )
    )


class Discard(BaseModel):
    """A candidate deliberately passed over, and why.

    Recorded because the interesting question about an agent is usually what it
    chose not to do, and because a rejection the manager can read is a
    rejection he can overrule.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    reason: str = Field(description="Short, in Spanish. Why this one is not worth it.")


class Judgment(BaseModel):
    """The model's full answer for one decision moment."""

    model_config = ConfigDict(frozen=True)

    worth_saying: bool = Field(
        description=(
            "False when there is nothing the manager needs to know or decide "
            "right now. Silence is the correct answer far more often than not."
        )
    )
    message: str = Field(
        default="",
        description=(
            "What to send the manager, in Spanish. Plain and direct, no "
            "greeting, no filler, no restating things he already knows. Empty "
            "when worth_saying is false."
        ),
    )
    picks: tuple[Pick, ...] = Field(
        default=(),
        description="Candidates worth acting on, most urgent first. Empty is fine.",
    )
    discarded: tuple[Discard, ...] = Field(
        default=(),
        description="Candidates considered and passed over, with the reason.",
    )

    @property
    def is_silent(self) -> bool:
        return not self.worth_saying and not self.picks


__all__ = ["Discard", "Judgment", "Pick"]
