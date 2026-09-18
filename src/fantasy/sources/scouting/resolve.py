"""Where squad roles actually come from, and in what order of authority.

Two sources, and the precedence is the whole design:

1. The scraper, which is current but can be wrong or absent.
2. `config/roles.yml`, which is hand-written, reviewed, and always wins.

The file used to be the only source. Demoting it to an override rather than
deleting it keeps the property that made it worth having — a human can correct
the agent in version control, with a diff and a date — while removing the one
that made it dangerous, which is that nobody notices when it goes stale.

A failed scrape is not an error. It falls back to the file alone, which leaves
most players UNKNOWN, which fails the starter filter. The agent then watches,
shields and reports but proposes no signings: cautious, not broken.
"""

from __future__ import annotations

import yaml

from fantasy.domain.models import SquadRole
from fantasy.settings import ROLES_FILE
from fantasy.sources.scouting.futbolfantasy import ScrapeError, build_index, fetch_roles
from fantasy.sources.scouting.roles import RoleBook, load_roles, normalise


def overrides() -> dict[str, SquadRole]:
    """The hand-written corrections, read from the same file as before."""
    if not ROLES_FILE.exists():
        return {}
    raw = yaml.safe_load(ROLES_FILE.read_text(encoding="utf-8")) or {}
    table: dict[str, SquadRole] = {}
    for role_name, players in raw.items():
        try:
            role = SquadRole(str(role_name))
        except ValueError:
            continue
        for entry in players or []:
            table[normalise(str(entry))] = role
    return table


def current(*, offline: bool = False) -> RoleBook:
    """The role book to plan with.

    `offline` skips the network entirely, which is what the tests and any
    air-gapped run want.
    """
    manual = overrides()
    if offline:
        return load_roles()

    try:
        scraped, failed = fetch_roles()
    except (ScrapeError, OSError) as exc:
        book = load_roles()
        book.source = f"{book.source} (scrape failed: {exc})"
        return book

    table = build_index(scraped)
    table.update(manual)

    source = f"futbolfantasy: {len(scraped)} players, {len(manual)} manual overrides"
    if failed:
        source += f"; failed: {', '.join(failed)}"
    return RoleBook(table, source=source)


__all__ = ["current", "overrides"]
