# fantasy-agent

An autonomous agent that manages a LaLiga Fantasy squad — watching the market,
planning signings days ahead, asking for approval on Telegram, and executing at
the exact minute a buyout clause opens.

It runs entirely on GitHub Actions. There is no server, no database and no
always-on process.

```
                 every 15 min ·  00:20 ·  17:30–17:55 ·  08:00
                                    │
   LaLiga API ──────► perceive ──► plan ──► decide ──► act ──► LaLiga API
                          │          │        │  ▲
                          ▼          ▼        ▼  │ approve / reject
                      state/*.json  intents  Telegram
                      (committed)
```

## Why it is shaped this way

**Approval comes before the moment, not during it.** A buyout clause opens
exactly fourteen days after its owner signed the player, so the opportunity is
known days in advance and only the price is uncertain. The agent shows its hand
early, collects a decision while there is time to think, and then executes
unattended. That is what makes real autonomy compatible with real control.

**An approval is granted to a situation, not to a blank cheque.** Before firing,
the agent re-checks what it showed you. A price that moved inside the agreed
tolerance is still the same deal and proceeds; an injury, a suspension or a lost
starting place is not, and goes back to you. Missing a window is recoverable.
Buying an injured player for forty million is not.

**The policy is data, not code.** [`policy.yml`](policy.yml) is the only thing
that grants permission. It can be read in one sitting, changed without a deploy,
and is validated on load — a misspelled limit is a startup error rather than a
signing nobody intended.

**The domain has no idea the network exists.** Clause mechanics, squad
selection and planning are pure functions over typed models, so the decisions
that cost money are tested exhaustively without a single HTTP call.

## Layout

```
src/fantasy_agent/
  models.py       typed domain: players, squads, clause windows, league state
  rules.py        game mechanics as pure functions, each verified against live data
  intents.py      what to do and when, with a deterministic key per operation
  approvals.py    the approval state machine, including revalidation
  policy.py       policy.yml, parsed and validated
  planner.py      league state + policy → dated, priced, justified intents
  executor.py     the only module that changes anything
  brief.py        the daily message
  sync.py         perception: API → LeagueState
  storage.py      state files, committed to git for free history
  notifier.py     Notifier port; Telegram implementation
  cli.py          sync · plan · brief · poll · run · doctor
  laliga/         API adapter: auth, transport, mapping
  intel/          scouting adapter: squad roles
tests/            unit tests, no network
policy.yml        what the agent is allowed to do
intel/roles.yml   who actually starts for their club
```

## Running it

```bash
pip install -e ".[dev]"

export FANTASY_EMAIL=...      # never committed; in production these are
export FANTASY_PASSWORD=...   # GitHub Actions secrets
export TELEGRAM_TOKEN=...
export TELEGRAM_CHAT_ID=...

fantasy doctor     # configuration and connectivity, changes nothing
fantasy sync       # fetch the league into state/
fantasy plan       # show what it would propose
fantasy run --dry-run
```

`fantasy run` is the whole loop: perceive, plan, revalidate, ask, execute.

## Autonomy

`policy.yml` opens in `supervised`, where every operation waits for a yes. The
agent is fully built in that mode — it watches, plans, explains and asks; what
holds it back is policy, not missing code. Widening it later is one line:

| mode | behaviour |
| --- | --- |
| `supervised` | nothing reaches the API without an explicit approval |
| `mixed` | acts alone below `auto_below`, asks above it |
| `autonomous` | acts alone within the hard limits |

Independently of the mode, every operation is checked against per-operation,
per-run and per-day limits, and everything that happens — including everything
refused — is appended to `state/decisions.jsonl`.

## Testing

```bash
pytest          # unit tests, no network
ruff check src tests
mypy            # strict
```

CI runs all four on every push.

## Design notes

Decisions with a rationale worth keeping live in [`docs/`](docs/):

- [Why GitHub Actions is the runtime](docs/0001-github-actions-runtime.md)
- [Why the repository is public](docs/0002-public-repository.md)
- [Why approval is asked in advance](docs/0003-approval-in-advance.md)
- [What happens when conditions change](docs/0004-revalidation.md)
- [Why squad roles are curated by hand](docs/0005-curated-roles.md)
