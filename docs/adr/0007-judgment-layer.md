# 7. One structured call, not a tool loop

**Status:** accepted · 2026-09-19

## Context

The agent could plan but could not judge. Everything it proposed was ranked by
one number — the season scoring average — which is backward-looking and, worse,
was also used as an entry filter. A key starter returning from two months out
carries a poor average that says nothing about what he will do next, so the
single most profitable kind of signing was rejected before anything could think
about it. Appreciation, which is how a squad outgrows a league without scoring
an extra point, was invisible entirely.

That gap is judgment, and it is what a language model is actually good at.

The default shape for this in 2026 is an agentic tool loop: hand the model tools
and let it explore. It was considered and rejected.

## Decision

One structured call per decision moment.

The deterministic layers narrow first: rules discard what is illegal, the policy
discards what is unaffordable, the ledger discards what has already been said.
What reaches the model is a handful of operations and a few dozen lines of
evidence — role, price trajectory, the shape of the squad, the deadline.

The model answers in a schema: which candidates are worth acting on **by key**,
why, what it passed over, and whether there is anything worth saying at all.

## Consequences

A loop earns its cost when the model must explore a space too large to hand
over. That is not this problem — the candidate list is already small — so a loop
would have bought nothing and cost reproducibility, latency and the ability to
test an answer against a recorded fixture.

Containment is structural rather than hoped for. Because a pick is a key into a
list the domain built, a model that hallucinates a player, alters a price or
proposes an illegal operation cannot express any of it: an unknown key resolves
to nothing and is reported. The worst a confused or adversarial answer achieves
is selecting something already on the table, or nothing.

`worth_saying: false` makes silence a real answer rather than an absence of one,
which is what the previous design lacked: it filled every run with a restated
league table until nobody read it.

The cost is a few cents a day. The scheduled proposals use Opus and the frequent
triage uses Sonnet; the system prompt and schema are stable, so they sit in a
cached prefix and the volatile briefing goes last.

If the state ever outgrows one turn — questions over the full league already
push a larger briefing — the seam to add tools is the briefing, not the loop.
