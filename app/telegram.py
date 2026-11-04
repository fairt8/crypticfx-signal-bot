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
TIER_ICON = {"primary": "⭐", "secondary": "🔷", "retired": "🗄"}
LINE = "━━━━━━━━━━━━━━"
PATS = ("PAT-WEDGE", "PAT-TRIPLE", "PAT-TRIPLE-C", "PAT-CUP", "BRK")
FVG_ORDER = ("FVG-D1", "FVG+TREND", "FVG-PLAN", "FVG")
def mf_label(sym):
    """MF-REJ pair label: the user's 5 designated pairs = Top5; other mapped pairs = Session pair; else dynamic Strong pair."""
    from . import strategy
    if sym in strategy.MF_DESIGNATED: return "⭐ Top5"
    return "🕐 Session pair" if sym in strategy.MF_PAIRS else "⚡ Strong pair"
def _pct(a, b):
    try: return abs(float(a) - float(b)) / float(a) * 100
    except Exception: return 0.0
def badge(k):
    """'⭐ PRIMARY · PAT-WEDGE' – tier badge + short strategy name."""
    from . import strategies as SG
    return f"{SG.label(k)} · {SG.short(k)}"
def _entry_kind(s):
    k = s.get("strategy")
    if k in PATS: return "market, 4H close"
    if k in ("CHK", "MF-REJ"): return "market, 1H close"
    return "limit"
def fmt(s):
    """Signal alert: tier badge, pair, direction, entry, SL, TP, R:R, strategy, WAT time, reasons."""
    from . import strategies as SG
    k = SG.eff(s.get("strategy"), s.get("tags")); mf = k == "MF-REJ"; long = s["direction"] == "long"
    e = "🟢 <b>LONG</b>" if long else "🔴 <b>SHORT</b>"
    rr = float(s.get("rr") or 0); c = s.get("confidence") or 0
    L = [f"{TIER_ICON.get(SG.status(k), '')} <b>{esc(SG.LABEL[SG.status(k)].split(' ', 1)[-1])} · {esc(SG.short(k))}</b>", LINE,
         f"{e}  <b>{esc(s['symbol'])}</b>  · {esc(s['market'])}  #{esc(s.get('id', '–'))}", "",
         f"📍 <b>Entry</b>   {code(s['entry'])}  <i>({_entry_kind(s)})</i>",
         f"🛑 <b>Stop</b>    {code(s['sl'])}  <i>(−{_pct(s['entry'], s['sl']):.2f}%)</i>",
         f"🎯 <b>Target</b>  {code(s['tp'])}  <i>(+{_pct(s['entry'], s['tp']):.2f}%{', next S/R zone' if mf else ''})</i>",
         f"⚖️ <b>R:R</b>     1:{rr:.2f}" if mf else f"⚖️ <b>R:R</b>     1:{rr:g}"]
    if s.get("stop_mode") == "c60" or (k == "FVG+TREND" and s.get("status") == "pending"):
        L.append("⏳ <i>Provisional SL/TP – final levels are set from the last closed 1h candle when the limit fills (you get a fill note).</i>")
    if k in C.PTP_STRATS and rr > 1.5 and s.get("tp1"): L.append(f"✂️ <i>Tracked: 50% at TP1 {esc(fmt_price(s['tp1']))} (1:1.5), SL to entry</i>")
    L += [f"📊 <b>Win prob</b> {esc(c)}%  {bar(c, 8)}",
          f"🧭 <b>Strategy</b> {esc(SG.name(k))}" + (f"  {mf_label(s.get('symbol'))}" if mf else ""),
          f"🕒 {wat(s.get('confirm_time') or s.get('created_at'))}  · {esc(s.get('status', 'new'))}"]
    if s.get("market") == "forex" and s.get("in_session") is False and k not in PATS: L.append("⚠️ <i>Outside London/NY session</i>")
    rs = [r for r in (s.get("reasons") or [])[1:] if r]
    if rs: L += ["", "💡 <b>Why</b>"] + ["• " + esc(r) for r in rs[:8]]
    L += ["", "<i>Not financial advice.</i>"]
    return "\n".join(L)
