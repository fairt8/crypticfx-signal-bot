"""Telegram via raw Bot API (no extra deps). Posts signals to TELEGRAM_CHAT_ID; long-polls commands."""
import requests, threading, time
from . import config as C, db, ai
API = lambda m: f"https://api.telegram.org/bot{C.TELEGRAM_BOT_TOKEN}/{m}"
def enabled(): return bool(C.TELEGRAM_BOT_TOKEN)
def fmt_price(x): return f"{x:.6g}" if x < 1 else (f"{x:.5f}" if x < 50 else f"{x:.2f}")
import html as _h
from datetime import datetime as _dt, timezone as _tz, timedelta as _td
def esc(x): return _h.escape(str(x), quote=False)
def code(x): return f"<code>{esc(fmt_price(x))}</code>"
def bar(p, n=10):
    k = max(0, min(n, round((p or 0) / 100 * n))); return "▰" * k + "▱" * (n - k)
def wat(ts=None):
    try: d = _dt.fromisoformat(str(ts).replace("Z", "+00:00")) if ts else _dt.now(_tz.utc)
    except Exception: d = _dt.now(_tz.utc)
    if d.tzinfo is None: d = d.replace(tzinfo=_tz.utc)
    return d.astimezone(_tz(_td(hours=1))).strftime("%d %b %H:%M") + " WAT"
NAMES = {"FVG":"FVG (live)","FVG+TREND":"FVG + 4H trend filter","CHK":"Varsity checklist","FVG-PLAN":"FVG creator plan (swing stop)","FVG-D1":"FVG-D1 daily bias","MF-REJ":"MF-REJ · Market Fluidity zone rejection (1H)",
         "PAT-WEDGE":"PAT-WEDGE · 4H wedge breakout retest","PAT-TRIPLE":"PAT-TRIPLE · 4H triple top/bottom retest (FX)","PAT-CUP":"PAT-CUP · 4H cup &amp; handle retest","BRK":"BRK · 4H pattern neckline/trendline breakout"}
PATS = ("PAT-WEDGE", "PAT-TRIPLE", "PAT-CUP", "BRK")
def fmt(s):
    e = "🟢 <b>LONG</b>" if s["direction"] == "long" else "🔴 <b>SHORT</b>"
    tags = s.get("tags") or ["FVG"]; mf = s.get("strategy") == "MF-REJ"
    if s.get("strategy") in PATS: return fmt_pat(s)
    exp = mf or s.get("experimental") or "FVG+TREND" in tags or "FVG-D1" in tags
    strat = NAMES["MF-REJ"] if mf else " + ".join(NAMES.get(t, t) for t in tags)
    entry_lbl = "Entry (market, 1H close)" if s.get("strategy") in ("CHK", "MF-REJ") else "Entry (limit)"
    L = []
    if s.get("strategy") == "CHK": L.append("⭐ <b>PRIMARY</b>")
    elif mf: L.append("🧪 <b>experimental – collecting live results</b>")
    elif exp: L.append("🧪 <b>EXPERIMENTAL – paper test</b>")
    L += [f"🏷 <b>{esc(strat)}</b>", "", f"{e}  <b>{esc(s['symbol'])}</b>  <i>({esc(s['market'])})</i>  #{esc(s['id'])}", ""]
    L.append(f"📍 <b>{esc(entry_lbl)}:</b> {code(s['entry'])}")
    L.append(f"🛑 <b>Stop:</b> {code(s['sl'])}")
    if mf:
        L.append(f"🎯 <b>TP (next S/R zone):</b> {code(s['tp'])}  <i>({s['rr']:.2f}R)</i>")
        if s.get("tp1"): L.append(f"🎯 <b>TP1 (1:1.5) reference:</b> {code(s['tp1'])}")
    else:
        if s.get("tp1"): L.append(f"🎯 <b>TP1 (1:1.5):</b> {code(s['tp1'])}")
        L.append(f"🎯 <b>TP2 (1:{s['rr']:g}):</b> {code(s['tp'])}")
    if s.get("strategy") in C.PTP_STRATS: L.append("✂️ <i>Tracked: 50% closed at TP1, SL moved to entry, rest to TP2</i>")
    else: L.append("✂️ <i>Optional: take 50% at TP1, move SL to entry</i>")
    c = s["confidence"]
    L += ["", f"📊 <b>Est. win probability:</b> {esc(c)}%", bar(c) + ("" if mf else "  <i>(needs &gt;25% to break even at 1:3)</i>")]
    L.append(f"📌 <b>Status:</b> {esc(s['status'])}")
    if not s.get("in_session"): L.append("⚠️ <i>Outside London/NY session</i>")
    L.append(f"⏰ {wat(s.get('confirm_time') or s.get('created_at'))}")
    rs = (s.get("reasons") or [])[1:]
    if rs: L += ["", "<b>Why:</b>"] + ["• " + esc(r) for r in rs]
    L += ["", "<i>Not financial advice.</i>"]
    return "\n".join(L)
