"""How an operation is said out loud, in Spanish.

The domain speaks English because the code does, and `Intent.describe()`
produces "Raise clause on Mandi" — fine in a log, wrong in the chat, where it
had been leaking into every approval request alongside Spanish prose.

Presentation belongs to the channel, so the translation lives here rather than
in the domain. Nothing in `domain/` should know which language the reader
speaks, and nothing here should know how a clause works.
"""

from __future__ import annotations

from fantasy.domain.intents import Intent, IntentKind

_PHRASE: dict[IntentKind, str] = {
    IntentKind.PAY_CLAUSE: "Pagar la cláusula de {name}",
    IntentKind.RAISE_CLAUSE: "Blindar a {name}",
    IntentKind.BID: "Pujar por {name}",
    IntentKind.SELL: "Poner a la venta a {name}",
    IntentKind.ACCEPT_OFFER: "Aceptar la oferta por {name}",
    IntentKind.REJECT_OFFER: "Rechazar la oferta por {name}",
    IntentKind.SET_LINEUP: "Cambiar la alineación",
}


def money(amount: float) -> str:
    """43.148.521 becomes '43,15 M', which is how it is read here."""
    return f"{amount / 1e6:.2f} M".replace(".", ",")


def describe(intent: Intent) -> str:
    """One line naming the operation and what it costs."""
    name = intent.player_name or intent.market_id or ""
    phrase = _PHRASE[intent.kind].format(name=name).strip()
    if intent.kind is IntentKind.SET_LINEUP:
        return phrase
    return f"{phrase} · {money(intent.amount)}"


__all__ = ["describe", "money"]