fmt_pat = fmt   # PAT-*/BRK share the same card
def fmt_fill(sig, info, filled):
    """FVG+TREND fill note: the final 1h-candle stop and 3R target (set at the fill)."""
    from . import strategies as SG
    k = SG.eff(sig.get("strategy"), sig.get("tags"))
    return "\n".join([f"✅ <b>FILLED · {esc(badge(k))}</b>", LINE,
        f"{'🟢 LONG' if sig['direction']=='long' else '🔴 SHORT'}  <b>{esc(sig['symbol'])}</b>  #{esc(sig.get('id'))}",
        f"📍 <b>Entry</b>   {code(sig['entry'])}", f"🛑 <b>Final stop</b>   {code(info['sl'])}  <i>(−{_pct(sig['entry'], info['sl']):.2f}%, last closed 1h candle)</i>",
        f"🎯 <b>Final target</b> {code(info['tp'])}  <i>(1:3)</i>", f"🕒 filled {wat(filled)}"])
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
    from . import alerts
    rows, _muted = alerts.filter_push(rows)   # alert mode: muted rows stay saved + tracked, just not pushed
    if not rows: return
    rows.sort(key=lambda r: FVG_ORDER.index(r["strategy"]) if r["strategy"] in FVG_ORDER else 9)
    text = fmt(rows[0])
    for r in rows[1:]:
        text += (f"\n\n{LINE}\n➕ <b>Same setup · {esc(badge(r['strategy']))}</b>  #{r['id']}\n"
                 f"📍 {code(r['entry'])}   🛑 {code(r['sl'])}   🎯 {code(r['tp'])}   ⚖️ 1:{float(r['rr']):g}"
                 + ("\n⏳ <i>final SL/TP set at fill</i>" if r["strategy"] == "FVG+TREND" else ""))
    if send(text, html=True):
        for r in rows: db.update(r["id"], posted=1)
def post_signal(s):
    from . import alerts
    if not alerts.filter_push([s])[0]: return
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
    return f"{d}  <b>{esc(r['symbol'])}</b>  · {TIER_ICON.get(SG.status(r['strategy']), '')} <i>{esc(SG.short(r['strategy']))}</i> #{r['id']}"
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
    from . import trades as T, strategies as SG
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
        for r in rows: b = bs.setdefault(SG.short(r["strategy"]), [0, 0, 0.0]); b[0] += 1; b[1] += (r.get("result_r") or 0) > 0; b[2] += r.get("net_r") or 0
        if len(bs) > 1: L += [f"• <b>{esc(k)}</b>: {v[0]} · win {round(100*v[1]/v[0])}% · {v[2]:+.2f}R" for k, v in sorted(bs.items(), key=lambda kv: -kv[1][2])] + ["━━━━━━━━━━━━"]
        L += [_closed_line(r) + "\n" for r in rows[:TG_MAX]] or ["No closed trades in this period."]
    elif state == "pending":
        L = [f"⏳ <b>Pending</b> – signalled, entry not hit yet · {PLBL[per]} ({len(rows)})", "<i>Limit entries expire if not filled in time.</i>", "━━━━━━━━━━━━"]
        L += [f"{_hdr(r)}\n    📍 entry {code(r['entry'])}   🛑 {code(r['sl'])}   🎯 {code(r['tp'])}\n    <i>signalled {_wat(r['created_at'])} WAT</i>\n" for r in rows[:TG_MAX]] or ["Nothing pending."]
    else:
        L = [f"🆕 <b>New signals</b> · {PLBL[per]} ({len(rows)})" if state == "new" else
             f"🗄 <b>Retired strategies</b> – history · {PLBL[per]} ({len(rows)})\n<i>FVG (old live) and PAT-CUP: no new signals; code kept for the monthly backtest.</i>", "━━━━━━━━━━━━"]
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
def cmd_don20(k="DON20"):
    from . import trades as T, strategies as SG
    d = T.don20_pnl(k)
    return "\n".join([f"{TIER_ICON.get(SG.status(k), '')} <b>{SG.LABEL[SG.status(k)].split(' ', 1)[-1]} · {k} live PnL</b>", f"⏰ as of {wat(d['as_of'])}" + (f" · since {_wat(d['since'])} WAT" if d['since'] else ""), "━━━━━━━━━━━━",
        f"🏁 Closed: {d['closed']}  ·  {_sg(d['closed_net_r'], 'R')} net" + (f"  ·  win {d['closed_win_rate']}%" if d['closed_win_rate'] is not None else ""),
        f"📈 Open: {d['open']}  ·  {_sg(d['open_live_net_r'], 'R')} net live  ·  🟩 {d['open_in_profit']} in profit",
        f"💰 <b>Total</b> {_sg(d['total_net_r'], 'R')} net (closed + open live)"])
