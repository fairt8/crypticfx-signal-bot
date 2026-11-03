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
    from .web import desk_page; return desk_page("app")

@router.get("/app/api/desk")
def app_desk(request: Request):
    auth(request)
    from . import desk; return desk.get()

@router.get("/app/api/me")
def me(request: Request):
    u = auth(request); return dict(ok=True, first_name=u.get("first_name"))

def equity(days=30):
    """Daily closed net R (signals + DON20) for the last `days` days, per tier, for the PnL chart."""
    from . import trades, strategies as SG
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc); start = (now - timedelta(days=days-1)).date()
    D = {(start + timedelta(days=i)).isoformat(): {"primary": 0.0, "secondary": 0.0} for i in range(days)}
    for r in trades._sig_rows("WHERE 1=1") + trades._don_rows():
        if r.get("net_r") is None: continue
        t = trades._ts(r.get("closed_at")); tier = SG.status(r.get("strategy"))
        if not t or tier not in SG.TIERS: continue
        k = (t + timedelta(hours=1)).date().isoformat()   # WAT day
        if k in D: D[k][tier] += r["net_r"]
    return [dict(d=k, primary=round(v["primary"], 3), secondary=round(v["secondary"], 3)) for k, v in sorted(D.items())]

@router.get("/app/api/overview")
def overview(request: Request):
    auth(request)
    from . import trades, scanner, alerts
    op = trades.by_state("open", "all")
    try: eq = equity(30)
    except Exception: eq = []
    return dict(stats=db.stats(), tier_stats={t: db.stats(tier=t) for t in ("primary", "secondary")}, don20=trades.don20_pnl(), open_count=len(op),
                open_live_net_r=round(sum(r.get("live_net_r") or 0 for r in op), 2),
                open_in_profit=sum((r.get("live_net_r") or 0) > 0 for r in op), equity=eq, alert_mode=alerts.get_mode(), alert_label=alerts.MODE_LABEL[alerts.get_mode()],
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
    from . import alerts
    return dict(listing=strategies.listing(), by_strategy=db.by_strategy(), alerts=alerts.state())

@router.get("/app/api/alerts")
def app_alerts(request: Request):
    auth(request)
    from . import alerts; return alerts.state()

from pydantic import BaseModel
class ModeIn(BaseModel): mode: str
@router.post("/app/api/alerts")
def app_alerts_set(request: Request, body: ModeIn):
    auth(request)
    from . import alerts
    try: alerts.set_mode(body.mode)
    except ValueError as e: raise HTTPException(400, str(e))
    return alerts.state()

@router.get("/app/api/signals")
def app_signals(request: Request, days: int = 3, tier: str = ""):
    """Live-tier signals (⭐ PRIMARY + 🔷 SECONDARY by default, or one tier) with the fields the signal cards need."""
    auth(request)
    from . import strategies as SG, alerts
    if tier and tier not in alerts.TIERS: raise HTTPException(400, "bad tier")
    from .web import tier_rows
    keep = ("id", "symbol", "market", "direction", "status", "entry", "sl", "tp", "rr", "confidence", "setup_score", "created_at", "confirm_time",
            "filled_at", "closed_at", "result_r", "net_r", "kind", "price_now", "live_r", "live_net_r")
    days = max(1, min(days, 30)); rows = tier_rows(days, tier) if tier else tier_rows(days, "primary") + tier_rows(days, "secondary")
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True); out = []
    for r in rows[:100]:
        k = r.get("strategy_key") or r.get("strategy") or "DON20"
        out.append(dict({x: r.get(x) for x in keep}, strategy_key=k, short=SG.short(k), tier=SG.status(k), label=SG.label(k), active=True))
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
