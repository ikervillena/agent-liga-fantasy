"""What the agent has already told the manager.

The single most damaging thing the old agent did was repeat itself. Not through
a bug in the messaging — the approval machinery was sound — but because nothing
anywhere recorded that a thing had already been said. Every run started from
zero, decided the same facts were interesting, and sent them again.

So this is the memory, and it is deliberately shallow: a key, when it was said,
and a fingerprint of the state it was said about. That is enough to answer the
only two questions that matter. Have we mentioned this? And has it changed
enough since that mentioning it again is news rather than noise?

The fingerprint is what stops the cure becoming a worse disease. A ledger that
only remembered keys would go silent for ever about a player whose price had
since halved. Silence has to be revocable by the facts changing.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from fantasy.settings import STATE_DIR

#: How long a statement stays "already said". Long enough to cover the days an
#: opportunity sits open, short enough that a standing situation resurfaces
#: eventually rather than being buried for the season.
RETENTION = timedelta(days=5)


class Entry(BaseModel):
    model_config = ConfigDict(frozen=True)

    key: str
    said_at: datetime
    #: Cheap summary of what was true when it was said. When this changes, the
    #: same key is worth raising again.
    fingerprint: str = ""


class Ledger:
    """Append-only record of what has been communicated."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (STATE_DIR / "said.jsonl")

    def entries(self) -> list[Entry]:
        if not self.path.exists():
            return []
        found: list[Entry] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                found.append(Entry.model_validate_json(line))
            except ValueError:
                continue  # a corrupt line must not silence the agent
        return found

    def record(self, key: str, *, at: datetime, fingerprint: str = "") -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = Entry(key=key, said_at=at, fingerprint=fingerprint)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry.model_dump(mode="json"), sort_keys=True) + "\n")

    def already_said(
        self,
        key: str,
        *,
        now: datetime,
        fingerprint: str = "",
        retention: timedelta = RETENTION,
    ) -> bool:
        """Whether raising this again would be repetition rather than news."""
        for entry in reversed(self.entries()):
            if entry.key != key:
                continue
            if now - entry.said_at > retention:
                return False
            return entry.fingerprint == fingerprint
        return False

    def suppress(
        self,
        candidates: dict[str, str],
        *,
        now: datetime,
        retention: timedelta = RETENTION,
    ) -> list[str]:
        """Of `{key: fingerprint}`, the keys that have already been communicated."""
        return [
            key
            for key, fingerprint in candidates.items()
            if self.already_said(key, now=now, fingerprint=fingerprint, retention=retention)
        ]


def fingerprint(*parts: object) -> str:
    """A stable, readable summary of the facts a statement rested on.

    Coarse on purpose. Fingerprinting an exact price would make every nightly
    revaluation count as news and bring the repetition straight back, so
    callers are expected to pass values already bucketed to something a person
    would notice.
    """
    return "|".join(str(part) for part in parts)


__all__ = ["RETENTION", "Entry", "Ledger", "fingerprint"]
