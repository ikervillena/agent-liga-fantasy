# 6. Squad roles are scraped, with manual override

**Status:** accepted · 2026-09-19 · supersedes [0005](0005-curated-roles.md)

## Context

[0005](0005-curated-roles.md) chose to curate squad roles by hand. The reasoning
was sound: the data moves a couple of times a week, a bad parse would silently
approve a bench player, and a file under version control gives a diff and a
history of who counted as a starter when.

What it did not account for is that a curated file decays invisibly. The version
this project was running carried `last reviewed 2026-09-07` and was read on
2026-09-19 — twelve days stale, over a stretch containing two matchdays. It held
301 names, entered by hand, covering part of the league.

A stale role book does not look stale. It looks like an opinion, and the starter
filter is the most load-bearing filter in the system.

## Decision

Scrape the roles; keep the file as an override that always wins.

The scraper reads each club's hierarchy page and takes only the tier. Market
values are deliberately not read from it: the game's own API is authoritative
for those, and cross-reading would invite a disagreement with no tie-breaker.

Run against the live league this yields 503 players across all twenty clubs,
refreshed daily and cached so a scheduled agent does not make two thousand
requests a day to somebody else's website.

## Consequences

The property that made 0005 worth choosing survives: a human still has the last
word, in version control, with a diff and a date. What is gone is the silent
decay, because the scraped layer underneath refreshes itself.

The sources disagree about names — the site writes "Aissa Mandi" where the game
says "Mandi" — so players are indexed under full name and surname, with accents
folded because the two sources and a human typing an override all disagree about
those as well. Where a surname is ambiguous across tiers it is indexed nowhere
and resolves to `unknown`, which fails the starter filter.

That last point is the safety property, and it holds for the whole design: a
broken scrape leaves players unknown, an unknown role fails the filter, and the
agent proposes no signings while still watching, shielding and reporting. It
degrades to cautious rather than to wrong.
