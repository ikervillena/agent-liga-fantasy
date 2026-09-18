"""The memory that stops the agent repeating itself.

Two opposing failures are being guarded at once. Saying the same thing twice is
what made the old agent unreadable; going permanently silent about a situation
that has since changed would be worse, because the manager would never learn
the thing that actually matters. The fingerprint is what separates them.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from fantasy.channel.ledger import RETENTION, Ledger, fingerprint

from .conftest import NOW


@pytest.fixture
def ledger(tmp_path: Path) -> Ledger:
    return Ledger(tmp_path / "said.jsonl")


class TestRepetition:
    def test_an_unsaid_key_is_not_suppressed(self, ledger: Ledger):
        assert not ledger.already_said("abc", now=NOW)

    def test_saying_it_once_suppresses_it(self, ledger: Ledger):
        ledger.record("abc", at=NOW, fingerprint="f1")
        assert ledger.already_said("abc", now=NOW + timedelta(hours=1), fingerprint="f1")

    def test_suppression_expires(self, ledger: Ledger):
        """A standing situation resurfaces eventually rather than being buried."""
        ledger.record("abc", at=NOW, fingerprint="f1")
        assert not ledger.already_said(
            "abc", now=NOW + RETENTION + timedelta(hours=1), fingerprint="f1"
        )


class TestChangedFactsBreakSilence:
    def test_a_changed_fingerprint_is_news_again(self, ledger: Ledger):
        ledger.record("abc", at=NOW, fingerprint="precio-12M")
        assert not ledger.already_said(
            "abc", now=NOW + timedelta(hours=1), fingerprint="precio-6M"
        )

    def test_the_latest_statement_wins(self, ledger: Ledger):
        ledger.record("abc", at=NOW, fingerprint="old")
        ledger.record("abc", at=NOW + timedelta(days=1), fingerprint="new")
        later = NOW + timedelta(days=1, hours=1)
        assert ledger.already_said("abc", now=later, fingerprint="new")
        assert not ledger.already_said("abc", now=later, fingerprint="old")


class TestBulkSuppression:
    def test_returns_only_the_keys_already_communicated(self, ledger: Ledger):
        ledger.record("seen", at=NOW, fingerprint="f")
        suppressed = ledger.suppress(
            {"seen": "f", "fresh": "g", "moved": "changed"}, now=NOW + timedelta(hours=2)
        )
        assert suppressed == ["seen"]


class TestDurability:
    def test_a_corrupt_line_does_not_silence_the_agent(self, ledger: Ledger):
        ledger.record("abc", at=NOW, fingerprint="f")
        with ledger.path.open("a", encoding="utf-8") as handle:
            handle.write("{ this is not json\n")
        ledger.record("def", at=NOW, fingerprint="f")
        assert {e.key for e in ledger.entries()} == {"abc", "def"}

    def test_a_missing_file_reads_as_nothing_said(self, tmp_path: Path):
        assert Ledger(tmp_path / "nope.jsonl").entries() == []


def test_fingerprint_is_stable_and_readable():
    assert fingerprint("mandi", 12, "key") == "mandi|12|key"
