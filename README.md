# fantasy-agent

An agent that manages a LaLiga Fantasy squad: it watches the market, judges
which opportunities are worth taking, asks before spending, answers questions in
plain Spanish, and executes at the minute a buyout clause opens.

It runs on GitHub Actions. There is no server and no always-on process.

```
  LaLiga API ─┐
futbolfantasy ─┼─► sources ─► domain ─► analysis ─► agent ─► channel ─► Telegram
  price history ┘            (rules)   (candidates) (Claude)    ▲          │
                                │                               └──────────┘
                                └──► execution ──► LaLiga API      approve / ask
```

## How it is put together

**The domain does not know the network exists.** Clause mechanics, matchday
deadlines and solvency are pure functions over typed models, so the decisions
that cost money are tested exhaustively without a single HTTP call.

**The model chooses; it never invents.** `analysis/` reduces seven hundred
players to the operations that are legal, affordable and relevant. Claude is
handed that shortlist and picks among it *by key*, returning a validated
schema. An invented player, a changed price or an illegal operation cannot be
expressed in the answer — the worst a confused reply can do is select something
already on the table, or nothing at all.

**Silence is a first-class answer.** Most hours of most days there is nothing
worth saying, and the agent says nothing. What it has already told you is
recorded, so it does not tell you again unless the facts underneath have
changed.

**The policy is data, not code.** [`config/policy.yml`](config/policy.yml) is
the only thing that grants permission. It reads in one sitting, changes without
a deploy, and is validated on load — a misspelled limit is a startup error
rather than a signing nobody intended.

## Layout

```
src/fantasy/
  domain/      models · rules · policy · intents · approvals   ← pure, no I/O
  sources/     laliga (auth, client, prices) · scouting · sync
  analysis/    valuation · candidates
  agent/       briefing · advisor · selection · ask · prompts/
  channel/     telegram · brief · ledger
  execution/   executor                                        ← the only writer
  storage/     state · values
  cli.py
tests/         unit · fixtures (real captured payloads) · evals
config/        policy.yml · roles.yml
docs/adr/      why things are the way they are
```

## Using it

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"

export FANTASY_EMAIL=... FANTASY_PASSWORD=...      # in production, GitHub secrets
export TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...
export ANTHROPIC_API_KEY=...

fantasy doctor                       # configuration and connectivity, changes nothing
fantasy sync                         # fetch the league into state/
fantasy plan                         # the candidate operations, deterministic
fantasy advise                       # what the judgment layer makes of them
fantasy ask "¿hay algún clausulazo interesante ahora mismo?"
fantasy run --dry-run                # the whole loop, touching nothing
```

## Talking to it

Anything you send the Telegram bot that is not a button press is treated as a
question and answered against the current league — who is appreciating fastest,
whether a clause is worth taking, what a signing would do to your balance
before kick-off. The `chat` workflow reads the channel every five minutes.

## Autonomy

`config/policy.yml` opens in `supervised`, where every operation waits for a
yes. The agent is fully built in all three modes; what holds it back is policy,
not missing code.

| mode | behaviour |
| --- | --- |
| `supervised` | nothing reaches the API without an explicit approval |
| `mixed` | acts alone below `auto_below`, asks above it |
| `autonomous` | acts alone within the hard limits |

Whatever the mode, every operation is checked against per-operation, per-run and
per-day limits, and everything that happens — including everything refused — is
appended to `state/decisions.jsonl`.

An approval is granted to a situation, not as a blank cheque. Before firing, the
agent re-checks what it showed you: a price that drifted inside the agreed
tolerance is the same deal and proceeds; an injury, a suspension or a lost
starting place is not, and comes back to you.

## When it runs

| moment | why then |
| --- | --- |
| 00:20 | straight after the nightly revaluation |
| 08:00 | the morning read |
| 15:45 | about two hours before the market closes |
| 17:40–18:00 | clause windows open at 17:48 |
| every 5 min | the chat |

## Testing

```bash
pytest                      # no network
ruff check src tests
mypy                        # strict
```

Adapters are tested against real captured payloads rather than hand-made
samples, because the failure that matters is an upstream shape changing.

## Design notes

Decisions with a rationale worth keeping live in [`docs/adr/`](docs/adr/):

- [Why GitHub Actions is the runtime](docs/adr/0001-github-actions-runtime.md)
- [Why the repository is public](docs/adr/0002-public-repository.md)
- [Why approval is asked in advance](docs/adr/0003-approval-in-advance.md)
- [What happens when conditions change](docs/adr/0004-revalidation.md)
- [Why squad roles were curated by hand](docs/adr/0005-curated-roles.md) — superseded
- [Squad roles are scraped, with manual override](docs/adr/0006-scraped-roles.md)
- [One structured call, not a tool loop](docs/adr/0007-judgment-layer.md)
- [What an intent is, and why the price is not part of it](docs/adr/0008-intent-identity.md)
