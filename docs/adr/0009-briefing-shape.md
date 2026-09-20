# 0009 — The briefing is the reasoning

Status: accepted

## Context

The agent gave generic advice. The working assumption was that this was a
prompting problem, and two rounds of prompt work did not move it.

It was not a prompting problem. The briefing handed to the model was a single
table of every owned player in the league, a hundred and forty-four rows,
sorted by the owner's manager name, carrying eleven fields. Our own fourteen
players sat scattered through it in exactly the format used for everyone
else's, under a heading that read "your squad and the reachable clauses".

That shape makes several questions unanswerable no matter how the model is
asked:

- *What is my squad short of?* — the squad is not visible as a squad.
- *Who can a rival take from me?* — our own clause appeared in the same column
  as a rival's, so it read as a price to pay rather than an exposure to cover.
- *Is he worth signing?* — the only performance field was the season average.
  A 6.86 earned across two substitute appearances and across seven starts are
  the same number in that table and opposite decisions in the game.
- *Is he fit?* — `PlayerStatus` was modelled, parsed and stored, and never
  printed. An injured player appeared as his last healthy average and nothing
  else, so recommending him was not a lapse of judgment; it was the only thing
  the text permitted.

The instinct in each case is to add a rule to the prompt. A rule cannot
reference a fact the briefing does not contain.

## Decision

The briefing is treated as the reasoning surface, and shaped by the decisions
it has to support rather than by what the API happens to return.

- **Our squad is its own section**, by position, with the points, the matchday
  count behind the average, availability, and the clause stated as what a rival
  would pay to take him.
- **Rivals are ordered by scoring average**, not by their owner's name, because
  that is the order in which a signing question is asked.
- **Availability and the matchday count are printed.** Both were already in the
  domain model.
- **Price movement carries its percentage**, since euros per day does not
  compare across a five million player and a hundred million one.
- **The system prompt states the mechanics that make those fields mean
  something** — what a clause premium destroys, what the fourteen-day lock does
  and does not cover, why role beats average — rather than only the tone.

## Consequences

The briefing grew by about two per cent, and the system prompt roughly doubled.
Both sit in the cached prefix, so the marginal cost of a question is unchanged
in practice.

`Valuation.bids` was removed from the briefing rather than added to it. It is
documented in three places as the only demand signal the game exposes and is
zero across all 9,574 observations on record: the endpoint does not return the
field. Printing it would have told the model that nobody in the league wants
anybody. The field stays in the model, unused, until the endpoint is
re-examined.

`Player.matchdays_played` now falls back to dividing the total by the average.
`weekPoints` arrives on the competition-wide player and not on the one nested
in a squad, so every player we hold reported zero matchdays played.

The failure mode this leaves is the model over-extending a rule it was given.
It was told the fourteen-day lock protects a signing from being clause-bought,
and it inferred — and stated as fact — that the player could therefore be
resold freely inside that window. The prompt now marks that specific question
as unknown. The general lesson is that a half-stated rule is worse than no
rule, because the model will complete it.