def cmd_strategies():
    from . import strategies as SG, alerts
    t = alerts.table(); L = ["🧭 <b>Strategies</b>", LINE]; last = None
    for r in SG.listing():
        if r["status"] != last: L.append(f"\n<b>{SG.LABEL[r['status']]}</b>"); last = r["status"]
        v = t.get(r["key"]) or {}
        L.append(f"• {esc(r['name'])}" + ("  💰" if v.get("profitable") else "") + (f"\n    <i>{esc(v.get('verdict'))}</i>" if v and r["status"] != "retired" else ""))
    L += ["", f"🔔 Alert mode: <b>{esc(alerts.MODE_LABEL[alerts.get_mode()])}</b> (/alerts)", f"💰 <i>{esc(alerts.state()['definition'])}</i>"]
    return "\n".join(L)
SIG_TIERS = {"primary": "⭐ PRIMARY", "secondary": "🔷 SECONDARY", "profitable": "💰 Profitable now"}
def _compact(r):
    """One signal in a list: direction, pair, tier badge, levels, R:R, WAT time."""
    from . import strategies as SG
    k = SG.eff(r["strategy"], r.get("tags")); st = {"open": "📈 open", "pending": "⏳ pending"}.get(r["status"], esc(r["status"]))
    return (f"{'🟢' if r['direction']=='long' else '🔴'} <b>{esc(r['symbol'])}</b> {'LONG' if r['direction']=='long' else 'SHORT'} · "
            f"{TIER_ICON.get(SG.status(k), '')} {esc(SG.short(k))} #{r['id']} · {st}\n"
            f"    📍 {code(r['entry'])}  🛑 {code(r['sl'])}  🎯 {code(r['tp'])}  ⚖️ 1:{float(r.get('rr') or 0):.3g}\n"
            f"    🕒 <i>{_wat(r.get('confirm_time') or r['created_at'])} WAT</i>")
def _don_block(k="DON20"):
    from . import trades as T, strategies as SG
    dn = sorted(T.live(T._don_rows(" WHERE status='open'", strategies=(k,))), key=lambda r: str(r.get("created_at") or ""), reverse=True)
    tot = sum(r.get("live_net_r") or 0 for r in dn)
    out = f"{TIER_ICON.get(SG.status(k), '')} <b>{k} open positions</b> ({len(dn)}) · live {_sg(tot, 'R')} net\n" + ("\n".join(_live_line(r) for r in dn[:12]) or f"<i>No open {k} positions.</i>")
    if len(dn) > 12: out += f"\n<i>…and {len(dn)-12} more (/open)</i>"
    return out
