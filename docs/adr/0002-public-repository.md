# 2. The repository is public

**Status:** accepted · 2026-09-08

## Context

An earlier design used two repositories: a private one for the code and a public
one holding only state, so that the state could be read without credentials.
That split existed purely to work around access, and it dragged in a personal
access token to let the workflow write across the boundary.

## Decision

One public repository. State is committed by the workflow using the built-in
`GITHUB_TOKEN`.

## Consequences

- The personal access token disappears from the design entirely. Two secrets
  remain for LaLiga and two for Telegram.
- Anyone can read the repository. What it contains is the source, and the state
  of a fantasy football league. Nothing else.
- Secrets work the same way in public repositories provided no workflow is
  triggered by pull requests from forks. Ours are triggered by schedule, by
  pushes to `main`, and manually — never by a fork.
- The repository doubles as a portfolio piece, which is worth something on its
  own.
