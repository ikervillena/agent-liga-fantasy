"""Read-only raw snapshot of the league for offline analysis. Never writes to the API."""
from __future__ import annotations
import json, sys, time, traceback
from pathlib import Path
from fantasy.sources.laliga import auth as _auth
from fantasy.sources.laliga import client as _client
from fantasy.sources.laliga.client import FantasyClient

AUTH_NOTE = []
_orig_post = _auth._post_token
def _post_token(params, policy):
    try:
        return _orig_post(params, policy)
    except _auth.AuthError as e:
        AUTH_NOTE.append(f"{policy}: {e}")
        if params.get("grant_type") == "password" and policy != "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN":
            return _orig_post(params, "B2C_1A_5ULAIP_PARAMETRIZED_SIGNIN")
        raise
_auth._post_token = _post_token

class TolerantClient(FantasyClient):
    """Falls back to anonymous requests (public endpoints) if login is impossible."""
    anon = False
    def _headers(self, *, force_refresh=False):
        if not self.anon:
            try:
                return super()._headers(force_refresh=force_refresh)
            except _auth.AuthError as e:
                AUTH_NOTE.append(f"login failed -> anonymous: {e}")
                self.anon = True
        return {"x-lang": "es", "User-Agent": _client.USER_AGENT, "Origin": "https://fantasy.laliga.com",
                "Referer": "https://fantasy.laliga.com/", "Accept": "application/json"}

LEAGUE, TEAM = "018110971", "38611081"
OUT = Path("state/snapshot"); OUT.mkdir(parents=True, exist_ok=True)
log = []
def save(name, data):
    (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1))
def safe(name, fn, *a):
    try:
        d = fn(*a); save(name, d); log.append(f"OK {name}"); return d
    except Exception as e:
        log.append(f"ERR {name}: {type(e).__name__}: {str(e)[:400]}"); return None

c = TolerantClient()
try:
    week = safe("week", c.current_matchday)
    players = safe("players", c.players)
    safe("leagues", c.leagues)
    st = safe("standing", c.standings, LEAGUE)
    safe("market", c.market, LEAGUE)
    safe("cash", c.cash, TEAM)
    safe("lineup", c.lineup, TEAM)
    for p in range(4): safe(f"activity_{p}", c.activity, LEAGUE, p)
    wk = None
    try: wk = int((week or {}).get("weekNumber") or 0)
    except Exception: pass
    for w in range(1, (wk or 10) + 4):
        safe(f"calendar_{w}", c.calendar, w)
    team_ids = []
    for row in (st or []):
        t = row.get("team") or {}
        tid = t.get("id") or row.get("teamId")
        if tid: team_ids.append(str(tid))
    owned = set()
    teams = {}
    for tid in team_ids:
        t = safe(f"team_{tid}", c.team, LEAGUE, tid)
        teams[tid] = t
        for pt in (t or {}).get("players", []) or []:
            pm = pt.get("playerMaster") or {}
            if pm.get("id"): owned.add(str(pm["id"]))
            if tid == TEAM and pt.get("id"):
                safe(f"offers_{pt['id']}", c.offers_for, LEAGUE, str(pt["id"]))
    mk = json.loads((OUT/"market.json").read_text()) if (OUT/"market.json").exists() else []
    mkt_ids = set()
    for m in mk or []:
        pm = (m.get("playerMaster") or {})
        if pm.get("id"): mkt_ids.add(str(pm["id"]))
    # top free agents by points too
    if not owned:
        # no private data: take every player with points so the analysis can still run offline
        top = sorted((players or []), key=lambda p: -(p.get("points") or 0))[:450]
    else:
        top = sorted((players or []), key=lambda p: -(p.get("points") or 0))[:120]
    ids = owned | mkt_ids | {str(p["id"]) for p in top}
    details, values = {}, {}
    for pid in sorted(ids):
        try: details[pid] = c.player(pid)
        except Exception as e: log.append(f"ERR player {pid}: {e}")
        if pid in owned or pid in mkt_ids or not owned:
            try: values[pid] = c.market_value(pid)
            except Exception as e: log.append(f"ERR mv {pid}: {e}")
    save("player_details", details); save("market_values", values)
    log.append(f"owned={len(owned)} market={len(mkt_ids)} details={len(details)}")
except Exception:
    log.append(traceback.format_exc())
finally:
    (OUT / "log.txt").write_text(time.strftime("%Y-%m-%d %H:%M:%S UTC\n", time.gmtime()) + "\n".join(AUTH_NOTE + log))
