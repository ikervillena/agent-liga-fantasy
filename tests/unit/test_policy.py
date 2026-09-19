"""The policy is the safety boundary, so its edges are tested explicitly."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from fantasy.domain.policy import Autonomy, Limits, Policy


def build(**overrides: object) -> Policy:
    return Policy.model_validate({"league_id": "L", "team_id": "T", **overrides})


class TestAutonomy:
    def test_supervised_never_acts_alone(self) -> None:
        assert build(autonomy="supervised").may_act_alone(1) is False

    def test_supervised_neutralises_a_leftover_threshold(self) -> None:
        # Dropping back to supervised must not leave last week's 15 M live.
        policy = build(autonomy="supervised", auto_below=15_000_000)
        assert policy.auto_below == 0
        assert policy.may_act_alone(1_000_000) is False

    def test_mixed_respects_the_threshold(self) -> None:
        policy = build(autonomy="mixed", auto_below=15_000_000)
        assert policy.may_act_alone(14_000_000) is True
        assert policy.may_act_alone(16_000_000) is False

    def test_autonomous_acts_within_the_limits(self) -> None:
        assert build(autonomy=Autonomy.AUTONOMOUS).may_act_alone(40_000_000) is True


class TestLimits:
    def test_rejects_an_oversized_operation(self) -> None:
        limits = Limits(max_per_operation=10_000_000)
        assert limits.rejects(11_000_000, 0, 0) is not None

    def test_rejects_when_the_run_budget_is_spent(self) -> None:
        limits = Limits(max_per_run=20_000_000)
        assert limits.rejects(5_000_000, 18_000_000, 0) is not None

    def test_rejects_past_the_daily_count(self) -> None:
        limits = Limits(max_operations_per_day=2)
        assert limits.rejects(1, 0, 2) is not None

    def test_passes_within_every_limit(self) -> None:
        assert Limits().rejects(1_000_000, 0, 0) is None


class TestValidation:
    def test_a_misspelled_key_is_an_error_not_a_silent_no_op(self) -> None:
        with pytest.raises(ValidationError):
            build(limmits={"max_per_operation": 1})


class TestIncomingMoneyIsNotSpending:
    """The caps bound what the agent spends, not what it takes in.

    Applying them to a sale inverts their meaning: an offer above the
    per-operation cap was refused for being too large, when a large offer for
    one of our players is the good case.
    """

    def test_a_sale_above_the_cap_is_allowed(self) -> None:
        limits = Limits(max_per_operation=45_000_000)
        assert limits.rejects(60_000_000, 0, 0, spends=False) is None

    def test_a_purchase_above_the_cap_is_still_refused(self) -> None:
        limits = Limits(max_per_operation=45_000_000)
        assert limits.rejects(60_000_000, 0, 0) is not None

    def test_a_sale_does_not_eat_the_run_budget(self) -> None:
        limits = Limits(max_per_run=80_000_000)
        assert limits.rejects(70_000_000, 70_000_000, 0, spends=False) is None

    def test_sales_still_count_towards_the_daily_operation_cap(self) -> None:
        limits = Limits(max_operations_per_day=2)
        assert limits.rejects(1_000_000, 0, 2, spends=False) is not None

    def test_the_cash_reserve_is_now_enforced(self) -> None:
        """`min_cash_reserve` was declared in the policy and read by nothing."""
        limits = Limits(min_cash_reserve=5_000_000)
        assert limits.rejects(10_000_000, 0, 0, cash=12_000_000) is not None
        assert limits.rejects(10_000_000, 0, 0, cash=20_000_000) is None
