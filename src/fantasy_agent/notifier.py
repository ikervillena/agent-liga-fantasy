"""The conversation channel.

`Notifier` is the port; `TelegramNotifier` is today's implementation. Nothing
else in the codebase knows Telegram exists, so moving to WhatsApp — which needs
a verified business account and approved templates, hence not on day one — is a
new class here and nothing else.

Replies arrive by polling rather than a webhook. GitHub Actions cannot hold a
socket open, and it does not need to: approvals are given in advance, so a
fifteen-minute lag on a decision made yesterday costs nothing. The polling
cursor lives in the repository, which is what stops a reply being processed
twice and an operation being executed twice.
"""

from __future__ import annotations

import time
from typing import Any, Protocol

import httpx

from .config import Settings

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
MAX_MESSAGE = 3_900  # Telegram's hard limit is 4096; leave room for markup


class Reply(dict[str, Any]):
    """Either a tapped button (`decision`, `answer`) or free text (`text`)."""


class Notifier(Protocol):
    def send(self, text: str) -> None: ...

    def ask(self, text: str, decision_key: str) -> None: ...

    def poll(self, cursor: int) -> tuple[list[Reply], int]: ...


class ConsoleNotifier:
    """Used in tests and when no credentials are configured."""

    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, text: str) -> None:
        self.sent.append(text)
        print(text)

    def ask(self, text: str, decision_key: str) -> None:
        self.send(f"{text}\n[decision {decision_key}]")

    def poll(self, cursor: int) -> tuple[list[Reply], int]:
        return [], cursor


class TelegramNotifier:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings.from_env()

    def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        url = TELEGRAM_API.format(token=self._settings.telegram_token, method=method)
        for attempt in range(3):
            try:
                response = httpx.post(url, json=payload, timeout=20)
                if response.status_code == 429:
                    time.sleep(2 * (attempt + 1))
                    continue
                data: dict[str, Any] = response.json()
                if not data.get("ok"):
                    print(f"Telegram refused {method}: {data.get('description')}")
                return data
            except (httpx.HTTPError, ValueError):
                time.sleep(2 * (attempt + 1))
        return None

    def send(self, text: str) -> None:
        for chunk in split_message(text):
            self._call(
                "sendMessage",
                {
                    "chat_id": self._settings.telegram_chat_id,
                    "text": chunk,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )

    def ask(self, text: str, decision_key: str) -> None:
        self._call(
            "sendMessage",
            {
                "chat_id": self._settings.telegram_chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            {"text": "Approve", "callback_data": f"{decision_key}:yes"},
                            {"text": "Reject", "callback_data": f"{decision_key}:no"},
                        ],
                        [{"text": "Tell me more", "callback_data": f"{decision_key}:explain"}],
                    ]
                },
            },
        )

    def poll(self, cursor: int) -> tuple[list[Reply], int]:
        """Everything new since `cursor`, plus the cursor to store next time."""
        url = TELEGRAM_API.format(token=self._settings.telegram_token, method="getUpdates")
        try:
            response = httpx.get(
                url, params={"offset": cursor + 1, "timeout": 0, "limit": 50}, timeout=25
            )
            data = response.json()
        except (httpx.HTTPError, ValueError):
            return [], cursor

        if not data.get("ok"):
            return [], cursor

        replies: list[Reply] = []
        latest = cursor
        for update in data.get("result", []):
            latest = max(latest, int(update.get("update_id", 0)))
            callback = update.get("callback_query")
            if callback:
                key, _, answer = str(callback.get("data", "")).partition(":")
                replies.append(Reply(kind="decision", decision=key, answer=answer))
                self._call(
                    "answerCallbackQuery",
                    {"callback_query_id": callback["id"], "text": "Got it"},
                )
                continue
            message = update.get("message") or {}
            text = str(message.get("text") or "").strip()
            if text:
                replies.append(Reply(kind="text", text=text))
        return replies, latest


def split_message(text: str, size: int = MAX_MESSAGE) -> list[str]:
    """Split on line boundaries so a table never breaks mid-row."""
    if len(text) <= size:
        return [text]
    chunks: list[str] = []
    buffer = ""
    for line in text.split("\n"):
        if len(buffer) + len(line) + 1 > size:
            chunks.append(buffer)
            buffer = line
        else:
            buffer = f"{buffer}\n{line}" if buffer else line
    if buffer:
        chunks.append(buffer)
    return chunks


def build_notifier(settings: Settings | None = None) -> Notifier:
    resolved = settings or Settings.from_env()
    return TelegramNotifier(resolved) if resolved.can_notify else ConsoleNotifier()


def millions(amount: float) -> str:
    """Money the way it is read in Spain: 43,15 M."""
    return f"{amount / 1e6:.2f} M".replace(".", ",")


__all__ = [
    "ConsoleNotifier",
    "Notifier",
    "Reply",
    "TelegramNotifier",
    "build_notifier",
    "millions",
    "split_message",
]
