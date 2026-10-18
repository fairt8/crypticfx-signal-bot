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
NAMES = {"FVG":"FVG (live)","FVG+TREND":"FVG + 4H trend filter","CHK":"Varsity checklist","FVG-PLAN":"FVG creator plan (swing stop)","FVG-D1":"FVG-D1 daily bias","MF-REJ":"FOREX MF-REJ · Market Fluidity zone rejection (1H)",
         "PAT-WEDGE":"PAT-WEDGE · 4H wedge breakout retest","PAT-TRIPLE":"PAT-TRIPLE · 4H triple top/bottom retest (FX)","PAT-CUP":"PAT-CUP · 4H cup &amp; handle retest","BRK":"BRK · 4H pattern neckline/trendline breakout"}
PATS = ("PAT-WEDGE", "PAT-TRIPLE", "PAT-CUP", "BRK")
def mf_label(sym):
    """MF-REJ pair label: the user's 5 designated pairs = Top5; other mapped pairs = Session pair; else dynamic Strong pair."""
    from . import strategy
    if sym in strategy.MF_DESIGNATED: return "⭐ Top5"
    return "🕐 Session pair" if sym in strategy.MF_PAIRS else "⚡ Strong pair"
def fmt(s):
    e = "🟢 <b>LONG</b>" if s["direction"] == "long" else "🔴 <b>SHORT</b>"
    tags = s.get("tags") or ["FVG"]; mf = s.get("strategy") == "MF-REJ"
    if s.get("strategy") in PATS: return fmt_pat(s)
    from . import strategies as SG
    k = SG.eff(s.get("strategy"), tags); strat = SG.name(k)
    if mf: strat += "  " + mf_label(s.get("symbol"))
    entry_lbl = "Entry (market, 1H close)" if s.get("strategy") in ("CHK", "MF-REJ") else "Entry (limit)"
    L = []
    L.append(f"<b>{SG.label(k)}</b>" + ("  <i>– collecting live results</i>" if SG.status(k) == "experimental" else ""))
    L += [f"🏷 <b>Strategy: {esc(strat)}</b>", "", f"{e}  <b>{esc(s['symbol'])}</b>  <i>({esc(s['market'])})</i>  #{esc(s['id'])}", ""]
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
    from . import strategies as SG
    L = [f"<b>{SG.label(s['strategy'])}</b>" + ("  <i>– paper test</i>" if SG.status(s['strategy']) == "experimental" else ""),
         f"🏷 <b>Strategy: {esc(SG.name(s['strategy']))}</b>", "",
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
    from . import strategies as SG
    rows.sort(key=lambda r: ("FVG-D1", "FVG", "FVG-PLAN").index(r["strategy"]) if r["strategy"] in ("FVG-D1", "FVG", "FVG-PLAN") else 9)
    text = fmt(rows[0])
    for r in rows[1:]:
        text += (f"\n\n━━━━━━━━━━━━\n<b>{SG.label(r['strategy'])}</b>\nSame setup, <b>{esc(SG.name(r['strategy']))}</b> levels (#{r['id']}):\n"
                 f"📍 Entry {code(r['entry'])}\n🛑 Stop {code(r['sl'])}\n🎯 Target {code(r['tp'])}")
    if send(text, html=True):
        for r in rows: db.update(r["id"], posted=1)
def post_signal(s):
    if s["confidence"] >= C.MIN_CONFIDENCE_TO_POST and send(fmt(s), html=True): db.update(s["id"], posted=1)
# ---------- trade lists + PnL commands (app/trades.py) ----------
def _wat(x):
    from .trades import _ts
    t = _ts(x); return (t + _td(hours=1)).strftime("%d %b %H:%M") if t else "?"
def _sg(v, suf="", nd=2):
    if v is None: return "–"
    return f"{'🟩' if v > 0 else '🟥' if v < 0 else '⬜'} <b>{v:+.{nd}f}{suf}</b>"
def _hdr(r):
    d = "🟢 LONG" if r["direction"] == "long" else "🔴 SHORT"
    from . import strategies as SG
    sn = "FOREX MF-REJ" if r["strategy"] == "MF-REJ" else r["strategy"]
    return f"{d}  <b>{esc(r['symbol'])}</b>  · <i>{esc(sn)}</i> {SG.label(r['strategy']).split()[0]} #{r['id']}"
def _live_line(r):
    if r.get("price_now") is None: return f"{_hdr(r)}\n    📍 {code(r['entry'])} → <i>price unavailable</i>"
    return (f"{_hdr(r)}\n    📍 {code(r['entry'])} → {code(r['price_now'])}   🛑 {code(r['sl'])}\n"
            f"    {_sg(r['live_pct'], '%')}   {_sg(r['live_r'], 'R')}   <i>net {r['live_net_r']:+.2f}R</i>")
def _closed_line(r):
    ic = {"tp": "✅", "sl": "❌", "be": "➖", "cancelled": "🚫"}.get(r["status"]) or ("✅" if (r.get("net_r") or 0) > 0 else "❌")
    return f"{ic} {_hdr(r)}\n    {_sg(r.get('net_r'), 'R')}   {_sg(r.get('net_pct'), '%')}   <i>closed {_wat(r['closed_at'])} WAT</i>"
TG_MAX = 40   # rows per Telegram list (totals always cover all rows)
PLBL = {"day": "today (24h)", "today": "today (24h)", "week": "last 7 days", "month": "last 30 days", "all": "all time"}
def cmd_trades_state(state, arg):
    from . import trades as T
    per = (arg or "all").split()[0].lower() if arg else "all"
    if per not in T.PERIODS: return f"Period must be one of: day, week, month, all"
    rows = T.by_state(state, per); L = []
    if state == "open":
        rows.sort(key=lambda r: -(r.get("live_net_r") if r.get("live_net_r") is not None else -99))
        tot = sum(r.get("live_net_r") or 0 for r in rows); up = sum((r.get("live_r") or 0) > 0 for r in rows)
        L = [f"📈 <b>Currently trading</b> ({len(rows)} open)", f"💰 Live total {_sg(tot, 'R')} net   ·   🟩 {up} in profit / 🟥 {len(rows)-up}", "━━━━━━━━━━━━"]
        L += [_live_line(r) + "\n" for r in rows[:TG_MAX]] or ["No open trades."]
    elif state == "closed":
        w = sum((r.get("result_r") or 0) > 0 for r in rows); n = sum(r.get("net_r") or 0 for r in rows)
        L = [f"🏁 <b>Closed trades</b> · {PLBL[per]} ({len(rows)})",
             f"🎯 Win {round(100*w/len(rows)) if rows else 0}%   ·   💰 {_sg(n, 'R')} net (after fees)", "━━━━━━━━━━━━"]
        bs = {}
        for r in rows: b = bs.setdefault("FOREX MF-REJ" if r["strategy"] == "MF-REJ" else r["strategy"], [0, 0, 0.0]); b[0] += 1; b[1] += (r.get("result_r") or 0) > 0; b[2] += r.get("net_r") or 0
        if len(bs) > 1: L += [f"• <b>{esc(k)}</b>: {v[0]} · win {round(100*v[1]/v[0])}% · {v[2]:+.2f}R" for k, v in sorted(bs.items(), key=lambda kv: -kv[1][2])] + ["━━━━━━━━━━━━"]
        L += [_closed_line(r) + "\n" for r in rows[:TG_MAX]] or ["No closed trades in this period."]
    elif state == "pending":
        L = [f"⏳ <b>Pending</b> – signalled, entry not hit yet · {PLBL[per]} ({len(rows)})", "<i>Limit entries expire if not filled in time.</i>", "━━━━━━━━━━━━"]
        L += [f"{_hdr(r)}\n    📍 entry {code(r['entry'])}   🛑 {code(r['sl'])}   🎯 {code(r['tp'])}\n    <i>signalled {_wat(r['created_at'])} WAT</i>\n" for r in rows[:TG_MAX]] or ["Nothing pending."]
    else:
        L = [f"🆕 <b>New signals</b> · {PLBL[per]} ({len(rows)})" if state == "new" else
             f"🗄 <b>Retired strategies</b> – history · {PLBL[per]} ({len(rows)})\n<i>FVG (live), FVG+TREND, PAT-WEDGE, PAT-CUP: no new signals; code kept for backtests.</i>", "━━━━━━━━━━━━"]
        st = {"retired": "🗄 closed (retired)", "cancelled": "🚫 cancelled", "pending": "⏳ pending", "open": "📈 open", "tp": "✅ TP", "sl": "❌ SL", "be": "➖ BE", "expired": "⌛ expired", "closed": "🏁 closed"}
        for r in rows[:TG_MAX]:
            x = f"{_hdr(r)}\n    {st.get(r['status'], esc(r['status']))}   📍 {code(r['entry'])}   <i>{_wat(r['created_at'])} WAT</i>"
            if r.get("live_r") is not None: x += f"\n    live {_sg(r['live_pct'], '%')} {_sg(r['live_r'], 'R')}"
            if r.get("net_r") is not None: x += f"\n    result {_sg(r['net_r'], 'R')} {_sg(r['net_pct'], '%')}"
            L.append(x + "\n")
        if not rows: L.append("No new signals in this period.")
    if len(rows) > TG_MAX: L.append(f"<i>…and {len(rows)-TG_MAX} more – full list on the dashboard (Trades &amp; PnL), or /pnl SYMBOL.</i>")
    return "\n".join(L)
def cmd_symbol(arg, full):
    from . import trades as T
    if not arg: return f"Usage: /{'trades' if full else 'pnl'} SYMBOL  (e.g. BTCUSDT, BTC, EURUSD, XAUAUD)"
    h = T.history(arg.split()[0]); s = h["summary"]; rows = h["trades"]
    if not rows: return f"No trades found for <b>{esc(s['symbol'])}</b>."
    L = [f"🔎 <b>{esc(s['symbol'])}</b>  {'trade history' if full else 'PnL'}",
         f"📊 {s['trades']} signals · 📈 {s['open']} open · ⏳ {s['pending']} pending · 🏁 {s['closed']} closed",
         f"🎯 Win {s['win_rate'] if s['win_rate'] is not None else '–'}%   ·   💰 closed {_sg(s['net_r'], 'R')} ({s['net_pct']:+.2f}%) net",
         f"⚡ Open now {_sg(s['open_live_net_r'], 'R')} net (live)", "━━━━━━━━━━━━"]
    op = [r for r in rows if r["status"] == "open"]
    if op: L += ["<b>Open</b>"] + [_live_line(r) + "\n" for r in op]
    cl = [r for r in rows if r.get("net_r") is not None]
    if cl: L += ["<b>Closed</b>"] + [_closed_line(r) + "\n" for r in (cl if full else cl[:10])]
    if full:
        other = [r for r in rows if r["status"] not in ("open",) and r.get("net_r") is None]
        if other: L += ["<b>Other</b>"] + [f"{_hdr(r)}  · {esc(r['status'])}  <i>{_wat(r['created_at'])} WAT</i>" for r in other]
    return "\n".join(L)
def cmd_don20():
    from . import trades as T
    d = T.don20_pnl()
    return "\n".join([f"⭐ <b>DON20 live PnL</b>  <i>(PRIMARY)</i>", f"⏰ as of {wat(d['as_of'])}" + (f" · since {_wat(d['since'])} WAT" if d['since'] else ""), "━━━━━━━━━━━━",
        f"🏁 Closed: {d['closed']}  ·  {_sg(d['closed_net_r'], 'R')} net" + (f"  ·  win {d['closed_win_rate']}%" if d['closed_win_rate'] is not None else ""),
        f"📈 Open: {d['open']}  ·  {_sg(d['open_live_net_r'], 'R')} net live  ·  🟩 {d['open_in_profit']} in profit",
        f"💰 <b>Total</b> {_sg(d['total_net_r'], 'R')} net (closed + open live)"])
def cmd_strategies():
    from . import strategies as SG
    L = ["🧭 <b>Strategies</b>", "━━━━━━━━━━━━"]
    for r in SG.listing(): L.append(f"{r['label']} · {esc(r['name'])}")
    return "\n".join(L)
HTML_CMDS = ("/signals", "/open", "/closed", "/pending", "/new", "/retired", "/don20", "/strategies", "/pnl", "/trades", "/help", "/start")
HELP_HTML = ("🤖 <b>CrypticFx signal bot</b>\n\n"
    "📈 /open – currently trading, live PnL (% and R)\n"
    "🏁 /closed [day|week|month|all] – closed trades, net R and %\n"
    "⏳ /pending [day|week|month|all] – signalled, entry not hit yet\n"
    "🆕 /new [day|week|month|all] – new signals\n"
    "💰 /pnl SYMBOL – live + closed PnL for one token\n"
    "📜 /trades SYMBOL – full trade history of one token\n"
    "🗄 /retired [day|week|month|all] – history of retired strategies\n"
    "⭐ /don20 – DON20 total PnL (closed + open live)\n"
    "🧭 /strategies – active strategies and labels\n\n"
    "/signals – open/pending signal cards\n/history [days] – last results\n/stats – 30-day stats\n/explain &lt;id&gt; – AI explanation\n/ask &lt;question&gt; – ask AI")
HELP = "/signals – open/pending signals\n/history [days] – last results (default 7)\n/stats – 30-day stats\n/explain <id> – AI explanation\n/ask <question> – ask AI about recent signals"
def handle(text, chat):
    parts = text.split(maxsplit=1); cmd = parts[0].split("@")[0].lower(); arg = parts[1] if len(parts) > 1 else ""
    if cmd in ("/start","/help"): return HELP_HTML
    if cmd in ("/open", "/closed", "/pending", "/new", "/retired"): return cmd_trades_state(cmd[1:], arg)
    if cmd == "/don20": return cmd_don20()
    if cmd == "/strategies": return cmd_strategies()
    if cmd in ("/pnl", "/trades"): return cmd_symbol(arg, cmd == "/trades")
    if cmd == "/signals":
        from . import strategies as SG
        rs = [r for r in db.recent(3) if r["status"] in ("pending","open") and SG.active(SG.eff(r["strategy"], r["tags"]))][:10]
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
def chunks(text, n=3900):
    """Split on line boundaries so each Telegram message stays under 4096 chars (HTML tags are per-line, so never cut)."""
    out, cur = [], ""
    for ln in text.split("\n"):
        while len(ln) > n: out.append(cur) if cur else None; cur = ""; out.append(ln[:n]); ln = ln[n:]
        if len(cur) + len(ln) + 1 > n: out.append(cur); cur = ln
        else: cur = (cur + "\n" + ln) if cur else ln
    if cur: out.append(cur)
    return [c for c in out if c.strip()]
def send_long(text, chat_id=None, html=False):
    ok = True
    for c in chunks(text): ok = send(c, chat_id, html=html) and ok
    return ok
def allowed_chat(chat):
    """Only the owner chat (TELEGRAM_CHAT_ID) gets answers."""
    return bool(C.TELEGRAM_CHAT_ID) and str(chat) == str(C.TELEGRAM_CHAT_ID).strip()
def process_update(u):
    m = u.get("message") or {}
    if m.get("text","").startswith("/"):
        chat = (m.get("chat") or {}).get("id")
        if not allowed_chat(chat): return
        try:
            cmd = m["text"].split()[0].split("@")[0].lower(); out = handle(m["text"], chat)
            html = cmd in HTML_CMDS
            send_long(out if html else out, chat, html=html)
        except Exception as e: send(f"Error: {type(e).__name__}: {e}"[:500], chat)
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

_WH = {}
def webhook_info():
    """Safe diagnostic (no token/secret): is Telegram delivering to this service's webhook, pending updates, last error."""
    if not enabled(): return None
    if "res" not in _WH or time.time() - _WH.get("t", 0) > 120:
        try:
            i = requests.get(API("getWebhookInfo"), timeout=10).json().get("result", {}); url = i.get("url") or ""
            want = (C.PUBLIC_URL.rstrip("/") + "/telegram/webhook") if C.PUBLIC_URL else None
            res = dict(points_here=bool(want) and url == want, host=url.split("/")[2] if url.count("/") >= 2 else None,
                       pending=i.get("pending_update_count"), last_error=i.get("last_error_message"), last_error_date=i.get("last_error_date"))
        except Exception as e: res = dict(error=type(e).__name__)
        _WH.update(res=res, t=time.time())
    return _WH["res"]
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
