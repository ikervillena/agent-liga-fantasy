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

import json
from datetime import date

import yaml

from fantasy.domain.models import SquadRole
from fantasy.settings import ROLES_FILE, STATE_DIR
from fantasy.sources.scouting.futbolfantasy import ScrapeError, build_index, fetch_roles
from fantasy.sources.scouting.roles import RoleBook, load_roles, normalise

#: Today's scrape, so the agent's schedule does not hammer somebody's website.
CACHE_FILE = STATE_DIR / "roles-cache.json"


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


def current(*, offline: bool = False, refresh: bool = False) -> RoleBook:
    """The role book to plan with, scraped at most once a day.

    The caching is not an optimisation, it is basic manners. Roles are read on
    every run of the agent, the agent runs on a schedule, and a scrape is
    twenty requests to somebody else's website. Without a cache a
    fifteen-minute cadence would mean nearly two thousand requests a day for
    data that changes twice a week.

    `offline` skips the network entirely; `refresh` forces a scrape even when
    today's cache exists.
    """
    manual = overrides()
    if offline:
        return load_roles()

    cached = _load_cache()
    if cached is not None and not refresh:
        table = build_index(cached)
        table.update(manual)
        return RoleBook(table, source=f"cache: {len(cached)} players, {len(manual)} overrides")

    try:
        scraped, failed = fetch_roles()
    except (ScrapeError, OSError) as exc:
        book = load_roles()
        book.source = f"{book.source} (scrape failed: {exc})"
        return book

    if scraped:
        _save_cache(scraped)

    table = build_index(scraped)
    table.update(manual)

    source = f"futbolfantasy: {len(scraped)} players, {len(manual)} manual overrides"
    if failed:
        source += f"; failed: {', '.join(failed)}"
    return RoleBook(table, source=source)


def _load_cache() -> dict[str, SquadRole] | None:
    """Today's scrape, or None if there isn't one."""
    if not CACHE_FILE.exists():
        return None
    try:
        raw = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if raw.get("fetched_on") != date.today().isoformat():
        return None

    roles: dict[str, SquadRole] = {}
    for name, value in (raw.get("roles") or {}).items():
        try:
            roles[str(name)] = SquadRole(str(value))
        except ValueError:
            continue
    return roles or None


def _save_cache(roles: dict[str, SquadRole]) -> None:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(
        json.dumps(
            {
                "fetched_on": date.today().isoformat(),
                "roles": {name: role.value for name, role in sorted(roles.items())},
            },
            ensure_ascii=False,
            indent=1,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


__all__ = ["current", "overrides"]
