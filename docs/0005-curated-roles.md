# 5. Squad roles are curated, not scraped

**Status:** accepted · 2026-09-08

## Context

The single most valuable filter in the system is whether a player actually
starts for his club. A 9.0 average built on three substitute appearances
regresses to nothing, and buying exactly that has cost us money more than once.

The game API says nothing about it. The information exists on scouting sites,
in a hierarchy of key / important / rotation / impact sub / bench.

## Decision

Roles live in `intel/roles.yml`, a hand-curated file under version control, not
in a scraper.

## Consequences

- A wrong parse cannot silently approve a bench player. A file that has been
  read by a human can only be wrong on purpose.
- Version control gives the history of who counted as a starter and when, which
  is exactly the context needed to review a decision after the fact.
- It has to be refreshed by hand, roughly weekly. Acceptable: the data moves
  slowly and the review is the point, not the overhead.
- Anyone missing resolves to `unknown`, which fails the starter filter. Silence
  means "do not buy", never "probably fine". Without the file the agent still
  watches, shields and reports; it just proposes no signings.
