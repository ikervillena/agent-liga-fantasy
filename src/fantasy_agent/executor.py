"""Execution: the only code in the project that changes anything.

Three gates stand between an intent and the API, in this order:

1. **The approval must be actionable** — approved, revalidated against the
   world as it is now, and inside its execution window.
2. **The policy limits must allow it** — per-operation cap, per-run budget,
   daily count.
3. **A write client must have been explicitly constructed.** Passing
   `dry_run=True` (the default) means one is never created at all, so there is
   no code path from a dry run to a real request.

Everything that happens, including everything refused, goes to the append-only
decision log. An agent that spends money without leaving a trail is not one you
would let near a real account.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .approvals import Approval, ApprovalState, is_actionable
from .intents import IntentKind
from .laliga.client import ApiError, FantasyClient, WriteClient
from .policy import Policy
from .storage import Store


class Outcome:
    """What happened to one intent on one run."""

    def __init__(self, key: str, status: str, detail: str = "") -> None:
        self.key = key
        self.status = status
        self.detail = detail

    def as_dict(self) -> dict[str, Any]:
        return {"key": self.key, "status": self.status, "detail": self.detail}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Outcome({self.key}, {self.status}, {self.detail!r})"


class Executor:
    def __init__(
        self,
        client: FantasyClient,
        policy: Policy,
        store: Store,
        *,
        dry_run: bool = True,
    ) -> None:
        self._client = client
        self._policy = policy
        self._store = store
        self._dry_run = dry_run
        # No write client at all in a dry run: the capability simply is not there.
        self._writer = None if dry_run else WriteClient(client, confirm=True)

    def run(self, approvals: list[Approval], now: datetime | None = None) -> list[Outcome]:
        now = now or datetime.now(UTC)
        outcomes: list[Outcome] = []
        spent = 0
        done = 0

        for approval in approvals:
            if not is_actionable(approval, now):
                continue

            intent = approval.intent
            refusal = self._policy.limits.rejects(intent.amount, spent, done)
            if refusal:
                outcomes.append(Outcome(approval.key, "blocked", refusal))
                self._log(approval, "blocked", refusal, now)
                continue

            if self._dry_run:
                outcomes.append(Outcome(approval.key, "dry_run", intent.describe()))
                self._log(approval, "dry_run", intent.describe(), now)
                continue

            try:
                self._dispatch(intent)
            except ApiError as exc:
                approval.transition(ApprovalState.FAILED, now, str(exc))
                outcomes.append(Outcome(approval.key, "failed", str(exc)))
                self._log(approval, "failed", str(exc), now)
                continue

            approval.transition(ApprovalState.EXECUTED, now, intent.describe())
            outcomes.append(Outcome(approval.key, "executed", intent.describe()))
            self._log(approval, "executed", intent.describe(), now)
            if intent.kind.spends_money:
                spent += intent.amount
            done += 1

        return outcomes

    def _dispatch(self, intent: Any) -> Any:
        writer = self._writer
        if writer is None:  # pragma: no cover - guarded by the dry-run branch
            raise RuntimeError("no write client in a dry run")

        league = self._policy.league_id
        match intent.kind:
            case IntentKind.PAY_CLAUSE:
                return writer.pay_clause(league, str(intent.player_id), intent.amount)
            case IntentKind.RAISE_CLAUSE:
                increase = int(intent.payload.get("increase", intent.amount * 2))
                return writer.raise_clause(league, str(intent.player_id), increase)
            case IntentKind.BID:
                return writer.bid(league, str(intent.market_id), intent.amount)
            case IntentKind.SELL:
                return writer.sell(league, str(intent.player_id), intent.amount)
            case IntentKind.ACCEPT_OFFER:
                return writer.accept_offer(
                    league, str(intent.market_id), str(intent.offer_id), intent.amount
                )
            case IntentKind.REJECT_OFFER:
                return writer.reject_offer(league, str(intent.market_id), str(intent.offer_id))
            case IntentKind.SET_LINEUP:
                return writer.set_lineup(self._policy.team_id, intent.payload.get("lineup"))
            case _:  # pragma: no cover - exhaustive over the enum
                raise ValueError(f"unsupported intent kind: {intent.kind}")

    def _log(self, approval: Approval, status: str, detail: str, now: datetime) -> None:
        self._store.log(
            {
                "at": now.isoformat(timespec="seconds"),
                "key": approval.key,
                "kind": approval.intent.kind.value,
                "player": approval.intent.player_name,
                "amount": approval.intent.amount,
                "expected_gain": approval.intent.expected_gain,
                "status": status,
                "detail": detail,
                "dry_run": self._dry_run,
            }
        )


__all__ = ["Executor", "Outcome"]
