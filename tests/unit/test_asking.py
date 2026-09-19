"""How much the agent asks at once.

The first version sent one message per pending approval. A run holding a dozen
of them sent a dozen walls of text with buttons attached, which is the same
failure the whole redesign set out to fix — an agent that forwards its queue
has not decided anything, it has only moved the work.
"""

from __future__ import annotations

from datetime import timedelta

from fantasy.agent.schemas import Judgment, Pick
from fantasy.channel.telegram import ConsoleNotifier
from fantasy.cli import MAX_ASKS, _ask_what_matters
from fantasy.domain.approvals import Approval, ApprovalState
from fantasy.domain.intents import Intent, IntentKind

from .conftest import NOW, ROLES, make_policy


class Recorder(ConsoleNotifier):
    """Counts messages as well as recording them."""

    def __init__(self) -> None:
        super().__init__()
        self.batches: list[list[tuple[str, str]]] = []

    def ask_many(self, text: str, decisions: list[tuple[str, str]]) -> None:
        self.batches.append(decisions)
        super().ask_many(text, decisions)


class FakeAdvisor:
    """Answers with whatever judgment the test wants."""

    def __init__(self, judgment: Judgment | None = None, fail: bool = False) -> None:
        self._judgment = judgment
        self._fail = fail

    def judge(self, briefing: str) -> Judgment:
        if self._fail:
            from fantasy.agent.advisor import AdvisorError

            raise AdvisorError("offline")
        assert self._judgment is not None
        return self._judgment


def approval(index: int, *, hours: int = 1) -> Approval:
    intent = Intent(
        kind=IntentKind.RAISE_CLAUSE,
        execute_at=NOW + timedelta(hours=hours),
        anchor=NOW + timedelta(hours=hours),
        player_id=str(index),
        player_name=f"Player {index}",
        amount=1_000_000 * index,
        rationale="because",
    )
    return Approval(intent=intent)


def run_ask(approvals, league, advisor, tmp_path):
    notifier = Recorder()
    from fantasy.channel import ledger as ledger_module

    original = ledger_module.Ledger
    ledger_module.Ledger = lambda path=None: original(tmp_path / "said.jsonl")  # type: ignore[misc,assignment]
    try:
        _ask_what_matters(approvals, league, make_policy(), ROLES, notifier, NOW, advisor=advisor)
    finally:
        ledger_module.Ledger = original  # type: ignore[misc]
    return notifier


class TestOneMessageNotMany:
    def test_a_dozen_decisions_produce_exactly_one_message(self, league, tmp_path):
        waiting = [approval(i) for i in range(1, 13)]
        picks = tuple(Pick(key=a.key, reasoning="vale la pena") for a in waiting)
        notifier = run_ask(
            waiting,
            league,
            FakeAdvisor(Judgment(worth_saying=True, message="x", picks=picks)),
            tmp_path,
        )
        assert len(notifier.batches) == 1

    def test_it_asks_about_at_most_three(self, league, tmp_path):
        waiting = [approval(i) for i in range(1, 13)]
        picks = tuple(Pick(key=a.key, reasoning="vale la pena") for a in waiting)
        notifier = run_ask(
            waiting,
            league,
            FakeAdvisor(Judgment(worth_saying=True, message="x", picks=picks)),
            tmp_path,
        )
        assert len(notifier.batches[0]) == MAX_ASKS

    def test_only_what_was_asked_becomes_pending(self, league, tmp_path):
        waiting = [approval(i) for i in range(1, 13)]
        picks = tuple(Pick(key=a.key, reasoning="x") for a in waiting)
        run_ask(
            waiting,
            league,
            FakeAdvisor(Judgment(worth_saying=True, message="x", picks=picks)),
            tmp_path,
        )
        pending = [a for a in waiting if a.state is ApprovalState.PENDING]
        assert len(pending) == MAX_ASKS
        # The rest are untouched and will come back when they matter.
        assert all(a.state is ApprovalState.PROPOSED for a in waiting if a not in pending)


class TestSilenceAndFallback:
    def test_nothing_worth_raising_sends_nothing(self, league, tmp_path):
        waiting = [approval(i) for i in range(1, 5)]
        notifier = run_ask(waiting, league, FakeAdvisor(Judgment(worth_saying=False)), tmp_path)
        assert notifier.batches == []
        assert all(a.state is ApprovalState.PROPOSED for a in waiting)

    def test_an_unreachable_advisor_still_asks_about_the_most_imminent(self, league, tmp_path):
        """Degrading to terse beats going silent on a clause opening in an hour."""
        waiting = [approval(i, hours=24 - i) for i in range(1, 8)]
        notifier = run_ask(waiting, league, FakeAdvisor(fail=True), tmp_path)
        assert len(notifier.batches) == 1
        assert len(notifier.batches[0]) == MAX_ASKS
        asked = {key for key, _ in notifier.batches[0]}
        soonest = {a.key for a in sorted(waiting, key=lambda a: a.intent.execute_at)[:MAX_ASKS]}
        assert asked == soonest

    def test_no_pending_approvals_is_a_no_op(self, league, tmp_path):
        assert run_ask([], league, FakeAdvisor(fail=True), tmp_path).batches == []
