# 3. Approval is asked in advance

**Status:** accepted · 2026-09-08

## Context

Autonomy and control usually trade off. An agent that asks before every action
misses anything that happens while nobody is looking; one that never asks is not
something you point at a real account.

The observation that dissolves the trade-off: in this game almost nothing is a
surprise. A buyout clause opens exactly fourteen days after its owner signed the
player. The free-agent market refreshes at 00:15. A matchday closes with its
first kick-off. The *window* is deterministic; only the price and the team news
are not.

## Decision

The agent plans seven days ahead and asks for approval when it forms the
intention, not when the moment arrives. At the moment itself it revalidates and
executes.

## Consequences

- Decisions are made with hours or days of thought instead of thirty seconds.
- Execution is unattended even for large operations, because the yes already
  exists.
- Replies can be polled rather than pushed. A fifteen-minute lag on a decision
  taken yesterday costs nothing, which is what allows the whole system to live
  inside scheduled CI with no always-on process.
- It creates an obligation: an approval given on Monday must not be honoured
  blindly on Thursday. See [0004](0004-revalidation.md).
