"""Squad roles: how much each player actually plays for his club.

The game API says nothing about this, and it is the filter that has saved the
most money — a 9.0 average built on three substitute appearances regresses to
nothing, and we have been burned by exactly that.

Roles live in `config/roles.yml`, a curated file kept under version control. A
reviewed file beats a fragile scraper here: the data changes a couple of times
a week, a wrong parse would silently approve a bench player, and the file gives
us a diff and a history of who was considered a starter when.

Anyone not listed resolves to UNKNOWN, which fails the starter filter. Silence
means "do not buy", never "probably fine".
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import yaml

from fantasy.domain.models import SquadRole
from fantasy.settings import ROLES_FILE

DEFAULT_PATH = ROLES_FILE


class RoleBook:
    """Player name or id to squad role."""

    def __init__(self, by_key: dict[str, SquadRole], source: str = "") -> None:
        self._by_key = by_key
        self.source = source

    def role_of(self, *keys: str) -> SquadRole:
        for key in keys:
            if not key:
                continue
            found = self._by_key.get(normalise(key))
            if found is not None:
                return found
        return SquadRole.UNKNOWN

    def __len__(self) -> int:
        return len(self._by_key)


def normalise(key: str) -> str:
    """Fold a name to a comparison key: lowercase, single-spaced, unaccented.

    Accents are stripped because the sources disagree about them and a human
    typing an override will not reproduce them reliably. The scouting site
    writes "Ángel Pérez"; this project's own curated file wrote "Angel Perez";
    both must resolve to the same player, or the override silently does nothing
    and the agent quietly treats a key starter as unknown.
    """
    folded = unicodedata.normalize("NFKD", key.strip().lower())
    without_accents = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(without_accents.split())


def load_roles(path: Path | None = None) -> RoleBook:
    """Read the curated role file. A missing file is not fatal.

    Without it every player is UNKNOWN, so the agent proposes no signings but
    still watches, shields and reports. Degrading to cautious beats crashing.
    """
    target = path or DEFAULT_PATH
    if not target.exists():
        return RoleBook({}, source=f"{target} (missing)")

    raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    table: dict[str, SquadRole] = {}
    for role_name, players in raw.items():
        try:
            role = SquadRole(str(role_name))
        except ValueError:
            continue
        for entry in players or []:
            table[normalise(str(entry))] = role
    return RoleBook(table, source=str(target))


__all__ = ["RoleBook", "load_roles", "normalise"]
