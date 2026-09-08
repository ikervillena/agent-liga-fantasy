"""Command line entry points.

The workflow calls these; a human can call the same ones locally to see exactly
what CI will do. `run` is the whole loop — perceive, plan, ask, execute — and
the individual commands exist so any single stage can be inspected on its own.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import typer

from .approvals import (
    Approval,
    ApprovalState,
    Observation,
    expire_stale,
    needs_asking,
    revalidate,
)
from .brief import ask_text, compose
from .config import POLICY_FILE, Settings
from .executor import Executor
from .intel.roles import load_roles
from .laliga.client import FantasyClient
from .models import LeagueState, PlayerStatus, SquadRole
from .notifier import build_notifier
from .planner import plan as build_plan
from .policy import Autonomy, Policy
from .storage import Store
from .sync import fetch_state

app = typer.Typer(add_completion=False, help="Autonomous manager for a LaLiga Fantasy squad.")


def _load(store: Store) -> LeagueState | None:
    raw = store.load_snapshot()
    return LeagueState.model_validate(raw) if raw else None


def _load_previous(store: Store) -> LeagueState | None:
    raw = store.load_previous()
    return LeagueState.model_validate(raw) if raw else None


@app.command()
def sync() -> None:
    """Fetch the league and write a fresh snapshot to state/."""
    policy = Policy.load(POLICY_FILE)
    store = Store()
    roles = load_roles()
    client = FantasyClient()
    state = fetch_state(client, policy.league_id, policy.team_id, roles)
    store.save_snapshot(state.model_dump(mode="json"))
    typer.echo(
        f"Snapshot saved: {len(state.teams)} teams, "
        f"{len(state.owned_players)} owned players, roles from {roles.source}."
    )


@app.command()
def plan() -> None:
    """Turn the current snapshot into intents and print them."""
    policy = Policy.load(POLICY_FILE)
    state = _load(Store())
    if state is None:
        typer.echo("No snapshot yet. Run `fantasy sync` first.")
        raise typer.Exit(code=1)

    intents = build_plan(state, policy, load_roles())
    if not intents:
        typer.echo("Nothing worth proposing.")
        return
    for intent in intents:
        typer.echo(f"{intent.key}  {intent.describe():<44} {intent.execute_at:%Y-%m-%d %H:%M}")
        typer.echo(f"           {intent.rationale}")


@app.command()
def brief() -> None:
    """Send the daily brief."""
    policy = Policy.load(POLICY_FILE)
    store = Store()
    state = _load(store)
    if state is None:
        typer.echo("No snapshot yet.")
        raise typer.Exit(code=1)

    intents = build_plan(state, policy, load_roles())
    approvals = store.load_approvals()
    build_notifier().send(compose(state, _load_previous(store), intents, approvals))
    typer.echo("Brief sent.")


@app.command()
def poll() -> None:
    """Read replies from the channel and apply them to pending approvals."""
    store = Store()
    notifier = build_notifier()
    replies, cursor = notifier.poll(store.load_cursor())
    approvals = {a.key: a for a in store.load_approvals()}
    now = datetime.now(UTC)
    changed = 0

    for reply in replies:
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
            notifier.send(ask_text(approval.intent))

    store.save_cursor(cursor)
    store.save_approvals(list(approvals.values()))
    typer.echo(f"{len(replies)} replies read, {changed} approvals updated.")


@app.command()
def run(
    dry_run: Annotated[bool, typer.Option(help="Never touch the API.")] = False,
) -> None:
    """The full loop: perceive, plan, revalidate, ask, execute."""
    policy = Policy.load(POLICY_FILE)
    store = Store()
    roles = load_roles()
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

    # 4. Ask about anything proposed or newly in doubt.
    for approval in approvals.values():
        if not needs_asking(approval):
            continue
        notifier.ask(ask_text(approval.intent), approval.key)
        approval.transition(ApprovalState.PENDING, now, "sent for approval")
        approval.asked_at = now

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

    roles = load_roles()
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
