"""The approval state machine — where a bug costs real money."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fantasy_agent.approvals import (
    Approval,
    ApprovalState,
    Observation,
    expire_stale,
    is_actionable,
    needs_asking,
    revalidate,
)
from fantasy_agent.intents import Conditions, Intent, IntentKind
from fantasy_agent.models import PlayerStatus, SquadRole

NOW = datetime(2026, 9, 10, 17, 48, tzinfo=UTC)


def approved_intent(price: int = 10_000_000) -> Approval:
    intent = Intent(
        kind=IntentKind.PAY_CLAUSE,
        execute_at=NOW,
        player_id="42",
        player_name="Mandi",
        amount=price,
        rationale="starter with no premium",
        conditions=Conditions(price=price, squad_role="key", player_status="ok"),
    )
    approval = Approval(intent=intent)
    approval.transition(ApprovalState.APPROVED, NOW - timedelta(days=2), "approved")
    return approval


class TestIdentity:
    def test_the_same_operation_yields_the_same_key(self) -> None:
        assert approved_intent().key == approved_intent().key

    def test_rewording_the_rationale_does_not_create_a_second_intent(self) -> None:
        base = approved_intent().intent
        reworded = base.model_copy(update={"rationale": "completely different words"})
        assert base.key == reworded.key

    def test_a_different_price_is_a_different_operation(self) -> None:
        assert approved_intent(10_000_000).key != approved_intent(12_000_000).key


class TestRevalidation:
    """Approval is given to a situation, so the situation is re-checked."""

    def test_price_drift_inside_the_tolerance_leaves_it_approved(self) -> None:
        approval = approved_intent()
        revalidate(approval, Observation(price=10_300_000), NOW)
        assert approval.state is ApprovalState.APPROVED

    def test_price_drift_beyond_the_tolerance_goes_back_to_the_manager(self) -> None:
        approval = approved_intent()
        revalidate(approval, Observation(price=12_000_000), NOW)
        assert approval.state is ApprovalState.NEEDS_REVIEW
        assert "price moved" in approval.history[-1].note

    def test_an_injury_always_stops_it_however_small_the_drift(self) -> None:
        approval = approved_intent()
        revalidate(
            approval,
            Observation(price=10_000_000, player_status=PlayerStatus.INJURED),
            NOW,
        )
        assert approval.state is ApprovalState.NEEDS_REVIEW

    def test_losing_his_place_stops_it_too(self) -> None:
        approval = approved_intent()
        revalidate(
            approval,
            Observation(price=10_000_000, squad_role=SquadRole.BENCH),
            NOW,
        )
        assert approval.state is ApprovalState.NEEDS_REVIEW

    def test_something_in_doubt_is_asked_about_again(self) -> None:
        approval = approved_intent()
        revalidate(approval, Observation(price=99_000_000), NOW)
        assert needs_asking(approval)


class TestExecutionWindow:
    def test_actionable_at_the_appointed_moment(self) -> None:
        assert is_actionable(approved_intent(), NOW)

    def test_not_actionable_before_it(self) -> None:
        assert not is_actionable(approved_intent(), NOW - timedelta(hours=1))

    def test_not_actionable_once_the_grace_period_has_passed(self) -> None:
        assert not is_actionable(approved_intent(), NOW + timedelta(hours=2))

    def test_a_pending_approval_is_never_actionable(self) -> None:
        intent = approved_intent().intent
        assert not is_actionable(Approval(intent=intent), NOW)


class TestTerminalStates:
    def test_stale_approvals_expire_instead_of_lingering(self) -> None:
        approval = approved_intent()
        expire_stale([approval], NOW + timedelta(days=3))
        assert approval.state is ApprovalState.EXPIRED

    def test_an_executed_approval_cannot_move_again(self) -> None:
        approval = approved_intent()
        approval.transition(ApprovalState.EXECUTED, NOW)
        with pytest.raises(ValueError, match="already executed"):
            approval.transition(ApprovalState.APPROVED, NOW)