def cmd_signals(arg):
    """/signals [primary|secondary|profitable]: open/pending signals; default = both live tiers, grouped by tier."""
    from . import strategies as SG, alerts
    tier = (arg or "").split()[0].lower() if arg else ""
    tier = {"p": "primary", "prim": "primary", "s": "secondary", "sec": "secondary", "profit": "profitable"}.get(tier, tier)
    if tier and tier not in SIG_TIERS: return "Usage: /signals [primary|secondary]   (or /primary, /secondary)"
    rs = [r for r in db.recent(3) if r["status"] in ("pending", "open") and SG.status(SG.eff(r["strategy"], r["tags"])) in SG.TIERS]
    tiers = [tier] if tier else list(SG.TIERS)
    L = [f"📡 <b>Live signals</b> · {' + '.join(SIG_TIERS[t] for t in tiers)}", f"🔔 Alerts: <i>{esc(alerts.MODE_LABEL[alerts.get_mode()])}</i> · /alerts", LINE]
    for t in tiers:
        g = [r for r in rs if alerts.in_tier(SG.eff(r["strategy"], r["tags"]), t)]
        if t == "profitable": L.append(f"<i>💰 now: {esc(', '.join(sorted(alerts.profitable_set())) or 'none')}</i>")
        L.append(f"\n<b>{SIG_TIERS[t]}</b> · {len(g)} open/pending")
        dks = [k for k in ("DON20", "DON28") if SG.active(k) and alerts.in_tier(k, t)]
        for k in dks: L.append(_don_block(k))
        L += [_compact(r) for r in g[:12]] or (["<i>No open/pending signals.</i>"] if not dks else [])
        if len(g) > 12: L.append(f"<i>…and {len(g)-12} more – Mini App ▸ Signals</i>")
    L += ["", "<i>Full card: /explain ID · Mini App: /app</i>"]
    return "\n".join(L)
def _alerts_markup(cur):
    from . import alerts
    btn = lambda m: {"text": ("✅ " if m == cur else "") + alerts.MODE_LABEL[m], "callback_data": "alerts:" + m}
    return {"inline_keyboard": [[btn(m)] for m in alerts.MODES]}
def _alerts_text():
    from . import alerts, strategies as SG
    s = alerts.state()
    pr = ", ".join(SG.short(k) for k in SG.STATUS if SG.status(k) == "primary"); se = ", ".join(SG.short(k) for k in SG.STATUS if SG.status(k) == "secondary")
    return (f"🔔 <b>Alert mode:</b> {esc(s['mode_label'])}\n{LINE}\n⭐ <b>PRIMARY</b>: {esc(pr)}\n🔷 <b>SECONDARY</b>: {esc(se)}\n\n"
            "<i>Signals outside the chosen mode are still saved and tracked (Mini App, /open, /closed) – just not pushed here.</i>\nTap to switch:")
def send_alerts_panel(chat_id=None):
    from . import alerts
    body = dict(chat_id=chat_id or C.TELEGRAM_CHAT_ID, parse_mode="HTML", text=_alerts_text(), reply_markup=_alerts_markup(alerts.get_mode()))
    return requests.post(API("sendMessage"), json=body, timeout=20).ok
def on_callback(q):
    from . import alerts
    chat = ((q.get("message") or {}).get("chat") or {}).get("id")
    if not allowed_chat(chat) or str((q.get("from") or {}).get("id")) != str(C.TELEGRAM_CHAT_ID).strip():
        requests.post(API("answerCallbackQuery"), json=dict(callback_query_id=q["id"]), timeout=10); return
    data = q.get("data") or ""
    if data.startswith("alerts:"):
        m = alerts.set_mode(data.split(":", 1)[1])
        requests.post(API("answerCallbackQuery"), json=dict(callback_query_id=q["id"], text="Alert mode: " + alerts.MODE_LABEL[m]), timeout=10)
        requests.post(API("editMessageText"), json=dict(chat_id=chat, message_id=q["message"]["message_id"], parse_mode="HTML",
                      text=_alerts_text(), reply_markup=_alerts_markup(m)), timeout=10)
    else: requests.post(API("answerCallbackQuery"), json=dict(callback_query_id=q["id"]), timeout=10)
