"""Squad roles, scraped instead of hand-maintained.

This replaces a curated file, and the reason is only partly effort. A reviewed
file was the right call while nothing else existed, but it decays silently: the
version this project shipped with was last reviewed twelve days before it was
read, over a stretch in which two of the players it called starters had stopped
starting. A stale role book does not look stale — it looks like an opinion.

So the file stays, demoted to an override. What the scraper cannot see, or gets
wrong, is corrected by hand in `config/overrides.yml` and wins. That keeps the
one property the curated design had and the scraper alone would lose: a human
can always have the last word, in version control, with a diff.

Two deliberate limits:

* Only the tier is taken. Market values come from the game's own API, which is
  authoritative and needs no parsing — cross-reading them here would invite a
  disagreement with no tie-breaker.
* Nothing is inferred from silence. A club page that fails to parse leaves its
  players UNKNOWN, which fails the starter filter, so a broken scrape makes the
  agent cautious rather than wrong.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import httpx
from selectolax.parser import HTMLParser

from fantasy.domain.models import SquadRole
from fantasy.settings import USER_AGENT

if TYPE_CHECKING:
    from fantasy.sources.scouting.roles import RoleBook

BASE = "https://www.futbolfantasy.com"
SEED_CLUB = "levante"

#: One request a second. We are an unannounced guest on somebody's website.
REQUEST_INTERVAL = 1.0

#: Section heading on the club page to the role it means. The headings are the
#: only reliable marker: the surrounding CSS classes are reused across
#: unrelated blocks on the same page.
TIER_HEADINGS: dict[str, SquadRole] = {
    "clave": SquadRole.KEY,
    "importantes": SquadRole.IMPORTANT,
    "rotación": SquadRole.ROTATION,
    "rotacion": SquadRole.ROTATION,
    "revulsivos": SquadRole.IMPACT_SUB,
    "reservas": SquadRole.BENCH,
    "descartes": SquadRole.BENCH,
}


class ScrapeError(RuntimeError):
    pass


def club_url(slug: str) -> str:
    return f"{BASE}/laliga/equipos/{slug}/jerarquias"


def discover_clubs(html: str) -> list[str]:
    """Every club slug the site links to, read off any club page.

    Discovered rather than hard-coded so that promotion and relegation do not
    need a code change every August.
    """
    tree = HTMLParser(html)
    slugs: set[str] = set()
    for link in tree.css("a"):
        href = link.attributes.get("href") or ""
        marker = "/laliga/equipos/"
        if marker not in href:
            continue
        tail = href.split(marker, 1)[1].strip("/")
        slug = tail.split("/", 1)[0]
        if slug:
            slugs.add(slug)
    return sorted(slugs)


def parse_roles(html: str) -> dict[str, SquadRole]:
    """Player name to role for one club page.

    Players appear more than once on the page — a tier block and an injury
    block can both list the same man — so the first tier seen wins and later
    mentions are ignored.
    """
    tree = HTMLParser(html)
    found: dict[str, SquadRole] = {}

    for section in tree.css("section"):
        heading = section.css_first(".titulo, .title, h2, h4, h5, .cabecera")
        if heading is None:
            continue
        label = (heading.text() or "").strip().lower()
        role = TIER_HEADINGS.get(label)
        if role is None:
            continue
        for anchor in section.css("a.jugador"):
            name = (anchor.text() or "").strip()
            if name and name not in found:
                found[name] = role
    return found


def fetch_roles(
    clubs: list[str] | None = None,
    *,
    client: httpx.Client | None = None,
) -> tuple[dict[str, SquadRole], list[str]]:
    """Scrape every club. Returns the roles and the clubs that failed.

    Failures are returned rather than raised: nineteen clubs of usable data
    beats none, and the caller needs to be able to say which club is missing.
    """
    http = client or httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": USER_AGENT}
    )
    owns_client = client is None
    try:
        if clubs is None:
            clubs = discover_clubs(_get(http, club_url(SEED_CLUB)))

        roles: dict[str, SquadRole] = {}
        failed: list[str] = []
        for index, slug in enumerate(clubs):
            if index:
                time.sleep(REQUEST_INTERVAL)
            try:
                page = _get(http, club_url(slug))
            except (httpx.HTTPError, ScrapeError):
                failed.append(slug)
                continue
            parsed = parse_roles(page)
            if not parsed:
                failed.append(slug)
                continue
            roles.update(parsed)
        return roles, failed
    finally:
        if owns_client:
            http.close()


def build_index(scraped: dict[str, SquadRole]) -> dict[str, SquadRole]:
    """Index scraped players under every name the game might call them.

    The two sources disagree on names by design: the scouting site writes
    "Aissa Mandi" where the game says "Mandi". So each player is indexed under
    his full name *and* under his surname alone.

    Surnames collide, and the collision is handled by refusing to guess. Where
    two players share one and sit in different tiers, that surname is indexed
    nowhere: it resolves to UNKNOWN, which fails the starter filter. Two
    players in the same tier are not a problem — either answer is the same
    answer — so that alias is kept.
    """
    from fantasy.sources.scouting.roles import normalise

    index: dict[str, SquadRole] = {normalise(name): role for name, role in scraped.items()}

    surnames: dict[str, set[SquadRole]] = {}
    for name, role in scraped.items():
        parts = normalise(name).split()
        if len(parts) > 1:
            surnames.setdefault(parts[-1], set()).add(role)

    for surname, roles in surnames.items():
        if surname in index:
            continue  # a full name already owns this key; do not shadow it
        if len(roles) == 1:
            index[surname] = next(iter(roles))
    return index


def role_book(
    overrides: dict[str, SquadRole] | None = None,
    *,
    clubs: list[str] | None = None,
    client: httpx.Client | None = None,
) -> RoleBook:
    """A role book from the site, with manual corrections layered on top."""
    from fantasy.sources.scouting.roles import RoleBook, normalise

    scraped, failed = fetch_roles(clubs, client=client)
    table = build_index(scraped)
    for name, role in (overrides or {}).items():
        table[normalise(name)] = role

    source = f"futbolfantasy ({len(scraped)} players)"
    if failed:
        source += f", failed: {', '.join(failed)}"
    return RoleBook(table, source=source)


def _get(http: httpx.Client, url: str) -> str:
    response = http.get(url)
    if response.status_code >= 400:
        raise ScrapeError(f"HTTP {response.status_code} on {url}")
    return response.text


__all__ = [
    "TIER_HEADINGS",
    "ScrapeError",
    "club_url",
    "discover_clubs",
    "fetch_roles",
    "parse_roles",
    "role_book",
]
