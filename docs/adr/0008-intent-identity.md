# 8. What an intent is, and why the price is not part of it

**Status:** accepted · 2026-09-19

## Context

The agent became unusable, and the complaint was specific: the same signing was
put to the manager over and over — fifteen messages for one decision — until he
stopped reading any of them.

The obvious suspect was the approval machinery, and it was innocent. Approvals
are a state machine keyed by intent, a `PENDING` approval is not re-asked, and
that worked exactly as designed. The fault was one layer down, in what counted
as *the same intent*:

```python
raw = "|".join([kind, player_id, market_id, offer_id, str(amount),
                execute_at.isoformat(timespec="minutes")])
```

Two of those move on their own.

`amount` for a clause is `max(clause, market_value)`, and the game recomputes
every market value overnight. Observed on one real player over four days:
12,998,678 → 12,991,226 → 12,964,732 → 12,869,602. Four prices, four
identities, four times the manager was asked whether to sign the same man.

`execute_at` is worse. For an opportunity that is already open the planner sets
it to `max(opens_at, now)` — which is `now`. The workflow ran every fifteen
minutes. Ninety-six identities a day, for one decision.

## Decision

An intent is identified by **which operation, on which target, in which
window**. The window is an explicit `anchor`: the instant a clause opens, or a
matchday deadline. Nothing else.

The price is deliberately absent. Whether a moved price is still the same deal
is a question about *conditions*, and `Conditions.price_tolerance` already
answers it — that is the mechanism built for the job, with an explicit
tolerance and a revalidation step before execution. Encoding the price in the
identity did not add safety; it converted a working tolerance into a stream of
duplicates.

`execute_at` is absent for the same reason: it is a scheduling concern, and for
a live opportunity it is not a fact about the opportunity at all, just a
reading of the clock.

## Consequences

Two plans fifteen minutes apart over drifting prices produce identical keys.
There is a regression test that asserts exactly that, and it was also confirmed
against the live league before the fix shipped.

A rejection now sticks. Because identity no longer changes with the price, a
"no" stays a no instead of expiring overnight into a fresh question. Where the
situation genuinely changes, the conditions catch it and the approval returns
to the manager — which is the distinction that was missing all along.

A clause reopening in a fortnight is a different anchor and therefore a genuinely
new decision, which is correct: it is one.
