"""Telegram Mini App (Web App) backend: initData verification + owner-only JSON endpoints under /app/api/*.
Security: every /app/api call needs the X-Telegram-Init-Data header. It is checked with Telegram's HMAC scheme
(secret = HMAC_SHA256(key="WebAppData", msg=bot_token); hash = HMAC_SHA256(secret, data_check_string)), must be
fresh (auth_date <= MINIAPP_MAX_AGE_S, default 24h) and the Telegram user id must equal TELEGRAM_CHAT_ID (owner).
The /app HTML page itself is static and contains no data. The older public /api/* endpoints are unchanged."""
import hmac, hashlib, json, time, glob, os
from urllib.parse import parse_qsl
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import HTMLResponse
from pathlib import Path
from . import config as C, db

router = APIRouter()
MAX_AGE = int(os.getenv("MINIAPP_MAX_AGE_S", "86400"))

def verify(init_data, token=None, owner=None, max_age=None, now=None):
    """Return the Telegram user dict if initData is authentic, fresh and from the owner; else raise ValueError(reason)."""
    token = C.TELEGRAM_BOT_TOKEN if token is None else token
    owner = str(C.TELEGRAM_CHAT_ID or "").strip() if owner is None else str(owner)
    max_age = MAX_AGE if max_age is None else max_age
    if not token or not owner: raise ValueError("mini app not configured")
    if not init_data or len(init_data) > 4096: raise ValueError("missing initData")
    try: pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=True))
    except ValueError: raise ValueError("malformed initData")
    got = pairs.pop("hash", "")
    if not got: raise ValueError("no hash")
    dcs = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    want = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, got): raise ValueError("bad signature")
    try: age = (now or time.time()) - int(pairs.get("auth_date", "0"))
    except ValueError: raise ValueError("bad auth_date")
    if age > max_age or age < -300: raise ValueError("initData expired")
    try: user = json.loads(pairs.get("user") or "{}")
    except ValueError: raise ValueError("bad user")
    if str(user.get("id")) != owner: raise ValueError("not the owner")
    return user

def auth(request: Request):
    try: return verify(request.headers.get("X-Telegram-Init-Data", ""))
    except ValueError as e: raise HTTPException(status_code=401 if str(e) != "not the owner" else 403, detail=str(e))

def app_url(): return (C.PUBLIC_URL.rstrip("/") + "/app") if C.PUBLIC_URL else None

@router.get("/app", response_class=HTMLResponse)
def page():   # static shell only; all data comes from /app/api/* with initData
    return HTMLResponse((Path(__file__).parent / "miniapp.html").read_text(), headers={"Cache-Control": "no-cache"})

@router.get("/app/api/me")
def me(request: Request):
    u = auth(request); return dict(ok=True, first_name=u.get("first_name"))

@router.get("/app/api/overview")
def overview(request: Request):
    auth(request)
    from . import trades, scanner
    op = trades.by_state("open", "all")
    return dict(stats=db.stats(), don20=trades.don20_pnl(), open_count=len(op),
                open_live_net_r=round(sum(r.get("live_net_r") or 0 for r in op), 2),
                open_in_profit=sum((r.get("live_net_r") or 0) > 0 for r in op),
                last_scan=scanner.STATE.get("last_scan"), counts=scanner.STATE.get("last_counts"), sessions=scanner.STATE.get("sessions"))

@router.get("/app/api/trades")
def app_trades(request: Request, state: str = "open", period: str = "all"):
    auth(request)
    from . import trades
    if state not in ("open", "closed", "pending", "new", "retired") or period not in trades.PERIODS: raise HTTPException(400, "bad state/period")
    rows = trades.by_state(state, period); cl = [r for r in rows if r.get("net_r") is not None]
    return dict(state=state, period=period, count=len(rows), closed_net_r=round(sum(r["net_r"] for r in cl), 2),
                closed_win=round(100*sum(r["net_r"] > 0 for r in cl)/len(cl), 1) if cl else None,
                open_live_net_r=round(sum(r.get("live_net_r") or 0 for r in rows if r["status"] == "open"), 2), rows=rows[:300])

@router.get("/app/api/token/{symbol}")
def app_token(request: Request, symbol: str):
    auth(request)
    from . import trades; return trades.history(symbol[:20])

@router.get("/app/api/strategies")
def app_strategies(request: Request):
    auth(request)
    from . import strategies
    return dict(listing=strategies.listing(), by_strategy=db.by_strategy())

@router.get("/app/api/signals")
def app_signals(request: Request, days: int = 3):
    auth(request)
    from . import strategies as SG
    keep = ("id", "symbol", "market", "strategy", "direction", "status", "entry", "sl", "tp", "confidence", "setup_score", "created_at", "result_r")
    out = []
    for r in db.recent(max(1, min(days, 30)))[:60]:
        k = SG.eff(r.get("strategy"), r.get("tags")); d = {x: r.get(x) for x in keep}
        d.update(strategy_key=k, label=SG.label(k), active=SG.active(k)); out.append(d)
    return out

def latest_backtest():
    """Newest all-strategy backtest: DB copy (saved by app.backtest_all) or a bt_all/ / reports/ JSON on disk. None if absent."""
    try:
        v = db.kv_get("backtest_all:last")
        if v: return json.loads(v) if isinstance(v, str) else v
    except Exception: pass
    fs = sorted(glob.glob("bt_all/backtest-all-*.json") + glob.glob("reports/backtest-all-*.json"))
    if not fs: return None
    d = json.load(open(fs[-1])); return compact_backtest(d)

def compact_backtest(d):
    return dict(generated=d.get("generated"), window_days=d.get("window_days"), btc_season_now=d.get("btc_season_now"),
                strategies={k: dict(label=v.get("label"), status=v.get("status"), total=v.get("total"), by_season=v.get("by_season")) for k, v in (d.get("strategies") or {}).items()})

@router.get("/app/api/backtest")
def app_backtest(request: Request):
    auth(request); b = latest_backtest()
    return dict(available=bool(b), report=b)
