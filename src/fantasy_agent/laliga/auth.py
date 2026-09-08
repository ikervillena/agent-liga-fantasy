"""Authentication against LaLiga's Azure AD B2C tenant.

The password grant is used once to obtain a token pair; from then on the agent
lives off the refresh token, so the password is only needed if LaLiga
invalidates the refresh. The bearer the API wants is the `id_token`, not the
`access_token` — an easy hour to lose if you assume otherwise.

Tokens are held in memory for the lifetime of a run. Each CI run is a fresh
container, so nothing is ever written to disk and there is no token file to
leak.
"""

from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from ..config import (
    AUTH_BASE,
    CLIENT_ID,
    POLICY_PASSWORD_GRANT,
    POLICY_REFRESH,
    REDIRECT_URI,
    USER_AGENT,
    Settings,
)

TOKEN_URL = f"{AUTH_BASE}/token"


class AuthError(RuntimeError):
    """Authentication failed in a way retrying will not fix."""


def _post_token(params: dict[str, str], policy: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.post(
            TOKEN_URL,
            params={"p": policy},
            data=params,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": USER_AGENT,
            },
        )
    try:
        payload: dict[str, Any] = response.json()
    except ValueError as exc:
        raise AuthError(f"B2C returned non-JSON ({response.status_code})") from exc

    if response.status_code >= 400:
        detail = payload.get("error_description") or payload.get("error") or "unknown error"
        raise AuthError(f"B2C {response.status_code}: {detail}")
    return payload


def _normalise(raw: dict[str, Any]) -> dict[str, Any]:
    now = int(time.time())
    expires_in = int(raw.get("id_token_expires_in") or raw.get("expires_in") or 86_400)
    bearer = raw.get("id_token") or raw.get("access_token")
    if not bearer:
        raise AuthError("B2C response carried neither id_token nor access_token")
    return {
        "bearer": bearer,
        "refresh_token": raw.get("refresh_token"),
        "expires_on": int(raw.get("expires_on") or now + expires_in),
    }


class TokenStore:
    """Hands out a valid bearer, refreshing or logging in as needed."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or Settings.from_env()
        self._tokens: dict[str, Any] | None = None

    def _expired(self, tokens: dict[str, Any], margin: int = 300) -> bool:
        return int(tokens.get("expires_on", 0)) - margin <= int(time.time())

    def bearer(self, *, force_refresh: bool = False) -> str:
        tokens = self._tokens
        if tokens and not force_refresh and not self._expired(tokens):
            return str(tokens["bearer"])

        if tokens and tokens.get("refresh_token"):
            try:
                refreshed = _normalise(
                    _post_token(
                        {
                            "grant_type": "refresh_token",
                            "refresh_token": str(tokens["refresh_token"]),
                            "client_id": CLIENT_ID,
                            "scope": "openid offline_access",
                        },
                        POLICY_REFRESH,
                    )
                )
                # B2C does not always rotate the refresh token; keep the old one.
                refreshed.setdefault("refresh_token", tokens["refresh_token"])
                self._tokens = refreshed
                return str(refreshed["bearer"])
            except AuthError:
                pass  # fall through to a full login

        if not self._settings.can_authenticate:
            raise AuthError("No credentials available. Set FANTASY_EMAIL and FANTASY_PASSWORD.")

        self._tokens = _normalise(
            _post_token(
                {
                    "grant_type": "password",
                    "client_id": CLIENT_ID,
                    "scope": f"openid {CLIENT_ID} offline_access",
                    "redirect_uri": REDIRECT_URI,
                    "username": self._settings.email,
                    "password": self._settings.password,
                    "response_type": "id_token",
                },
                POLICY_PASSWORD_GRANT,
            )
        )
        return str(self._tokens["bearer"])

    def claims(self) -> dict[str, Any]:
        """Decode the JWT payload without verifying it — diagnostics only."""
        try:
            part = self.bearer().split(".")[1]
            part += "=" * (-len(part) % 4)
            decoded: dict[str, Any] = json.loads(base64.urlsafe_b64decode(part))
            return decoded
        except (IndexError, ValueError):
            return {}


__all__ = ["AuthError", "TokenStore"]
