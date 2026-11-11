"""Weekly strategy report from live Neon/SQLite stats, posted to the owner Telegram chat.

Usage:  python -m app.weekly_report [--no-telegram]

Builds per-strategy stats for the past 7 days and all-time (signals, win rate, average
net R, PnL in R and in $ on the $1,000 account / $10-per-1R default, tier, open trades)
and a short note on strategies flagged as unprofitable by app.alerts. Reuses db, trades,
don20, alerts and telegram. Does not start the scanner and does not change signal
generation, alerts or auto-trade. Intended to run from the fvg-weekly-report.timer.
"""
import argparse, sys
from datetime import datetime, timezone, timedelta
from . import config as C, db, telegram, strategies as SG
from .telegram import esc, wat

ACCOUNT_START = 1000
ACCOUNT_RISK = 10          # $ per 1R on the default paper account
WEEK_DAYS = 7
KV_LAST = "weekly_report:last"


def usd(net_r):
    if net_r is None: return None
    return round(float(net_r) * ACCOUNT_RISK, 2)

def _fmt_r(x):
    return "—" if x is None else f"{x:+.2f}R"

def _fmt_usd(x):
    if x is None: return "—"
    sign = "−" if x < 0 else ("+" if x > 0 else "")
    return f"{sign}${abs(x):,.2f}"

def _fmt_wr(x):
    return "—" if x is None else f"{x:g}%"

def _win_rate(closed):
    if not closed: return None
    w = sum((r.get("net_r") or 0) > 0 for r in closed)
    return round(100 * w / len(closed), 1)

def _net(closed):
    if not closed: return 0.0, None
    nets = [r["net_r"] for r in closed if r.get("net_r") is not None]
    if not nets: return 0.0, None
    total = round(sum(nets), 2)
    return total, round(total / len(nets), 3)

def _block(signals, closed, open_rows):
    net_r, avg = _net(closed)
    live = [r.get("live_net_r") for r in open_rows if r.get("live_net_r") is not None]
    return dict(signals=len(signals), closed=len(closed), open=len(open_rows),
                win_rate=_win_rate(closed), net_r=net_r, avg_r=avg, pnl_usd=usd(net_r),
                open_live_net_r=round(sum(live), 2) if live else None,
                open_live_usd=usd(round(sum(live), 2)) if live else None)

def _mark_open(open_rows):
    """Best-effort live mark-to-market; never fail the report if prices are unavailable."""
    try:
        from . import trades
        return trades.live(open_rows)
    except Exception:
        return open_rows

def collect(now=None, week_days=WEEK_DAYS, profit_table=None):
    """Return a JSON-serialisable report dict. `now` is UTC. Does not send Telegram."""
    from . import trades, don20
    don20.init()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None: now = now.replace(tzinfo=timezone.utc)
    week_since = now - timedelta(days=week_days)
    rows = trades._sig_rows("WHERE status<>'filtered'") + trades._don_rows()
    first = None
    for r in rows:
        t = trades._ts(r.get("created_at"))
        if t and (first is None or t < first): first = t
    open_rows = _mark_open([r for r in rows if r["status"] in ("open", "pending")])
    keys = list(SG.STATUS)

    def for_window(since):
        sigs = [r for r in rows if trades._in(r.get("created_at"), since)]
        closed = [r for r in rows if r.get("net_r") is not None and trades._in(r.get("closed_at"), since)]
        strat = {}
        for k in keys:
            sk = [r for r in sigs if r.get("strategy") == k]
            ck = [r for r in closed if r.get("strategy") == k]
            ok = [r for r in open_rows if r.get("strategy") == k]
            strat[k] = dict(_block(sk, ck, ok), key=k, short=SG.short(k), name=SG.name(k),
                            status=SG.status(k), label=SG.label(k), paused=SG.paused(k))
        return dict(since=since.isoformat() if since else None, total=_block(sigs, closed, open_rows), strategies=strat)

    if profit_table is None:
        try:
            from . import alerts
            profit_table = alerts.table()
        except Exception:
            profit_table = {}
    flagged = []
    for k in keys:
        v = profit_table.get(k) or {}
        if v.get("profitable") is False and SG.status(k) != "retired":
            flagged.append(dict(key=k, short=SG.short(k), label=SG.label(k), verdict=v.get("verdict") or "📉 not profitable"))
    retired = [k for k in keys if SG.status(k) == "retired"]
    return dict(
        generated_at=now.isoformat(), week_days=week_days,
        account=dict(start=ACCOUNT_START, risk=ACCOUNT_RISK),
        first_signal=first.isoformat() if first else None,
        week=for_window(week_since), all_time=for_window(None),
        unprofitable=flagged, retired=retired,
    )

