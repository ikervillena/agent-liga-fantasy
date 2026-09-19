# The chat relay

GitHub Actions is not a chat transport. A workflow scheduled every five minutes
ran **twice in nine hours** — GitHub drops high-frequency cron under load — so
questions sat unanswered for hours and then arrived three at once.

A webhook fixes that, and a webhook needs something always listening. That is
this Worker, and it is deliberately the dumbest part of the system: it holds no
opinion about fantasy football. `fantasy sync` publishes `state/digest.txt` and
`state/persona.txt`; the Worker fetches them, posts them to the model verbatim,
and sends back what comes out. If this file ever starts making decisions, that
is the bug.

Cloudflare rather than Vercel for one concrete reason: its free limit is **CPU
time** (10 ms), and time spent waiting on a `fetch` does not count against it. A
model call is eleven seconds of waiting and almost no CPU. Vercel's Hobby plan
caps a function at ten seconds of wall clock, which this would exceed on every
single question.

## Setting it up

1. **Deploy.** At [dash.cloudflare.com](https://dash.cloudflare.com) → Workers →
   Create → paste `worker.js`. Note the URL it gives you.

2. **Secrets.** In the Worker's Settings → Variables, add as *encrypted*:

   | name | value |
   |---|---|
   | `ANTHROPIC_API_KEY` | the same workspace-scoped key |
   | `TELEGRAM_TOKEN` | the bot token |
   | `TELEGRAM_CHAT_ID` | your chat id |
   | `WEBHOOK_SECRET` | any long random string you invent |
   | `GITHUB_TOKEN` | a fine-grained token with *Contents: read and write* on this repo only |

3. **Point Telegram at it.** Once, from a terminal:

   ```bash
   curl -s "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://<your-worker>.workers.dev" \
     -d "secret_token=<WEBHOOK_SECRET>"
   ```

4. **Check it.** Open `https://<your-worker>.workers.dev/health`. It reports
   which secrets are set (never their values), whether the token and the chat
   id actually work, and how much of the briefing it can read — and sends a
   confirmation to the chat if it can. Then `getWebhookInfo` should show the
   URL with no `last_error_message`.

   Telegram reporting a clean delivery is not proof: the relay returns 200 the
   moment it accepts an update and does the real work afterwards, so a bad
   secret shows up as silence, not as an error. That is what `/health` is for.

## What runs where, afterwards

| | where | when |
|---|---|---|
| answering questions | this Worker | instantly, always |
| button presses | Worker → dispatch → Actions | a minute |
| clauses, shields, pre-matchday, the brief | Actions | on schedule |

Setting a webhook disables `getUpdates`, so nothing polls Telegram any more.
That is why button presses travel as a `repository_dispatch`: the approval state
lives in the repository and is applied there, by `fantasy decide`.

## Cost

Cloudflare's free plan covers 100,000 requests a day; this uses a handful. The
model is the only real cost: **$0.04** for a question and **$0.01** for a
follow-up, which re-reads the cached digest.
