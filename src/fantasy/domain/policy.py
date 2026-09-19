"""The policy: the only file that decides what the agent is allowed to do.

Kept as data rather than as conditionals scattered through the code, for three
reasons. It can be reviewed by a human in one sitting. It can be changed
without a deploy — editing `policy.yml` and pushing is the whole procedure. And
it can be validated, so a typo becomes a startup error instead of a signing
nobody intended.

Validation is strict on purpose: unknown keys are rejected. A misspelled limit
that silently does nothing is the worst possible failure mode here.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from fantasy.domain.models import Euros


class Autonomy(StrEnum):
    """How much rope the agent has.

    Week one runs SUPERVISED: the agent does everything — watches, plans,
    explains, asks — but nothing reaches the API without a yes. The capability
    is fully built; the policy is what holds it back. Moving to MIXED later is a
    one-line change, not a deployment.
    """

    SUPERVISED = "supervised"
    MIXED = "mixed"
    AUTONOMOUS = "autonomous"


class Limits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_per_operation: Euros = 45_000_000
    max_per_run: Euros = 80_000_000
    max_operations_per_day: int = 4
    min_cash_reserve: Euros = 0

    def rejects(
        self,
        amount: Euros,
        spent_this_run: Euros,
        done_today: int,
        *,
        spends: bool = True,
        cash: Euros | None = None,
    ) -> str | None:
        """Why this operation is refused, or None if it passes.

        `spends` is the distinction that was missing. The money caps exist to
        bound what the agent can *spend*, and applying them to an incoming sum
        inverts their meaning: a 50 M offer for one of our players was refused
        for "exceeding the per-operation cap", which is the cap working exactly
        backwards. Sales and accepted offers still count against the daily
        operation limit, because that one bounds activity rather than money.
        """
        if done_today >= self.max_operations_per_day:
            return f"already at the daily cap of {self.max_operations_per_day} operations"
        if not spends:
            return None

        if amount > self.max_per_operation:
            return f"{amount:,} exceeds the per-operation cap of {self.max_per_operation:,}"
        if spent_this_run + amount > self.max_per_run:
            return f"would exceed the per-run budget of {self.max_per_run:,}"
        if cash is not None and cash - amount < self.min_cash_reserve:
            return (
                f"would leave {cash - amount:,} in hand, below the "
                f"{self.min_cash_reserve:,} reserve"
            )
        return None


class Filters(BaseModel):
    """What the agent will even consider signing."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_average: float = 5.5
    max_clause_premium: float = 1.15
    starters_only: bool = True
    exclude_status: tuple[str, ...] = ("injured", "suspended", "out_of_league", "doubtful")


class Objective(BaseModel):
    """What winning means here, and how to break the tie when goals conflict.

    Two aims that usually agree: points now, weighted by the fixture list, and
    market value so the budget compounds into the second half of the season.
    When they disagree — a starter peaking in value right before a hard run —
    `protect_starters` decides. With it on, a player in the starting eleven is
    never sold for market reasons; the trading happens with everyone else.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    protect_starters: bool = True
    #: How many upcoming fixtures the judgment layer is shown per player. A run
    #: of hard games is weighed there rather than scored here: any table of
    #: opponent difficulty is a guess about football that goes stale, and the
    #: model already knows what Barcelona away means.
    fixture_lookahead: int = 3


class ProtectItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    player_id: str
    raise_to: Euros
    before: datetime | None = None
    reason: str = ""


class Policy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    version: int = 1
    league_id: str
    team_id: str

    autonomy: Autonomy = Autonomy.SUPERVISED
    #: Below this, the agent acts on its own. Zero means it never does.
    auto_below: Euros = 0

    limits: Limits = Field(default_factory=Limits)
    filters: Filters = Field(default_factory=Filters)
    objective: Objective = Field(default_factory=Objective)
    protect: tuple[ProtectItem, ...] = ()

    @model_validator(mode="after")
    def _supervised_implies_no_autonomy(self) -> Policy:
        """SUPERVISED wins over any threshold left behind in the file.

        Guards against the obvious footgun: dropping back to supervised while
        `auto_below` still holds last week's fifteen million.
        """
        if self.autonomy is Autonomy.SUPERVISED and self.auto_below != 0:
            object.__setattr__(self, "auto_below", 0)
        return self

    def may_act_alone(self, amount: Euros) -> bool:
        if self.autonomy is Autonomy.AUTONOMOUS:
            return True
        if self.autonomy is Autonomy.SUPERVISED:
            return False
        return amount <= self.auto_below

    @classmethod
    def load(cls, path: str | Path) -> Policy:
        data: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(data)


__all__ = [
    "Autonomy",
    "Filters",
    "Limits",
    "Objective",
    "Policy",
    "ProtectItem",
]
