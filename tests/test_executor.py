"""Execution guarantees. These tests exist to defend three claims made in the
README: a dry run cannot reach the API, limits are enforced regardless of
approval, and everything that happens is written down."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fantasy_agent.approvals import Approval, ApprovalState
from fantasy_agent.executor import Executor
from fantasy_agent.intents import Intent, IntentKind
from fantasy_agent.laliga.client import FantasyClient, WriteClient
from fantasy_agent.policy import Policy
from fantasy_agent.storage import Store

NOW = datetime(2026, 9, 10, 17, 48, tzinfo=UTC)


def approval(amount: int = 10_000_000, at: datetime = NOW) -> Approval:
    intent = Intent(
        kind=IntentKind.PAY_CLAUSE,
        execute_at=at,
        player_id="42",
        player_name="Mandi",
        amount=amount,
        rationale="starter with no premium",
    )
    approved = Approval(intent=intent)
    approved.transition(ApprovalState.APPROVED, at - timedelta(days=1), "approved")
    return approved


def policy(**overrides: object) -> Policy:
    return Policy.model_validate({"league_id": "L", "team_id": "T", **overrides})


class TestDryRun:
    def test_needs_no_client_at_all(self, tmp_path: Path) -> None:
        # Constructed with None: if a dry run could reach the API this would fail.
        executor = Executor(None, policy(), Store(tmp_path), dry_run=True)  # type: ignore[arg-type]
        outcomes = executor.run([approval()], NOW)
        assert [o.status for o in outcomes] == ["dry_run"]

    def test_leaves_the_approval_untouched(self, tmp_path: Path) -> None:
        pending = approval()
        Executor(None, policy(), Store(tmp_path), dry_run=True).run([pending], NOW)  # type: ignore[arg-type]
        assert pending.state is ApprovalState.APPROVED


class TestLimits:
    def test_an_oversized_operation_is_blocked_even_though_approved(self, tmp_path: Path) -> None:
        strict = policy(limits={"max_per_operation": 1_000_000})
        outcomes = Executor(None, strict, Store(tmp_path), dry_run=True).run(  # type: ignore[arg-type]
            [approval(50_000_000)], NOW
        )
        assert [o.status for o in outcomes] == ["blocked"]

    def test_an_approval_outside_its_window_is_skipped_entirely(self, tmp_path: Path) -> None:
        outcomes = Executor(None, policy(), Store(tmp_path), dry_run=True).run(  # type: ignore[arg-type]
            [approval(at=NOW + timedelta(days=1))], NOW
        )
        assert outcomes == []


class TestAudit:
    def test_every_decision_is_appended_to_the_log(self, tmp_path: Path) -> None:
        store = Store(tmp_path)
        Executor(None, policy(), store, dry_run=True).run([approval()], NOW)  # type: ignore[arg-type]
        lines = store.log_path.read_text(encoding="utf-8").strip().splitlines()
        entry = json.loads(lines[0])
        assert entry["player"] == "Mandi"
        assert entry["dry_run"] is True

    def test_blocked_operations_are_logged_too(self, tmp_path: Path) -> None:
        store = Store(tmp_path)
        strict = policy(limits={"max_per_operation": 1})
        Executor(None, strict, store, dry_run=True).run([approval()], NOW)  # type: ignore[arg-type]
        assert json.loads(store.log_path.read_text().strip())["status"] == "blocked"


class TestWriteClient:
    def test_cannot_be_built_by_accident(self) -> None:
        with pytest.raises(ValueError, match="confirm=True"):
            WriteClient(FantasyClient())
