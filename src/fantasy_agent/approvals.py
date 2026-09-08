"""The approval lifecycle.

A single explicit state machine, because this is where a bug costs money. The
states and the only legal moves between them:

    PROPOSED ─auto─> APPROVED ─execute─> EXECUTED
        │                │
        └─ask─> PENDING ─┤
                  │      ├─conditions moved─> NEEDS_REVIEW ─ask─> PENDING
                  │      └─window passed───> EXPIRED
                  ├─no─> REJECTED
                  └─window passed─> EXPIRED

The interesting transition is NEEDS_REVIEW. Approval is granted to a situation,
so before firing we re-check the situation. What happens when it has moved is a
deliberate product decision, not a technical default:

  * the price drifted, but within the agreed tolerance → the approval stands.
    The manager already said yes to this deal, and a 3% move is the same deal.
  * anything about the football changed — injury, suspension, lost his place —
    → the approval does not stand. Missing a window is recoverable; buying an
    injured player for forty million is not.

Rejections and expiries are terminal. Nothing here deletes history: the record
is append-only so that "why did it buy that?" always has an answer.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from .intents import Intent
from .models import PlayerStatus, SquadRole


class ApprovalState(StrEnum):
    PROPOSED = "proposed"
    PENDING = "pending"
    APPROVED = "approved"
    NEEDS_REVIEW = "needs_review"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (
            ApprovalState.REJECTED,
            ApprovalState.EXPIRED,
            ApprovalState.EXECUTED,
            ApprovalState.FAILED,
        )


class Observation(BaseModel):
    """The current facts an approval is re-checked against."""

    model_config = ConfigDict(frozen=True)

    price: int
    player_status: PlayerStatus = PlayerStatus.OK
    squad_role: SquadRole = SquadRole.UNKNOWN


class Event(BaseModel):
    model_config = ConfigDict(frozen=True)

    at: datetime
    state: ApprovalState
    note: str = ""


class Approval(BaseModel):
    """One intent and everything that has happened to it."""

    intent: Intent
    state: ApprovalState = ApprovalState.PROPOSED
    history: list[Event] = Field(default_factory=list)
    asked_at: datetime | None = None
    decided_at: datetime | None = None

    @property
    def key(self) -> str:
        return self.intent.key

    def transition(self, state: ApprovalState, at: datetime, note: str = "") -> None:
        if self.state.is_terminal:
            raise ValueError(
                f"{self.key} is already {self.state.value}; cannot move to {state.value}"
            )
        self.state = state
        self.history.append(Event(at=at, state=state, note=note))


def needs_asking(approval: Approval) -> bool:
    return approval.state in (ApprovalState.PROPOSED, ApprovalState.NEEDS_REVIEW)


def is_actionable(
    approval: Approval, now: datetime, grace: timedelta = timedelta(minutes=30)
) -> bool:
    """Approved, and we are inside its execution window."""
    if approval.state is not ApprovalState.APPROVED:
        return False
    start = approval.intent.execute_at
    return start <= now <= start + grace


def revalidate(approval: Approval, observed: Observation, now: datetime) -> Approval:
    """Re-check an approved intent against the world as it is now.

    Returns the approval, mutated in place. Called immediately before execution
    and on every polling pass, so a squad change during the day is caught even
    if nobody is watching.
    """
    if approval.state is not ApprovalState.APPROVED:
        return approval

    conditions = approval.intent.conditions

    if not observed.player_status.is_available:
        approval.transition(
            ApprovalState.NEEDS_REVIEW,
            now,
            f"status changed to {observed.player_status.value}",
        )
        return approval

    # An UNKNOWN role means the scouting file lost him, not that he was
    # dropped. Absence of evidence must not cancel a deal the manager approved;
    # the price and availability checks still stand either way.
    was_starter = SquadRole(conditions.squad_role or "unknown").is_starter
    demoted = observed.squad_role is not SquadRole.UNKNOWN and not observed.squad_role.is_starter
    if was_starter and demoted:
        approval.transition(
            ApprovalState.NEEDS_REVIEW,
            now,
            f"role dropped to {observed.squad_role.value}",
        )
        return approval

    if not conditions.price_still_acceptable(observed.price):
        drift = conditions.drift(observed.price)
        approval.transition(
            ApprovalState.NEEDS_REVIEW,
            now,
            f"price moved {drift:+.1%}, beyond the agreed {conditions.price_tolerance:.0%}",
        )
    return approval


def expire_stale(
    approvals: list[Approval], now: datetime, grace: timedelta = timedelta(minutes=30)
) -> None:
    """Close out anything whose moment has passed.

    Without this, an approval given on Monday for Thursday would sit around and
    fire during some unrelated run the following week.
    """
    for approval in approvals:
        if approval.state.is_terminal:
            continue
        if now > approval.intent.execute_at + grace:
            approval.transition(ApprovalState.EXPIRED, now, "execution window passed")


__all__ = [
    "Approval",
    "ApprovalState",
    "Event",
    "Observation",
    "expire_stale",
    "is_actionable",
    "needs_asking",
    "revalidate",
]
