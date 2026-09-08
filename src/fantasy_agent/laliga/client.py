"""HTTP transport for the LaLiga Fantasy API.

Reads and writes are separated on purpose. `FantasyClient` only ever GETs;
every mutating call lives on `WriteClient`, which cannot be constructed without
passing `confirm=True`. Wiring a write by accident should take effort.

Two hard-won details are encoded here rather than in comments elsewhere: a POST
with no body must not advertise `Content-Type: application/json` or the API
answers 400, and the whole surface moved host and path prefix between the
25/26 and 26/27 seasons, so paths are built from one place.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import httpx

from ..config import API_BASE, MIN_REQUEST_INTERVAL, USER_AGENT
from .auth import TokenStore


class ApiError(RuntimeError):
    def __init__(self, status: int, url: str, body: str) -> None:
        super().__init__(f"HTTP {status} on {url}: {body[:300]}")
        self.status = status
        self.url = url
        self.body = body


class _Pacer:
    """One request every `interval` seconds. Human pace, no bursts."""

    def __init__(self, interval: float) -> None:
        self._interval = interval
        self._last = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last = time.monotonic()


class FantasyClient:
    """Read-only access to the competition and to one private league."""

    def __init__(
        self,
        tokens: TokenStore | None = None,
        competition_id: str = "1",
        client: httpx.Client | None = None,
    ) -> None:
        self.tokens = tokens or TokenStore()
        self.competition_id = competition_id
        self._pacer = _Pacer(MIN_REQUEST_INTERVAL)
        self._http = client or httpx.Client(timeout=30, follow_redirects=True)

    @property
    def base(self) -> str:
        return f"/v1/competition/{self.competition_id}"

    def _headers(self, *, force_refresh: bool = False) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.tokens.bearer(force_refresh=force_refresh)}",
            "x-lang": "es",
            "User-Agent": USER_AGENT,
            "Origin": "https://fantasy.laliga.com",
            "Referer": "https://fantasy.laliga.com/",
            "Accept": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        *,
        body: Any | None = None,
        params: dict[str, Any] | None = None,
        attempts: int = 3,
    ) -> Any:
        url = path if path.startswith("http") else f"{API_BASE}{path}"
        query = dict(params or {})
        query.setdefault("x-lang", "es")
        last: Exception | None = None

        for attempt in range(attempts):
            self._pacer.wait()
            stale_token = isinstance(last, ApiError) and last.status == 401
            headers = self._headers(force_refresh=stale_token)
            if body is not None:
                headers["Content-Type"] = "application/json"

            try:
                response = self._http.request(
                    method.upper(),
                    url,
                    headers=headers,
                    params=query,
                    content=json.dumps(body) if body is not None else None,
                )
            except httpx.HTTPError as exc:
                last = exc
                time.sleep(2**attempt)
                continue

            if response.status_code == 401 and attempt < attempts - 1:
                last = ApiError(401, url, response.text)
                continue
            if response.status_code == 429:
                last = ApiError(429, url, response.text)
                time.sleep(min(60, 5 * (attempt + 1)))
                continue
            if response.status_code >= 400:
                raise ApiError(response.status_code, url, response.text)

            if not response.content:
                return None
            try:
                return response.json()
            except ValueError:
                return response.text

        raise last or RuntimeError(f"gave up on {path}")

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    # -- competition ---------------------------------------------------------
    def current_matchday(self) -> Any:
        return self.get(f"{self.base}/week/current")

    def players(self) -> Any:
        """Every player in the competition. Public: no bearer required."""
        return self.get(f"{self.base}/players")

    def player(self, player_id: str) -> Any:
        return self.get(f"{self.base}/player/{player_id}")

    def calendar(self, matchday: int) -> Any:
        return self.get(f"{self.base}/calendar", params={"weekNumber": matchday})

    # -- league --------------------------------------------------------------
    def standings(self, league_id: str) -> Any:
        return self.get(f"{self.base}/leagues/{league_id}/standing")

    def team(self, league_id: str, team_id: str) -> Any:
        return self.get(f"{self.base}/leagues/{league_id}/teams/{team_id}")

    def activity(self, league_id: str, page: int = 0) -> Any:
        return self.get(f"{self.base}/leagues/{league_id}/activity/{page}")

    def market(self, league_id: str) -> Any:
        return self.get(f"{self.base}/league/{league_id}/market")

    def offers_for(self, league_id: str, player_team_id: str) -> Any:
        return self.get(f"{self.base}/league/{league_id}/playerTeam/{player_team_id}/offer")

    def cash(self, team_id: str) -> Any:
        return self.get(f"{self.base}/teams/{team_id}/money")

    def lineup(self, team_id: str) -> Any:
        return self.get(f"{self.base}/teams/{team_id}/lineup")

    def close(self) -> None:
        self._http.close()


class WriteClient:
    """Every operation that changes the world.

    Deliberately a separate class with a mandatory `confirm` flag: the executor
    is the only caller, and constructing one anywhere else reads as a mistake.
    """

    def __init__(self, client: FantasyClient, *, confirm: bool = False) -> None:
        if not confirm:
            raise ValueError("WriteClient must be constructed with confirm=True")
        self._c = client

    @property
    def _base(self) -> str:
        return self._c.base

    def pay_clause(self, league_id: str, player_id: str, amount: int) -> Any:
        return self._c.request(
            "POST",
            f"{self._base}/league/{league_id}/buyout/{player_id}/pay",
            body={"buyoutClauseToPay": int(amount)},
        )

    def raise_clause(
        self, league_id: str, player_id: str, increase: int, factor: float = 2.0
    ) -> Any:
        return self._c.request(
            "PUT",
            f"{self._base}/league/{league_id}/buyout/player",
            body={"playerId": player_id, "factor": factor, "valueToIncrease": int(increase)},
        )

    def bid(self, league_id: str, market_id: str, amount: int) -> Any:
        return self._c.request(
            "POST",
            f"{self._base}/league/{league_id}/market/{market_id}/bid",
            body={"money": int(amount)},
        )

    def cancel_bid(self, league_id: str, market_id: str, bid_id: str) -> Any:
        return self._c.request(
            "DELETE",
            f"{self._base}/league/{league_id}/market/{market_id}/bid/{bid_id}/cancel",
        )

    def sell(self, league_id: str, player_id: str, price: int) -> Any:
        return self._c.request(
            "POST",
            f"{self._base}/league/{league_id}/market/sell",
            body={"playerId": player_id, "salePrice": int(price)},
        )

    def accept_offer(self, league_id: str, market_id: str, offer_id: str, amount: int) -> Any:
        return self._c.request(
            "POST",
            f"{self._base}/league/{league_id}/market/{market_id}/offer/{offer_id}/accept",
            body={"offerMoney": int(amount)},
        )

    def reject_offer(self, league_id: str, market_id: str, offer_id: str) -> Any:
        return self._c.request(
            "POST",
            f"{self._base}/league/{league_id}/market/{market_id}/offer/{offer_id}/reject",
        )

    def set_lineup(self, team_id: str, lineup: Any) -> Any:
        return self._c.request("PUT", f"{self._base}/teams/{team_id}/lineup", body=lineup)


__all__ = ["ApiError", "FantasyClient", "WriteClient"]
