"""Telegram via raw Bot API (no extra deps). Posts signals to TELEGRAM_CHAT_ID; long-polls commands."""
import requests, threading, time
from . import config as C, db, ai
API = lambda m: f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/{m}"
def enabled(): return bool(C.TELEGRAM_BOT_TOKEN)
def fmt_price(x): return f"{x:.6g}" if x < 1 else (f"{x:.5f}" if x < 50 else f"{x:.2f}")
def fmt(s):
    e = "🟢 LONG" if s["direction"]=="long" else "🔴 SHORT"
    tags = s.get("tags") or ["FVG"]; exp = s.get("experimental") or "FVG+TREND" in tags or "FVG-D1" in tags
    names = {"FVG":"FVG (live)","FVG+TREND":"FVG + 4H trend filter","CHK":"Varsity checklist","FVG-PLAN":"FVG creator plan (swing stop)","FVG-D1":"FVG-D1 [EXPERIMENTAL] daily bias","MF-REJ":"MF-REJ (Market Fluidity zone rejection, 1H)"}
    head = ("[EXPERIMENTAL – paper test] " if exp else "") + "Strategy: " + " + ".join(names.get(t,t) for t in tags)
    if s.get("strategy") in ("CHK", "MF-REJ"): entry_lbl = "Entry (market, 1H close)"
    else: entry_lbl = "Entry (limit)"
    if s.get("strategy") == "MF-REJ": head = "MF-REJ [EXPERIMENTAL – paper test] Strategy: Market Fluidity zone rejection (1H)"
    flag = "" if s["in_session"] else "\n⚠️ Outside London/NY session"
    return (f"{head}\n#{s['id']} {e} {s['symbol']} ({s['market']})\nEst. win probability: {s['confidence']}% (needs >25% to break even at 1:3)\n"
            f"{entry_lbl}: {fmt_price(s['entry'])}\nStop: {fmt_price(s['sl'])}"
            + (f"\nTP1 (1:1.5): {fmt_price(s['tp1'])}" if s.get('tp1') else "") + f"\nTP2 (1:{s['rr']:g}): {fmt_price(s['tp'])}"
            f"\nStatus: {s['status']}{flag}\n" + "\n".join("• "+r for r in s["reasons"][1:]) + "\n\nNot financial advice.")
def send(text, chat_id=None):
    if not enabled() or not (chat_id or C.TELEGRAM_CHAT_ID): return False
    r = requests.post(API("sendMessage"), json=dict(chat_id=chat_id or C.TELEGRAM_CHAT_ID, text=text[:4000]), timeout=20)
    return r.ok
def post_group(rows):
    rows = [r for r in rows if r["confidence"] >= C.MIN_CONFIDENCE_TO_POST]
    if not rows: return
    rows.sort(key=lambda r: r["strategy"] != "FVG")   # live FVG first
    text = fmt(rows[0])
    for r in rows[1:]:
        text += (f"\n\n[EXPERIMENTAL – paper test] Same setup, {r['strategy']} levels (#{r['id']}): entry {fmt_price(r['entry'])}, "
                 f"stop {fmt_price(r['sl'])}, target {fmt_price(r['tp'])}")
    if send(text):
        for r in rows: db.update(r["id"], posted=1)
def post_signal(s):
    if s["confidence"] >= C.MIN_CONFIDENCE_TO_POST and send(fmt(s)): db.update(s["id"], posted=1)
