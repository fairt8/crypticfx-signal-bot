import threading
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pathlib import Path
from . import config as C, db, scanner, telegram, ai, summary
app = FastAPI(title="FVG Signal Bot")
@app.on_event("startup")
def _start():
    db.init(); telegram.start(); summary.start()
    if C.ENABLE_SCHEDULER: scanner.start()
@app.on_event("shutdown")
def _stop(): db.release_lease()
@app.get("/", response_class=HTMLResponse)
def home(): return (Path(__file__).parent / "dashboard.html").read_text()
@app.get("/api/signals")
def signals(days: int = 30): return db.recent(days)
@app.get("/api/stats")
def stats(): return dict(db.stats(), by_strategy=db.by_strategy(), telegram_mode=telegram.MODE["state"], leader=scanner.STATE.get("leader"), db="postgres" if db.PG else "sqlite", last_summary=scanner.STATE.get("last_summary"), last_scan=scanner.STATE.get("last_scan"), counts=scanner.STATE.get("last_counts"),
    sessions=scanner.STATE.get("sessions"), active_ccy=scanner.STATE.get("active_ccy"),
    forex_priority=[r for r in scanner.STATE.get("forex_rank", []) if r.get("priority")],
    strength={k: round(v,3) for k,v in scanner.STATE.get("strength", {}).items()},
    universe_size=len(scanner.STATE.get("universe", [])), ai=ai.enabled(), telegram=telegram.enabled(), telegram_token_shape=telegram.token_shape(), min_post_score=C.MIN_POST_SCORE)
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
