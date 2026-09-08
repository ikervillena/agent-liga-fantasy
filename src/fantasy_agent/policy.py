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

from .models import Euros


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

    def rejects(self, amount: Euros, spent_this_run: Euros, done_today: int) -> str | None:
        """Returns why the operation is refused, or None if it passes."""
        if amount > self.max_per_operation:
            return f"{amount:,} exceeds the per-operation cap of {self.max_per_operation:,}"
        if spent_this_run + amount > self.max_per_run:
            return f"would exceed the per-run budget of {self.max_per_run:,}"
        if done_today >= self.max_operations_per_day:
            return f"already at the daily cap of {self.max_operations_per_day} operations"
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
    fixture_lookahead: int = 3
    #: Relative weight of value growth against points when ranking candidates.
    value_growth_weight: float = 0.3


class WatchItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    player_id: str
    action: str = "pay_clause"
    max_price: Euros
    opens_at: datetime | None = None
    reason: str = ""


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
    watchlist: tuple[WatchItem, ...] = ()
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
    "WatchItem",
]
