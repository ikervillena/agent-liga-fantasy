"""Reading and writing the files the agent keeps in the repository.

State is committed to git rather than kept in a database, which is an unusual
choice worth defending: it gives free history and diffs of every change in the
league, it needs no infrastructure, and it is readable by anything that can
clone a repository. The dataset is a few hundred kilobytes; the day it stops
fitting, this module is the only thing that changes.

Everything is written with sorted keys and stable ordering so that a commit
diff shows what actually moved in the league, not JSON churn.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .approvals import Approval
from .config import STATE_DIR


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return fallback


class Store:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or STATE_DIR
        self.root.mkdir(parents=True, exist_ok=True)

    # -- league snapshots -----------------------------------------------------
    @property
    def snapshot_path(self) -> Path:
        return self.root / "league.json"

    @property
    def previous_path(self) -> Path:
        return self.root / "league.previous.json"

    def save_snapshot(self, payload: dict[str, Any]) -> None:
        """Keep the prior snapshot so the brief can report what changed."""
        if self.snapshot_path.exists():
            self.previous_path.write_text(
                self.snapshot_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
        _write_json(self.snapshot_path, payload)

    def load_snapshot(self) -> dict[str, Any]:
        return dict(_read_json(self.snapshot_path, {}))

    def load_previous(self) -> dict[str, Any]:
        return dict(_read_json(self.previous_path, {}))

    # -- approvals ------------------------------------------------------------
    @property
    def approvals_path(self) -> Path:
        return self.root / "approvals.json"

    def load_approvals(self) -> list[Approval]:
        return [Approval.model_validate(row) for row in _read_json(self.approvals_path, [])]

    def save_approvals(self, approvals: list[Approval]) -> None:
        _write_json(
            self.approvals_path,
            [
                a.model_dump(mode="json")
                for a in sorted(approvals, key=lambda a: a.intent.execute_at)
            ],
        )

    # -- conversation cursor --------------------------------------------------
    @property
    def cursor_path(self) -> Path:
        return self.root / "telegram-cursor.json"

    def load_cursor(self) -> int:
        return int(_read_json(self.cursor_path, {}).get("offset", 0))

    def save_cursor(self, offset: int) -> None:
        _write_json(self.cursor_path, {"offset": offset})

    # -- append-only decision log --------------------------------------------
    @property
    def log_path(self) -> Path:
        return self.root / "decisions.jsonl"

    def log(self, entry: dict[str, Any]) -> None:
        """One line per decision, never rewritten.

        This is what answers "why did it buy that?" three weeks later, and what
        makes the agent's record measurable rather than anecdotal.
        """
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str) + "\n")


__all__ = ["Store"]