HTML_CMDS = ("/signals", "/primary", "/secondary", "/open", "/closed", "/pending", "/new", "/retired", "/don20", "/don28", "/strategies", "/pnl", "/trades", "/stats", "/help", "/start")
def help_html():
    from . import strategies as SG, alerts
    pr = " · ".join(SG.short(k) for k in SG.STATUS if SG.status(k) == "primary"); se = " · ".join(SG.short(k) for k in SG.STATUS if SG.status(k) == "secondary")
    return ("🤖 <b>CrypticFx Signals</b>\n<i>Crypto + forex setups, tracked live with net R after fees.</i>\n" + LINE + "\n"
        f"⭐ <b>PRIMARY</b>  {esc(pr)}\n🔷 <b>SECONDARY</b>  {esc(se)}\n🔔 Alerts: <b>{esc(alerts.MODE_LABEL[alerts.get_mode()])}</b>\n\n"
        "📡 <b>Signals</b>\n"
        "  /signals – open + pending, by tier\n  /primary · /secondary – one tier only\n  /alerts – push ⭐ only or ⭐ + 🔷\n\n"
        "📈 <b>Trades &amp; PnL</b>\n"
        "  /open – live trades with PnL\n  /closed [day|week|month|all] – results\n  /pending · /new [period]\n"
        "  /pnl SYMBOL · /trades SYMBOL – one token\n  /don20 · /don28 – DON20 ⭐ / DON28 🔷 total PnL\n  /stats – 30-day stats by tier\n\n"
        "🧭 <b>More</b>\n  /strategies – tiers + live verdicts\n  /retired – retired strategy history\n"
        "  /explain ID – full signal card + AI note\n  /ask question – ask AI\n  📱 /app – the Mini App (also the ☰ button)")
HELP = "/signals – open/pending signals\n/primary · /secondary – one tier\n/alerts – alert mode\n/stats – 30-day stats\n/help – all commands"
def cmd_stats():
    from . import strategies as SG
    bs = db.by_strategy(); L = ["📊 <b>Live stats</b> <i>(net R after fees)</i>", LINE]
    for t in SG.TIERS:
        rows = [(k, v) for k, v in bs.items() if SG.status(k) == t]
        n = sum(v.get("closed") or 0 for _, v in rows); net = sum(v.get("net_r") or 0 for _, v in rows)
        L.append(f"\n{SG.LABEL[t]} · {n} closed · {_sg(net, 'R')}")
        for k, v in rows:
            wr = v.get("win_rate"); L.append(f"  • <b>{esc(SG.short(k))}</b>: {v.get('closed', 0)} closed · win {wr if wr is not None else '–'}% · {v.get('net_r', 0):+.2f}R · {v.get('open', 0)} open")
    return "\n".join(L)
def handle(text, chat):
    parts = text.split(maxsplit=1); cmd = parts[0].split("@")[0].lower(); arg = parts[1] if len(parts) > 1 else ""
    if cmd in ("/start", "/help"): return help_html()
    if cmd in ("/open", "/closed", "/pending", "/new", "/retired"): return cmd_trades_state(cmd[1:], arg)
    if cmd == "/don20": return cmd_don20()
    if cmd == "/don28": return cmd_don20("DON28")
    if cmd == "/strategies": return cmd_strategies()
    if cmd in ("/pnl", "/trades"): return cmd_symbol(arg, cmd == "/trades")
    if cmd == "/signals": return cmd_signals(arg)
    if cmd in ("/primary", "/secondary"): return cmd_signals(cmd[1:])
    if cmd == "/stats": return cmd_stats()
    if cmd == "/history":
        d = int(arg) if arg.isdigit() else 7
        rs = db.recent(d)[:30]
        return "\n".join(f"#{r['id']} {r['symbol']} {r['direction']} {r['confidence']}% → {r['status']}" for r in rs) or "No history."
    if cmd == "/explain":
        s = db.get(int(arg)) if arg.isdigit() else None
        if not s: return "Usage: /explain <id>"
        try: send(fmt(s), chat, html=True)
        except Exception: pass
        return ai.explain(s)
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
    if u.get("callback_query"): return on_callback(u["callback_query"])
    m = u.get("message") or {}
    if m.get("text","").startswith("/"):
        chat = (m.get("chat") or {}).get("id")
        if not allowed_chat(chat): return
        try:
            cmd = m["text"].split()[0].split("@")[0].lower()
            if cmd == "/app": send_app_button(chat); return
            if cmd == "/alerts":
                a = m["text"].split(maxsplit=1)
                if len(a) > 1:
                    from . import alerts
                    try: alerts.set_mode(a[1])
                    except ValueError as e: return send(str(e), chat)
                return send_alerts_panel(chat)
            out = handle(m["text"], chat)
            html = cmd in HTML_CMDS
            send_long(out if html else out, chat, html=html)
        except Exception as e: send(f"Error: {type(e).__name__}: {e}"[:500], chat)