def fmt_pat(s):
    e = "🟢 <b>LONG</b>" if s["direction"] == "long" else "🔴 <b>SHORT</b>"; sd = 1 if s["direction"] == "long" else -1
    risk = abs(s["entry"] - s["sl"]); tp1 = s["entry"] + sd*1.5*risk; tp2 = s["entry"] + sd*3*risk; tr = float(s["rr"])
    L = ["🧪 <b>EXPERIMENTAL – paper</b>", f"🏷 <b>{NAMES.get(s['strategy'], esc(s['strategy']))}</b>", "",
         f"{e}  <b>{esc(s['symbol'])}</b>  <i>({esc(s['market'])})</i>  #{esc(s['id'])}", "",
         f"📍 <b>Entry (market, 4H close):</b> {code(s['entry'])}", f"🛑 <b>Stop:</b> {code(s['sl'])}",
         f"🎯 <b>TP1 (1:1.5):</b> {code(tp1)}" + ("  ✅ <i>tracked</i>" if tr == 1.5 else ""),
         f"🎯 <b>TP2 (1:3):</b> {code(tp2)}" + ("  ✅ <i>tracked</i>" if tr == 3 else ""), ""]
    c = s["confidence"]; be = 40 if tr == 1.5 else 25
    L += [f"📊 <b>Backtest win rate (confidence):</b> {esc(c)}%", bar(c) + f"  <i>(needs &gt;{be}% to break even at 1:{tr:g})</i>",
          f"📌 <b>Status:</b> {esc(s['status'])}", f"⏰ {wat(s.get('confirm_time') or s.get('created_at'))}"]
    rs = (s.get("reasons") or [])[1:]
    if rs: L += ["", "<b>Why:</b>"] + ["• " + esc(r) for r in rs]
    L += ["", "<i>Paper test only. Not financial advice.</i>"]
    return "\n".join(L)
def send(text, chat_id=None, html=False):
    if not enabled() or not (chat_id or C.TELEGRAM_CHAT_ID): return False
    body = dict(chat_id=chat_id or C.TELEGRAM_CHAT_ID, text=text[:4000], disable_web_page_preview=True)
    if html: body["parse_mode"] = "HTML"
    r = requests.post(API("sendMessage"), json=body, timeout=20)
    if not r.ok and html:   # never lose a signal over markup: fall back to plain text
        import re as _re
        body.pop("parse_mode"); body["text"] = _h.unescape(_re.sub(r"<[^>]+>", "", text))[:4000]
        r = requests.post(API("sendMessage"), json=body, timeout=20)
    return r.ok
def post_group(rows):
    rows = [r for r in rows if r["confidence"] >= C.MIN_CONFIDENCE_TO_POST]
    if not rows: return
    rows.sort(key=lambda r: r["strategy"] != "FVG")   # live FVG first
    text = fmt(rows[0])
    for r in rows[1:]:
        text += (f"\n\n━━━━━━━━━━━━\n🧪 <b>EXPERIMENTAL – paper test</b>\nSame setup, <b>{esc(r['strategy'])}</b> levels (#{r['id']}):\n"
                 f"📍 Entry {code(r['entry'])}\n🛑 Stop {code(r['sl'])}\n🎯 Target {code(r['tp'])}")
    if send(text, html=True):
        for r in rows: db.update(r["id"], posted=1)
def post_signal(s):
    if s["confidence"] >= C.MIN_CONFIDENCE_TO_POST and send(fmt(s), html=True): db.update(s["id"], posted=1)
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
            f"\n⭐ DON20 [PRIMARY]: {d.get('open',0)} open, {d.get('closed',0)} closed, win {d.get('win_rate')}%, net {d.get('net_r',0)}R" 
    if cmd == "/explain":
        s = db.get(int(arg)) if arg.isdigit() else None
        return ai.explain(s) if s else "Usage: /explain <id>"
    if cmd == "/ask": return ai.chat(arg or "Summarise", "\n".join(str(r) for r in db.recent(2)[:20]))
    return HELP
def process_update(u):
    m = u.get("message") or {}
    if m.get("text","").startswith("/"):
        try:
            out = handle(m["text"], m["chat"]["id"])
            send(out, m["chat"]["id"], html=m["text"].split()[0].split("@")[0].lower() == "/signals")
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
