# 4. What happens when conditions change

**Status:** accepted · 2026-09-08

## Context

[0003](0003-approval-in-advance.md) means approvals are held for days. The world
moves in between: prices drift nightly, players get injured, managers drop
people. Honouring a stale approval is how an agent buys an injured player for
forty million.

The tempting answer — always ask again — is worse than it looks. The clause
opens at a fixed minute; if the answer arrives late, the window is gone and a
rival has the player.

## Decision

Approval is granted to a *situation*, recorded on the intent as `Conditions`.
Before executing, the agent compares the situation to the world as it is now:

| what changed | what happens |
| --- | --- |
| price moved within the agreed tolerance (5% by default) | approval stands |
| price moved beyond it | back to the manager |
| injury, suspension, unavailability | back to the manager |
| lost his starting place | back to the manager |
| squad role unknown (source missing) | approval stands |

## Consequences

- Silence has a defined meaning, and it differs by cause. That asymmetry is the
  point: missing a window is recoverable, buying a broken asset is not.
- The last row matters more than it looks. An unknown role means our scouting
  file lost the player, not that he was dropped. Absence of evidence must not
  cancel a deal the manager approved — the price and availability checks still
  apply either way.
- Every transition is recorded, so "why did it not buy?" always has an answer.