def format_report(data, now=None):
    """HTML Telegram body from collect()."""
    now = now or datetime.now(timezone.utc)
    week_days = data.get("week_days") or WEEK_DAYS
    start = now - timedelta(days=week_days)
    # date labels in WAT (UTC+1)
    def dlab(t):
        if t is None: return "—"
        if isinstance(t, str):
            try: t = datetime.fromisoformat(t.replace("Z", "+00:00"))
            except Exception: return t[:10]
        if t.tzinfo is None: t = t.replace(tzinfo=timezone.utc)
        return t.astimezone(timezone(timedelta(hours=1))).strftime("%d %b %Y")
    acct = data.get("account") or {}
    start_usd = acct.get("start", ACCOUNT_START); risk = acct.get("risk", ACCOUNT_RISK)
    L = [f"📊 <b>Weekly strategy report</b>", f"⏰ {wat(now)}",
         f"<i>Week: {dlab(start)} – {dlab(now)} · All-time since {dlab(data.get('first_signal')) or 'first signal'} · "
         f"${start_usd:,.0f} account, ${risk:g} / 1R</i>", "━━━━━━━━━━━━"]

    def tot_line(label, b):
        live = ""
        if b.get("open") and b.get("open_live_net_r") is not None:
            live = f" <i>(live {_fmt_r(b['open_live_net_r'])} / {_fmt_usd(b['open_live_usd'])})</i>"
        return (f"• <b>{label}</b>: {b['signals']} sig · {b['closed']} closed · win {_fmt_wr(b['win_rate'])} · "
                f"<code>{esc(_fmt_r(b['net_r']))}</code> (<code>{esc(_fmt_usd(b['pnl_usd']))}</code>) · {b['open']} open{live}")

    L += ["", "📈 <b>Totals</b>", tot_line("Week", data["week"]["total"]), tot_line("All-time", data["all_time"]["total"])]

    def strat_line(period, s):
        avg = "" if s["avg_r"] is None else f" · avg <code>{esc(_fmt_r(s['avg_r']))}</code>"
        return (f"  {period}: {s['signals']} sig · {s['closed']} closed · win {_fmt_wr(s['win_rate'])} · "
                f"<code>{esc(_fmt_r(s['net_r']))}</code> (<code>{esc(_fmt_usd(s['pnl_usd']))}</code>){avg} · {s['open']} open")

    for tier in SG.ORDER:
        keys = [k for k, s in data["all_time"]["strategies"].items() if s["status"] == tier]
        if not keys: continue
        L += ["", f"{SG.LABEL[tier]}"]
        for k in keys:
            w, a = data["week"]["strategies"][k], data["all_time"]["strategies"][k]
            L += [f"<b>{esc(SG.short(k))}</b>" + (" <i>(paused)</i>" if a.get("paused") else ""),
                  strat_line("week", w), strat_line("all-time", a)]

    L += ["", "📉 <b>Unprofitable</b>"]
    L.append("<i>Info flag only (30-day live net R, else latest backtest). Signal generation and alerts are unchanged.</i>")
    if data["unprofitable"]:
        for u in data["unprofitable"]:
            L.append(f"• {esc(u['short'])} — {esc(u.get('verdict') or 'not profitable')}")
    else:
        L.append("• None of the live strategies with enough data are flagged as unprofitable.")
    if data.get("retired"):
        L.append(f"🗄 <i>Retired (no new signals): {esc(', '.join(data['retired']))}</i>")
    L += ["", "<i>Not financial advice. Default paper account $1,000 / $10 per 1R.</i>"]
    return "\n".join(L)

def build(now=None, week_days=WEEK_DAYS, profit_table=None):
    now = now or datetime.now(timezone.utc)
    return format_report(collect(now=now, week_days=week_days, profit_table=profit_table), now=now)

def main(argv=None):
    ap = argparse.ArgumentParser(description="Weekly strategy report (Telegram)")
    ap.add_argument("--no-telegram", action="store_true", help="print the report, do not send")
    a = ap.parse_args(argv)
    db.init()
    from . import don20; don20.init()
    text = build()
    print(text, flush=True)
    if a.no_telegram:
        return 0
    if not telegram.enabled() or not C.TELEGRAM_CHAT_ID:
        print("[weekly_report] telegram not configured; skipped send", flush=True)
        return 1
    ok = telegram.send_long(text, html=True)
    print(f"[weekly_report] sent={ok}", flush=True)
    if ok:
        try: db.kv_set(KV_LAST, datetime.now(timezone.utc).isoformat())
        except Exception: pass
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main())