HELP = "/signals – open/pending signals\n/history [days] – last results (default 7)\n/stats – 30-day stats\n/explain <id> – AI explanation\n/ask <question> – ask AI about recent signals"
def handle(text, chat):
    parts = text.split(maxsplit=1); cmd = parts[0].split("@")[0].lower(); arg = parts[1] if len(parts) > 1 else ""
    if cmd in ("/start","/help"): return f"Signal bot ready. Your chat id: {chat}\n"+HELP
    if cmd == "/signals":
        rs = [r for r in db.recent(3) if r["status"] in ("pending","open")][:10]
        return "\n\n".join(fmt(r) for r in rs) or "No open signals."
    if cmd == "/history":
        d = int(arg) if arg.isdigit() else 7
        rs = db.recent(d)[:30]
        return "\n".join(f"#{r['id']} {r['symbol']} {r['direction']} {r['confidence']}% → {r['status']}" for r in rs) or "No history."
    if cmd == "/stats":
        bs = db.by_strategy(); d = bs.get("DON20", {})
        return "\n".join(f"{v['label']}: {v['closed']} closed, win {v['win_rate']}%, net {v['net_r']}R ({v['open']} open)" for k, v in bs.items() if k != "DON20") + \
            f"\nDON20 [EXPERIMENTAL – paper test]: {d.get('open',0)} open, {d.get('closed',0)} closed, win {d.get('win_rate')}%, net {d.get('net_r',0)}R" 
    if cmd == "/explain":
        s = db.get(int(arg)) if arg.isdigit() else None
        return ai.explain(s) if s else "Usage: /explain <id>"
    if cmd == "/ask": return ai.chat(arg or "Summarise", "\n".join(str(r) for r in db.recent(2)[:20]))
    return HELP
def process_update(u):
    m = u.get("message") or {}
    if m.get("text","").startswith("/"):
        try: send(handle(m["text"], m["chat"]["id"]), m["chat"]["id"])
        except Exception as e: send(f"Error: {e}", m["chat"]["id"])
def poll_forever():
    off = 0
    while True:
        try:
            if not db.lease("telegram-poll", ttl_s=180): time.sleep(60); continue   # one poller at a time
            r = requests.get(API("getUpdates"), params=dict(timeout=50, offset=off), timeout=60).json()
            if r.get("error_code") == 409: MODE["state"] = "conflict: webhook set or other poller"; time.sleep(60); continue
            for u in r.get("result", []):
                off = u["update_id"]+1; process_update(u)
        except Exception: time.sleep(5)
import hashlib
MODE = {"state": "off"}
def webhook_secret():
    return C.TELEGRAM_WEBHOOK_SECRET or hashlib.sha256(("wh:" + C.TELEGRAM_BOT_TOKEN).encode()).hexdigest()[:32]
def start():
    """Webhook when a public URL is known (Render sets RENDER_EXTERNAL_URL) -> no polling conflicts between instances.
    Otherwise long-polling, but never delete a webhook someone else set unless TELEGRAM_MODE=polling."""
    if not enabled(): return
    if C.PUBLIC_URL and C.TELEGRAM_MODE != "polling":
        r = requests.post(API("setWebhook"), json=dict(url=C.PUBLIC_URL.rstrip("/") + "/telegram/webhook", secret_token=webhook_secret(),
            allowed_updates=["message"], drop_pending_updates=False), timeout=20).json()
        MODE["state"] = "webhook " + ("ok" if r.get("ok") else f"failed: {r.get('description')}")
        return
    info = requests.get(API("getWebhookInfo"), timeout=20).json().get("result", {})
    if info.get("url") and C.TELEGRAM_MODE != "polling":
        MODE["state"] = f"webhook active elsewhere ({info['url'].split('/')[2]}); not polling here"; return
    if info.get("url"): requests.post(API("deleteWebhook"), timeout=20)
    MODE["state"] = "polling"; threading.Thread(target=poll_forever, daemon=True).start()

_SHAPE = {}
def token_shape():
    """Safe diagnostic: never returns the token or any part of it."""
    import re
    t = C.TELEGRAM_BOT_TOKEN
    if "res" not in _SHAPE or time.time() - _SHAPE.get("t", 0) > 300:
        try: r = requests.get(API("getMe"), timeout=10).json(); res = dict(ok=r.get("ok"), description=r.get("description"))
        except Exception as e: res = dict(ok=False, description=type(e).__name__)
        _SHAPE.update(res=res, t=time.time())
    return dict(length=len(t), bot_id_digits=len(t.split(":")[0]) if ":" in t else 0,
                matches_regex=bool(re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", t)),
                getMe_ok=_SHAPE["res"]["ok"], getMe_description=_SHAPE["res"]["description"])
