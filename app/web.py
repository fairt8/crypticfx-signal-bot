import threading
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path
from . import config as C, db, scanner, telegram, ai, summary, don20
app = FastAPI(title="FVG Signal Bot")
from fastapi.middleware.gzip import GZipMiddleware
app.add_middleware(GZipMiddleware, minimum_size=2000)   # /api/desk is ~200KB of JSON
from .webapp import router as _miniapp
app.include_router(_miniapp)   # Telegram Mini App: /app + owner-only /app/api/*
@app.on_event("startup")
def _start():
    db.init(); don20.init(); telegram.start(); summary.start()
    from . import alerts; alerts.apply_migrations()   # one-time, user-approved alert-mode switch (stored in the DB)
    don20.start(scanner.crypto_universe, lambda: bool(scanner.STATE.get("leader")))
    if C.ENABLE_SCHEDULER: scanner.start()
@app.on_event("shutdown")
def _stop(): db.release_lease()
def desk_page(mode):
    """Shared desk UI (desk.html) for the public dashboard (mode=web) and the Telegram Mini App (mode=app). Static shell, no data."""
    h = (Path(__file__).parent / "desk.html").read_text().replace("__MODE__", mode)
    if mode != "app": h = h.replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>', "")
    return HTMLResponse(h, headers={"Cache-Control": "no-cache"})
@app.get("/", response_class=HTMLResponse)
def home(): return desk_page("web")
@app.get("/api/desk")
def desk_api():
    """Equity (R), per-tier/strategy stats, positions with live price, recent alerts, health. Cached 60s server-side."""
    from . import desk; return desk.get()
def tier_rows(days, tier):
    """Signals of one tier (primary|secondary|profitable), with DON20/DON28 positions included when the tier covers them."""
    from . import alerts, strategies as SG, trades
    rs = [dict(r, strategy_key=SG.eff(r.get("strategy"), r.get("tags"))) for r in db.recent(days)]
    rs = [r for r in rs if SG.active(r["strategy_key"]) and alerts.in_tier(r["strategy_key"], tier)]
    since = trades._since(days)   # DON20 ⭐ / DON28 🔷 positions of this tier
    rs += [dict(r, confidence=None, kind="don20") for r in trades._don_rows() if alerts.in_tier(r["strategy"], tier) and (r["status"] == "open" or trades._in(r["created_at"], since))]
    rs.sort(key=lambda r: str(trades._ts(r.get("created_at")) or ""), reverse=True); return rs
@app.get("/api/signals")
def signals(days: int = 30, tier: str = ""):
    if not tier: return db.recent(days)   # unchanged default
    from . import alerts
    if tier not in alerts.TIERS: return JSONResponse({"error": "tier must be primary|secondary|profitable"}, 400)
    return tier_rows(days, tier)
@app.get("/api/alerts")
def alerts_state():   # read-only (mode can only be changed from Telegram: /alerts or the mini app)
    from . import alerts; return alerts.state()
def strategies_enabled():
    """Live on/off per strategy (env flags), for diagnostics."""
    pat = lambda k: C.ENABLE_PAT and k in C.PAT_ENABLED
    return {"DON20": True, "DON28": C.ENABLE_DON28, "MF-REJ": C.ENABLE_MF, "PAT-TRIPLE": pat("PAT-TRIPLE"), "PAT-WEDGE": pat("PAT-WEDGE"),
            "BRK": C.ENABLE_BRK, "CHK": C.ENABLE_CHK, "FVG-D1": C.ENABLE_D1, "FVG-PLAN": C.ENABLE_FVG_PLAN, "PAT-TRIPLE-C": pat("PAT-TRIPLE-C"),
            "FVG+TREND": C.ENABLE_FVG_TREND, "FVG": C.ENABLE_FVG_LIVE, "PAT-CUP": pat("PAT-CUP")}
def tier_map():
    from . import strategies as SG, variants as V
    return {k: dict(tier=SG.status(k), label=SG.label(k), short=SG.short(k), stop=V.DESC.get(V.MODE.get(k), "strategy rules")) for k in SG.STATUS}
