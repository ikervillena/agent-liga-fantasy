"""Command line entry points.

The workflow calls these; a human can call the same ones locally to see exactly
what CI will do. `run` is the whole loop — perceive, plan, ask, execute — and
the individual commands exist so any single stage can be inspected on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer

from fantasy.agent.advisor import Advisor, AdvisorError
from fantasy.agent.ask import answer as ask_question
from fantasy.agent.ask import publish_briefing
from fantasy.agent.session import deliberate, enrich, remember
from fantasy.analysis.candidates import plan as build_plan
from fantasy.channel.telegram import Notifier, build_notifier
from fantasy.channel.wording import describe as describe_es
from fantasy.domain.approvals import (
    Approval,
    ApprovalState,
    Observation,
    expire_stale,
    needs_asking,
    revalidate,
)
from fantasy.domain.models import LeagueState, PlayerStatus, SquadRole
from fantasy.domain.policy import Autonomy, Policy
from fantasy.execution.executor import Executor
from fantasy.settings import POLICY_FILE, Settings
from fantasy.sources.laliga.client import FantasyClient
from fantasy.sources.scouting.resolve import current as current_roles
from fantasy.sources.scouting.roles import RoleBook
from fantasy.sources.sync import fetch_state
from fantasy.storage.state import Store
from fantasy.storage.values import ValueCache

app = typer.Typer(add_completion=False, help="Autonomous manager for a LaLiga Fantasy squad.")


def _load(store: Store) -> LeagueState | None:
    raw = store.load_snapshot()
    return LeagueState.model_validate(raw) if raw else None


def _answer_question(question: str, store: Store, now: datetime) -> str:
    """Answer one question from the channel, or say plainly why it could not.

    A failure here is reported to the manager rather than swallowed: an
    unanswered question in a chat window looks like the agent is broken, which
    is worse than an honest error.
    """
    state = _load(store)
    if state is None:
        return "Todavía no tengo una foto de la liga. Espera al próximo volcado."
    try:
        return ask_question(question, state, ValueCache().load(), now=now)
    except AdvisorError as exc:
        return f"No he podido responder: {exc}"


def _load_previous(store: Store) -> LeagueState | None:
    raw = store.load_previous()
    return LeagueState.model_validate(raw) if raw else None


#: Most decisions the manager is asked about in one go. Past about three, a
#: request for a decision stops reading as a question and starts reading as a
#: backlog, and backlogs get ignored wholesale. Anything not asked today is not
#: lost — it stays proposed and comes back when it actually becomes urgent.
MAX_ASKS = 3


def _ask_what_matters(
    waiting: list[Approval],
    state: LeagueState,
    policy: Policy,
    roles: RoleBook,
    notifier: Notifier,
    now: datetime,
    advisor: Advisor | None = None,
) -> None:
    """Put at most a few decisions to the manager, in a single message.

    The old loop sent one message per approval, so a run with a dozen of them
    sent a dozen walls of text. Volume was never a presentation problem: an
    agent that forwards its whole queue has not decided anything, it has just
    moved the work. So the judgment layer chooses what is worth raising now and
    writes the covering note; everything else waits without being mentioned.

    If the judgment layer cannot be reached the agent still asks, but only
    about the most imminent few, unexplained. Degrading to terse beats going
    silent on a clause that opens in an hour.
    """
    if not waiting:
        return

    by_key = {a.key: a for a in waiting}
    candidates = enrich([a.intent for a in waiting], roles)
    outcome = deliberate(state, policy, candidates, now=now, advisor=advisor or Advisor())

    chosen = [i.key for i in outcome.selection.intents][:MAX_ASKS]
    note = outcome.message

    if not chosen:
        if outcome.judgment is not None and not outcome.error:
            return  # judged: nothing here is worth interrupting for
        soonest = sorted(waiting, key=lambda a: a.intent.execute_at)[:MAX_ASKS]
        chosen = [a.key for a in soonest]
        note = "Tienes esto pendiente de decidir:"

    decisions: list[tuple[str, str]] = []
    lines = [note] if note else []
    for key in chosen:
        approval = by_key.get(key)
        if approval is None:
            continue
        lines.append(f"\n<b>{describe_es(approval.intent)}</b>\n{approval.intent.rationale}")
        decisions.append((key, approval.intent.player_name or describe_es(approval.intent)))

    if not decisions:
        return

    notifier.ask_many("\n".join(lines), decisions)
    for key, _ in decisions:
        approval = by_key[key]
        approval.transition(ApprovalState.PENDING, now, "sent for approval")
        approval.asked_at = now


@app.command()
def sync() -> None:
    """Fetch the league and write a fresh snapshot to state/."""
    policy = Policy.load(POLICY_FILE)
    store = Store()
    roles = current_roles()
    client = FantasyClient()
    state = fetch_state(client, policy.league_id, policy.team_id, roles)
    store.save_snapshot(state.model_dump(mode="json"))

    # Publish what the agent knows as plain files. The chat endpoint is a relay
    # that reads these and nothing else, so everything about *what* the agent
    # knows and *how* it speaks stays here, in one language, under test.
    published = publish_briefing(state, ValueCache().load(), now=datetime.now(UTC))
    typer.echo(
        f"Snapshot saved: {len(state.teams)} teams, "
        f"{len(state.owned_players)} owned players, roles from {roles.source}. "
        f"Briefing published ({published:,} chars)."
    )


@app.command()
def plan() -> None:
    """Turn the current snapshot into intents and print them."""
    policy = Policy.load(POLICY_FILE)
    state = _load(Store())
    if state is None:
        typer.echo("No snapshot yet. Run `fantasy sync` first.")
        raise typer.Exit(code=1)

    intents = build_plan(state, policy, current_roles())
    if not intents:
        typer.echo("Nothing worth proposing.")
        return
    for intent in intents:
        typer.echo(f"{intent.key}  {intent.describe():<44} {intent.execute_at:%Y-%m-%d %H:%M}")
        typer.echo(f"           {intent.rationale}")


@app.command()
def advise(
    send: Annotated[bool, typer.Option(help="Send the message instead of printing it.")] = False,
) -> None:
    """Put today's candidates to the judgment layer and show what it decides.

    Read-only with respect to the game: it proposes and explains, and nothing
    reaches the API from here. Printing by default so the reasoning can be read
    before anything is wired to Telegram.
    """
    policy = Policy.load(POLICY_FILE)
    store = Store()
    state = _load(store)
    if state is None:
        typer.echo("No snapshot yet. Run `fantasy sync` first.")
        raise typer.Exit(code=1)

    now = datetime.now(UTC)
    roles = current_roles()
    intents = build_plan(state, policy, roles, now=now)
    candidates = enrich(intents, roles, client=FantasyClient())

    outcome = deliberate(state, policy, candidates, now=now, advisor=Advisor())

    if outcome.error:
        typer.echo(f"The advisor could not answer: {outcome.error}")
        raise typer.Exit(code=1)
    if outcome.suppressed:
        typer.echo(f"({len(outcome.suppressed)} already communicated, not repeated)")
    if outcome.judgment is None or outcome.judgment.is_silent:
        typer.echo("Nothing worth saying right now.")
        return

    typer.echo(outcome.message or "(no message)")
    for intent in outcome.selection.intents:
        typer.echo(f"\n  → {describe_es(intent)}\n    {intent.rationale}")
    for discard in outcome.judgment.discarded:
        typer.echo(f"  no: {discard.key}: {discard.reason}")
    if outcome.selection.unknown_keys:
        ignored = ", ".join(outcome.selection.unknown_keys)
        typer.echo(f"  ! unrecognised keys ignored: {ignored}")

    if send and outcome.should_send:
        build_notifier().send(outcome.message)
        remember(outcome, candidates, at=now)
        typer.echo("\nSent.")


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="What to ask, in plain Spanish.")],
) -> None:
    """Ask the agent something about the league and print the answer."""
    store = Store()
    state = _load(store)
    if state is None:
        typer.echo("No snapshot yet. Run `fantasy sync` first.")
        raise typer.Exit(code=1)

    values = ValueCache().load()
    if values.is_stale():
        typer.echo("(prices are from an earlier day; run `fantasy values` to refresh)")
    try:
        typer.echo(ask_question(question, state, values, now=datetime.now(UTC)))
    except AdvisorError as exc:
        typer.echo(f"Could not answer: {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def values() -> None:
    """Refresh the cached price histories for every owned player."""
    store = Store()
    state = _load(store)
    if state is None:
        typer.echo("No snapshot yet. Run `fantasy sync` first.")
        raise typer.Exit(code=1)

    cache = ValueCache().load()
    updated = cache.refresh(FantasyClient(), [p.id for p in state.owned_players])
    cache.save()
    typer.echo(f"{updated} price histories refreshed, {len(cache)} cached.")


@app.command()
def poll() -> None:
    """Read replies from the channel: button presses, and questions.

    Anything that is not a button press is treated as a question and answered.
    That is what makes the channel a conversation rather than a notification
    feed — the manager can ask at any time, and the reply lands in the same
    thread as everything else.
    """
    store = Store()
    notifier = build_notifier()
    replies, cursor = notifier.poll(store.load_cursor())
    approvals = {a.key: a for a in store.load_approvals()}
    now = datetime.now(UTC)
    changed = 0
    answered = 0

    for reply in replies:
        if reply.get("kind") == "text":
            question = str(reply.get("text") or "").strip()
            if question:
                # Seen, then thinking, then the answer. Silence while a model
                # reasons reads as a broken bot, and these two calls cost
                # nothing next to the one that follows.
                message_id = reply.get("message_id")
                if isinstance(message_id, int):
                    notifier.acknowledge(message_id)
                notifier.typing()
                notifier.send(_answer_question(question, store, now))
                answered += 1
            continue
        if reply.get("kind") != "decision":
            continue
        approval = approvals.get(str(reply.get("decision")))
        if approval is None or approval.state.is_terminal:
            continue
        answer = str(reply.get("answer"))
        if answer == "yes":
            approval.transition(ApprovalState.APPROVED, now, "approved by manager")
            approval.decided_at = now
            changed += 1
        elif answer == "no":
            approval.transition(ApprovalState.REJECTED, now, "rejected by manager")
            approval.decided_at = now
            changed += 1
        elif answer == "explain":
            notifier.send(approval.intent.rationale)

    store.save_cursor(cursor)
    store.save_approvals(list(approvals.values()))
    typer.echo(f"{len(replies)} replies read, {changed} approvals updated, {answered} answered.")


@app.command()
def run(
    dry_run: Annotated[bool, typer.Option(help="Never touch the API.")] = False,
    execute_only: Annotated[
        bool,
        typer.Option(help="Fire what is already approved; do not judge or ask."),
    ] = False,
) -> None:
    """The full loop: perceive, plan, revalidate, ask, execute.

    `--execute-only` skips the judgment and the asking. The dense band around
    17:48 exists to fire an approval at the exact minute a clause opens, not
    to think: without this it deliberated on every pass, which is five model
    calls in twenty minutes to reach the same conclusion five times.
    """
    policy = Policy.load(POLICY_FILE)
    store = Store()
    roles = current_roles()
    notifier = build_notifier()
    now = datetime.now(UTC)

    # 1. Perceive.
    state = fetch_state(FantasyClient(), policy.league_id, policy.team_id, roles)
    store.save_snapshot(state.model_dump(mode="json"))

    # 2. Plan, keeping approvals we already hold.
    approvals = {a.key: a for a in store.load_approvals()}
    expire_stale(list(approvals.values()), now)

    for intent in build_plan(state, policy, roles, now):
        if intent.key in approvals:
            continue
        approval = Approval(intent=intent)
        if policy.may_act_alone(intent.amount):
            approval.transition(ApprovalState.APPROVED, now, "within the autonomy threshold")
        approvals[intent.key] = approval

    # 3. Revalidate what is already approved against the world as it is now.
    current = {p.id: p for p in state.owned_players}
    for approval in approvals.values():
        target = current.get(approval.intent.player_id or "")
        if target is None:
            continue
        revalidate(
            approval,
            Observation(
                price=target.buyout_clause or target.player.market_value,
                player_status=target.player.status or PlayerStatus.UNKNOWN,
                squad_role=target.player.role or SquadRole.UNKNOWN,
            ),
            now,
        )

    # 4. Ask — once, about the few things worth asking about.
    if not execute_only:
        _ask_what_matters(
            [a for a in approvals.values() if needs_asking(a)],
            state,
            policy,
            roles,
            notifier,
            now,
        )

    # 5. Execute what is approved and due.
    executor = Executor(FantasyClient(), policy, store, dry_run=dry_run)
    outcomes = executor.run(list(approvals.values()), now)

    store.save_approvals(list(approvals.values()))
    for outcome in outcomes:
        typer.echo(f"{outcome.status:<9} {outcome.key} {outcome.detail}")
    typer.echo(
        f"{len(approvals)} approvals tracked, {len(outcomes)} acted on "
        f"({'dry run' if dry_run else policy.autonomy.value})."
    )


@app.command()
def doctor() -> None:
    """Check configuration and connectivity without changing anything."""
    settings = Settings.from_env()
    ok = True

    typer.echo(f"policy file        {'found' if POLICY_FILE.exists() else 'MISSING'}")
    try:
        policy = Policy.load(POLICY_FILE)
        typer.echo(f"policy             valid · autonomy={policy.autonomy.value}")
        if policy.autonomy is Autonomy.SUPERVISED:
            typer.echo("                   every operation requires approval")
    except (OSError, ValueError) as exc:
        typer.echo(f"policy             INVALID: {exc}")
        ok = False

    typer.echo(f"laliga credentials {'present' if settings.can_authenticate else 'MISSING'}")
    typer.echo(f"telegram           {'configured' if settings.can_notify else 'not configured'}")

    roles = current_roles(offline=True)
    typer.echo(f"role book          {len(roles)} players from {roles.source}")
    if len(roles) == 0:
        typer.echo("                   without roles no signing passes the starter filter")

    store = Store()
    state = _load(store)
    typer.echo(f"snapshot           {'present' if state else 'none yet'}")
    if state:
        typer.echo(
            f"                   {state.fetched_at:%Y-%m-%d %H:%M} · {len(state.teams)} teams"
        )

    if settings.can_authenticate:
        try:
            FantasyClient().current_matchday()
            typer.echo("api                reachable")
        except Exception as exc:
            typer.echo(f"api                UNREACHABLE: {exc}")
            ok = False

    raise typer.Exit(code=0 if ok else 1)


if __name__ == "__main__":  # pragma: no cover
    app()
