"""2-hourly Telegram summary (posted from the server scheduler)."""
import time, threading
from datetime import datetime, timezone, timedelta
from . import db, telegram, scanner
from .telegram import fmt_price
NAMES = {"FVG": "FVG", "FVG+TREND": "FVG+4H trend [EXP]", "CHK": "Checklist [EXP]", "FVG-PLAN": "FVG plan [EXP]", "FVG-D1": "FVG-D1 [EXPERIMENTAL]"}
def label(r): return " + ".join(NAMES.get(t, t) for t in r["tags"])
def build(hours=2):
    now = datetime.now(timezone.utc); since = (now - timedelta(hours=hours)).isoformat()
    rs = db.recent(10); new = [r for r in rs if r["created_at"] >= since]
    lines = [f"📊 {hours}h summary – {datetime.now().strftime('%d %b %H:%M')} WAT"]
    if new:
        lines.append(f"\nNew signals ({len(new)}):")
        for r in new:
            lines.append(f"• #{r['id']} {label(r)} | {r['symbol']} {r['direction'].upper()} | entry {fmt_price(r['entry'])} SL {fmt_price(r['sl'])} TP {fmt_price(r['tp'])} | est. win {r['confidence']}%")
    else:
        lines.append("\nNo new signals in the last 2h.")
        wl = sorted(scanner.STATE.get("watch", []), key=lambda w: w["dist_pct"])[:5]
        if wl:
            lines.append("Closest to a setup (watch only – not signals):")
            for w in wl:
                where = "inside the 4H FVG" if w["dist_pct"] == 0 else f"{w['dist_pct']}% from the 4H FVG"
                nxt = "waiting for a 15m FVG in the same direction" if w["dist_pct"] == 0 or w["tapped"] else "needs price to reach the zone first"
                lines.append(f"• {w['symbol']} {w['direction']} – price {fmt_price(w['price'])}, {where} ({fmt_price(w['bottom'])}–{fmt_price(w['top'])}); {nxt}")
    op = [r for r in rs if r["status"] in ("open", "pending")]
    lines.append(f"\nOpen/pending ({len(op)}):")
    for r in op[:15]:
        lines.append(f"• #{r['id']} {r['symbol']} {r['direction']} {r['status']} ({label(r)})")
    if len(op) > 15: lines.append(f"… and {len(op)-15} more (see /signals)")
    bs = db.by_strategy()
    lines.append("\nLive stats (60d, net after costs): " + "; ".join(f"{NAMES[k]}: {v['closed']} closed, win {v['win_rate'] if v['win_rate'] is not None else '—'}%, {v['net_r']}R" for k, v in bs.items()))
    return "\n".join(lines)
def due(every_h):
    last = db.kv_get("last_summary_at")
    return not last or datetime.now(timezone.utc) - datetime.fromisoformat(last) >= timedelta(hours=every_h) - timedelta(minutes=2)
def loop(every_h=2):
    while not scanner.STATE.get("last_scan"): time.sleep(10)   # need watchlist data from a scan first
    while True:
        try:
            # persisted timestamp -> restarts/redeploys don't trigger extra summaries; only the scheduler leader sends
            if scanner.STATE.get("leader") and due(every_h):
                ok = telegram.send(build(every_h))
                if ok: db.kv_set("last_summary_at", datetime.now(timezone.utc).isoformat())
                scanner.STATE["last_summary"] = f"{time.strftime('%Y-%m-%d %H:%M %Z')} sent={ok}"
        except Exception as e: scanner.STATE["errors"].append(f"summary: {e}")
        time.sleep(300)
_started = False
def start():
    global _started
    if telegram.enabled() and not _started:
        _started = True; threading.Thread(target=loop, daemon=True).start()
