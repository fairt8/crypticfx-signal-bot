"""2-hourly Telegram summary (posted from the server scheduler)."""
import time, threading
from datetime import datetime, timezone, timedelta
from . import db, telegram, scanner
from .telegram import fmt_price
NAMES = {"FVG": "FVG", "FVG+TREND": "FVG+4H trend [EXP]", "CHK": "⭐ CHK checklist [PRIMARY]", "FVG-PLAN": "FVG plan [EXP]", "FVG-D1": "FVG-D1 [EXPERIMENTAL]", "MF-REJ": "FOREX MF-REJ [experimental – collecting live results]", "DON20": "⭐ DON20 [PRIMARY]",
         "PAT-WEDGE": "PAT-WEDGE [EXPERIMENTAL – paper]", "PAT-TRIPLE": "PAT-TRIPLE [EXPERIMENTAL – paper]", "PAT-CUP": "PAT-CUP [EXPERIMENTAL – paper]", "BRK": "BRK [EXPERIMENTAL – paper]"}
def label(r):
    from . import strategies as SG
    k = SG.eff(r.get("strategy"), r.get("tags")); return f"{k} {SG.label(k)}"
def build(hours=2):
    from .telegram import esc, code, wat
    now = datetime.now(timezone.utc); since = (now - timedelta(hours=hours)).isoformat()
    rs = db.recent(10); new = [r for r in rs if r["created_at"] >= since]
    L = [f"📊 <b>{hours}h SUMMARY</b>", f"⏰ {wat()}", "━━━━━━━━━━━━"]
    if new:
        L += ["", f"🆕 <b>New signals ({len(new)})</b>"]
        for r in new:
            d = "🟢 LONG" if r["direction"] == "long" else "🔴 SHORT"
            L.append(f"• #{r['id']} {d} <b>{esc(r['symbol'])}</b> · {esc(label(r))}\n   📍 {code(r['entry'])}  🛑 {code(r['sl'])}  🎯 {code(r['tp'])}  📊 {r['confidence']}%")
    else:
        L += ["", "💤 <i>No new signals in the last 2h.</i>"]
        wl = sorted(scanner.STATE.get("watch", []), key=lambda w: w["dist_pct"])[:5]
        if wl:
            L += ["", "👀 <b>Closest to a setup</b> <i>(watch only – not signals)</i>"]
            for w in wl:
                where = "inside the 4H FVG" if w["dist_pct"] == 0 else f"{w['dist_pct']}% from the 4H FVG"
                nxt = "waiting for a 15m FVG in the same direction" if w["dist_pct"] == 0 or w["tapped"] else "needs price to reach the zone first"
                L.append(f"• <b>{esc(w['symbol'])}</b> {esc(w['direction'])} – price {code(w['price'])}, {where} ({code(w['bottom'])}–{code(w['top'])}); {nxt}")
    from . import strategies as SG
    op = [r for r in rs if r["status"] in ("open", "pending") and SG.active(SG.eff(r["strategy"], r["tags"]))]
    L += ["", f"📂 <b>Open/pending ({len(op)})</b>"]
    for r in op[:15]:
        d = "🟢" if r["direction"] == "long" else "🔴"
        L.append(f"• #{r['id']} {d} {esc(r['symbol'])} {esc(r['status'])} <i>({esc(label(r))})</i>")
    if len(op) > 15: L.append(f"… and {len(op)-15} more (see /signals)")
    bs = db.by_strategy()
    L += ["", "📈 <b>Live stats</b> <i>(60d, net after costs)</i>"]
    ret = [k for k, v in bs.items() if v.get("status") == "retired"]
    for k, v in bs.items():   # PRIMARY, NORMAL, EXPERIMENTAL
        if v.get("status") == "retired": continue
        wr = v['win_rate'] if v['win_rate'] is not None else '—'
        dot = "🟢" if v['net_r'] > 0 else ("🔴" if v['net_r'] < 0 else "⚪")
        extra = f" · {v.get('open',0)} open" if k == "DON20" else ""
        L.append(f"{dot} {esc(v.get('label', k))}: {v['closed']} closed{extra} · win {wr}% · <code>{v['net_r']}R</code>")
    try:
        from . import alerts
        mode = alerts.get_mode()
        if mode != "all":
            mu = alerts.muted_since(hours); by = {}
            for m in mu: by[m["strategy"]] = by.get(m["strategy"], 0) + 1
            L += ["", f"🔕 <b>Alert mode:</b> {esc(alerts.MODE_LABEL[mode])} · {len(mu)} signal(s) muted in {hours}h"
                  + (f" ({esc(', '.join(f'{k} {v}' for k, v in sorted(by.items())))})" if by else "") + " – still tracked, see /new"]
    except Exception: pass
    if ret: L.append(f"🗄 <i>Retired (no new signals): {esc(', '.join(ret))} – see /retired</i>")
    return "\n".join(L)
def due(every_h):
    last = db.kv_get("last_summary_at")
    return not last or datetime.now(timezone.utc) - datetime.fromisoformat(last) >= timedelta(hours=every_h) - timedelta(minutes=2)
def loop(every_h=2):
    while not scanner.STATE.get("last_scan"): time.sleep(10)   # need watchlist data from a scan first
    while True:
        try:
            # persisted timestamp -> restarts/redeploys don't trigger extra summaries; only the scheduler leader sends
            if scanner.STATE.get("leader") and due(every_h):
                ok = telegram.send(build(every_h), html=True)
                if ok: db.kv_set("last_summary_at", datetime.now(timezone.utc).isoformat())
                scanner.STATE["last_summary"] = f"{time.strftime('%Y-%m-%d %H:%M %Z')} sent={ok}"
        except Exception as e: scanner.STATE["errors"].append(f"summary: {e}")
        time.sleep(300)
_started = False
def start():
    global _started
    if telegram.enabled() and not _started:
        _started = True; threading.Thread(target=loop, daemon=True).start()