@app.get("/api/stats")
def stats(): return dict(db.stats(), by_strategy=db.by_strategy(), telegram_mode=telegram.MODE["state"], telegram_menu_button=telegram.MENU["state"], telegram_webhook=telegram.webhook_info(), leader=scanner.STATE.get("leader"), db="postgres" if db.PG else "sqlite", last_summary=scanner.STATE.get("last_summary"), last_scan=scanner.STATE.get("last_scan"), counts=scanner.STATE.get("last_counts"),
    sessions=scanner.STATE.get("sessions"), active_ccy=scanner.STATE.get("active_ccy"),
    forex_priority=[r for r in scanner.STATE.get("forex_rank", []) if r.get("priority")],
    strength={k: round(v,3) for k,v in scanner.STATE.get("strength", {}).items()},
    universe_size=len(scanner.STATE.get("universe", [])), ai=ai.enabled(), telegram=telegram.enabled(), telegram_token_shape=telegram.token_shape(), min_post_score=C.MIN_POST_SCORE, strategies_enabled=strategies_enabled(), tiers=tier_map(), tier_stats={t: db.stats(tier=t) for t in ("primary", "secondary")}, strategies_flags={"BRK": C.ENABLE_BRK, "BRK_MARKETS": sorted(C.BRK_MARKETS), "BRK_LEVELS": C.BRK_LEVELS}, mf_strong_pair=scanner.STATE.get("mf_strong_pair"),
    instance=db.INSTANCE, scheduler_lease=db.kv_get("lease:scheduler"), scan_started=scanner.STATE.get("scan_started"), scan_errors=scanner.STATE.get("errors", [])[-5:], don20=dict(last_run=don20.STATE["last_run"], last_result=don20.STATE["last_result"], errors=don20.STATE["errors"][-5:]))
@app.get("/api/trades")
def trades_by_state(state: str = "open", period: str = "all"):
    from . import trades
    if state not in ("open", "closed", "pending", "new", "retired"): return JSONResponse({"error": "state must be open|closed|pending|new|retired"}, 400)
    if period not in trades.PERIODS: return JSONResponse({"error": "period must be day|week|month|all"}, 400)
    rows = trades.by_state(state, period); cl = [r for r in rows if r.get("net_r") is not None]
    return dict(state=state, period=period, count=len(rows), closed_net_r=round(sum(r["net_r"] for r in cl), 2),
                open_live_net_r=round(sum(r.get("live_net_r") or 0 for r in rows if r["status"] == "open"), 2), rows=rows)
@app.get("/api/equity")
def equity(days: int = 30):
    from .webapp import equity as eq; return eq(max(7, min(days, 90)))
@app.get("/api/don20/pnl")
def don20_pnl():
    from . import trades; return trades.don20_pnl()
@app.get("/api/strategies")
def strategies_list():
    from . import strategies; return strategies.listing()
@app.get("/api/trades/{symbol}")
def trades_symbol(symbol: str):
    from . import trades; return trades.history(symbol)
@app.get("/api/don20")
def don20_positions(): return don20.all_positions()
@app.post("/api/scan")
def scan_now(): return [s["id"] for s in scanner.scan()]
@app.get("/api/explain/{i}")
def explain(i: int):
    s = db.get(i); return {"text": ai.explain(s) if s else "not found"}
class Q(BaseModel): q: str
@app.post("/api/chat")
def chat(q: Q): return {"text": ai.chat(q.q, "\n".join(str(r) for r in db.recent(2)[:20]))}
@app.api_route("/health", methods=["GET", "HEAD"])
def health(): return {"ok": True}   # no DB / network work: safe for a 10-minute pinger
@app.post("/telegram/webhook")
async def tg_webhook(request: Request):
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != telegram.webhook_secret(): return {"ok": False}
    u = await request.json(); threading.Thread(target=telegram.process_update, args=(u,), daemon=True).start()
    return {"ok": True}
