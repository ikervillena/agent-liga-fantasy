"""Intents: what the agent proposes to do, and when.

An intent is a dated, priced, justified proposal — never an immediate command.
That separation is the core of the design: because buyout windows open at known
instants, the agent can show its hand days in advance and collect approval
before the moment arrives, instead of interrupting for a decision at 17:48 on a
Thursday.

Every intent carries a deterministic `key`. Two runs that reach the same
conclusion about the same player at the same instant produce the same key, so
replaying a plan can never pay a clause twice.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .models import Euros


class IntentKind(StrEnum):
    PAY_CLAUSE = "pay_clause"
    RAISE_CLAUSE = "raise_clause"
    BID = "bid"
    SELL = "sell"
    ACCEPT_OFFER = "accept_offer"
    REJECT_OFFER = "reject_offer"
    SET_LINEUP = "set_lineup"

    @property
    def spends_money(self) -> bool:
        return self in (IntentKind.PAY_CLAUSE, IntentKind.RAISE_CLAUSE, IntentKind.BID)


class Conditions(BaseModel):
    """The world as it looked when the intent was proposed.

    Re-checked immediately before execution. Approval is given to a situation,
    not to a blank cheque: if the situation moved, the approval is reconsidered
    rather than honoured blindly.
    """

    model_config = ConfigDict(frozen=True)

    price: Euros = 0
    #: How much the price may drift and still count as the same deal.
    price_tolerance: float = 0.05
    player_status: str = "ok"
    squad_role: str = "unknown"
    average_points: float = 0.0

    def drift(self, current_price: Euros) -> float:
        if self.price <= 0:
            return 0.0
        return (current_price - self.price) / self.price

    def price_still_acceptable(self, current_price: Euros) -> bool:
        return self.drift(current_price) <= self.price_tolerance


class Intent(BaseModel):
    """A single proposed operation."""

    model_config = ConfigDict(frozen=True)

    kind: IntentKind
    execute_at: datetime
    rationale: str
    conditions: Conditions = Field(default_factory=Conditions)

    player_id: str | None = None
    player_name: str = ""
    market_id: str | None = None
    offer_id: str | None = None
    amount: Euros = 0
    payload: dict[str, Any] = Field(default_factory=dict)

    #: Points of matchday average this is expected to add to the starting eleven.
    expected_gain: float = 0.0
    #: What we would do instead if this falls through.
    fallback: str = ""

    @property
    def key(self) -> str:
        """Stable identity for this intent.

        Deliberately excludes the rationale and the expected gain: those are
        commentary, and a reworded explanation must not create a second intent
        for an operation that is already approved.
        """
        raw = "|".join(
            [
                self.kind.value,
                self.player_id or "",
                self.market_id or "",
                self.offer_id or "",
                str(self.amount),
                self.execute_at.isoformat(timespec="minutes"),
            ]
        )
        return hashlib.sha256(raw.encode()).hexdigest()[:12]

    @property
    def euros_per_point(self) -> float:
        if self.expected_gain <= 0:
            return float("inf")
        return self.amount / self.expected_gain

    def describe(self) -> str:
        """One line for the daily brief. Amounts in millions, comma decimals."""
        money = f"{self.amount / 1e6:.2f} M".replace(".", ",")
        verb = _VERBS[self.kind]
        target = self.player_name or self.market_id or ""
        return f"{verb} {target} · {money}".strip()


_VERBS: dict[IntentKind, str] = {
    IntentKind.PAY_CLAUSE: "Pay clause for",
    IntentKind.RAISE_CLAUSE: "Raise clause on",
    IntentKind.BID: "Bid for",
    IntentKind.SELL: "List for sale",
    IntentKind.ACCEPT_OFFER: "Accept offer for",
    IntentKind.REJECT_OFFER: "Reject offer for",
    IntentKind.SET_LINEUP: "Set lineup",
}


__all__ = ["Conditions", "Intent", "IntentKind"]
