# 1. GitHub Actions is the runtime

**Status:** accepted · 2026-09-08

## Context

The agent has to reach `fantasy-api.llt-services.com` on a schedule, at
precise minutes, without a machine being awake. Three candidate homes:

1. A laptop with a scheduled job. Free, but only runs while the lid is open —
   and the windows that matter open at 17:48 on weekdays and 00:15 at night.
2. A small VPS. Always on, but costs money, needs patching, and the credentials
   live on a box somebody has to secure.
3. GitHub Actions. Free for public repositories, always available, open network,
   and a secret store that is already audited.

## Decision

GitHub Actions, driven by cron, with state committed back to the repository.

## Consequences

- No server to own, and the credentials never leave GitHub's secret store.
- Scheduled workflows are best-effort and are frequently delayed by minutes.
  That is unacceptable for a clause opening at a fixed instant, so the schedule
  runs every five minutes through the 17:30–17:55 band rather than trusting a
  single trigger.
- There is no long-lived process, so nothing can hold a webhook open. This is
  why replies are polled rather than pushed — see
  [0003](0003-approval-in-advance.md), which makes that acceptable.
- Concurrency is capped at one run. Two overlapping runs would race on the state
  commit and, worse, could pay the same clause twice.