def send_app_button(chat_id=None):
    """Reply with an inline web_app button that opens the Mini App (private chat only)."""
    from .webapp import app_url
    url = app_url()
    if not url: return send("Mini app needs a public URL (PUBLIC_URL / RENDER_EXTERNAL_URL).", chat_id)
    body = dict(chat_id=chat_id or C.TELEGRAM_CHAT_ID, parse_mode="HTML", text="📱 <b>CrypticFx mini app</b>\nStats, live PnL, trades, token lookup, strategies and signals in one place.",
                reply_markup={"inline_keyboard": [[{"text": "🚀 Open CrypticFx app", "web_app": {"url": url}}]]})
    return requests.post(API("sendMessage"), json=body, timeout=20).ok
MENU = {"state": "not set"}
def set_menu_button():
    """Owner chat's ☰ menu button -> Mini App (setChatMenuButton, type web_app). Token from env, never logged."""
    from .webapp import app_url
    url = app_url()
    if not (enabled() and url and C.TELEGRAM_CHAT_ID): MENU["state"] = "skipped (no public URL or chat)"; return
    try:
        r = requests.post(API("setChatMenuButton"), json=dict(chat_id=int(str(C.TELEGRAM_CHAT_ID).strip()),
            menu_button={"type": "web_app", "text": "📱 App", "web_app": {"url": url}}), timeout=20).json()
        MENU["state"] = "ok" if r.get("ok") else f"failed: {r.get('description')}"
    except Exception as e: MENU["state"] = f"error: {type(e).__name__}"
    set_commands()
COMMANDS = [("signals", "📡 Open + pending signals by tier"), ("primary", "⭐ PRIMARY signals"), ("secondary", "🔷 SECONDARY signals"),
            ("alerts", "🔔 Push ⭐ only or ⭐ + 🔷"), ("open", "📈 Live trades with PnL"), ("closed", "🏁 Closed results"), ("stats", "📊 30-day stats by tier"),
            ("don20", "⭐ DON20 PnL"), ("strategies", "🧭 Strategy tiers"), ("app", "📱 Open the Mini App"), ("help", "❓ All commands")]
def set_commands():
    """Owner chat's / command menu (setMyCommands, chat scope). Best effort."""
    try:
        requests.post(API("setMyCommands"), json=dict(commands=[dict(command=c, description=d) for c, d in COMMANDS],
                      scope=dict(type="chat", chat_id=int(str(C.TELEGRAM_CHAT_ID).strip()))), timeout=20)
    except Exception: pass
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
    if C.PUBLIC_URL: threading.Thread(target=set_menu_button, daemon=True).start()
    if C.PUBLIC_URL and C.TELEGRAM_MODE != "polling":
        r = requests.post(API("setWebhook"), json=dict(url=C.PUBLIC_URL.rstrip("/") + "/telegram/webhook", secret_token=webhook_secret(),
            allowed_updates=["message", "callback_query"], drop_pending_updates=False), timeout=20).json()
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
        try: r = requests.get(API("getMe"), timeout=10).json(); res = dict(ok=r.get("ok"), description=r.get("description"), username=(r.get("result") or {}).get("username"))
        except Exception as e: res = dict(ok=False, description=type(e).__name__)
        _SHAPE.update(res=res, t=time.time())
    return dict(length=len(t), bot_id_digits=len(t.split(":")[0]) if ":" in t else 0,
                matches_regex=bool(re.fullmatch(r"\d+:[A-Za-z0-9_-]{30,}", t)),
                getMe_ok=_SHAPE["res"]["ok"], getMe_description=_SHAPE["res"]["description"], bot_username=_SHAPE["res"].get("username"))
