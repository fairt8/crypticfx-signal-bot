"""Desk view (dashboard / and Mini App /app): equity in R (the UI converts to $ for a configurable account), per-tier and
per-strategy stats, open/pending positions with live price, recent alerts and bot health.

Neon-friendly: one narrow SELECT of open/pending signal rows + the small don20 table every 60s; closed rows (the big part)
are re-read at most every 10 min, or sooner when an open trade disappears (it just closed). Nothing heavy per request."""
import threading, time
from datetime import datetime, timezone, timedelta
from . import config as C, db, strategies as SG

TTL, CLOSED_TTL = 60, 600
COLS = "id,symbol,market,direction,entry,sl,tp,rr,status,strategy,tags,created_at,filled_at,closed_at,result_r,posted"
_LOCK = threading.Lock()
_C = {"t": 0, "v": None, "closed_t": 0, "closed": [], "open_ids": set(), "aux_t": 0, "aux": {}}

def _ts(x):
    from .trades import _ts as t; return t(x)
def _q(sql, p=()):
    with db.conn() as c: return [dict(r) for r in c.execute(sql, p).fetchall()]
def _sig(r):
    from . import trades
    r = dict(r); r["tags"] = (r.get("tags") or "FVG").split(","); r.setdefault("reasons", [])
    d = trades._sig(r); d["posted"] = bool(r.get("posted")); return d

def _closed_rows():
    rs = [_sig(r) for r in _q(f"SELECT {COLS} FROM signals WHERE status IN ('tp','sl','be','retired')")]
    return [r for r in rs if SG.active(r["strategy"]) and r.get("net_r") is not None]

def _dd(series):
    """Max drawdown (R) of a cumulative series starting at 0, and the peak it fell from."""
    peak = best = 0.0; dd = 0.0; dd_peak = 0.0
    for v in series:
        if v > peak: peak = v
        if peak - v > dd: dd, dd_peak = peak - v, peak
    return round(dd, 3), round(dd_peak, 3)

def _sample(pts, n):
    if len(pts) <= n: return pts
    step = (len(pts) - 1) / (n - 1)
    return [pts[round(i * step)] for i in range(n)]

def _block(closed, opened, pending, n_pts=160):
    """Stats + equity series (R) for a set of trades. closed: dicts with net_r/result_r/closed_at; opened: with live_net_r."""
    cl = sorted(closed, key=lambda r: str(_ts(r.get("closed_at")) or ""))
    cum, s, pts = [], 0.0, []
    first = min((str(_ts(r.get("created_at")) or "") for r in closed + opened if r.get("created_at")), default=None)
    if first: pts.append([first[:19] + "Z", 0.0])
    for r in cl:
        s += r["net_r"]; cum.append(s); t = _ts(r.get("closed_at"))
        pts.append([(t.isoformat()[:19] + "Z") if t else None, round(s, 3)])
    unreal = sum(r.get("live_net_r") or 0 for r in opened)
    pts = _sample(pts, n_pts) + [[datetime.now(timezone.utc).isoformat()[:19] + "Z", round(s + unreal, 3)]]
    wins = [r["net_r"] for r in cl if (r.get("result_r") or 0) > 0]; losses = [r["net_r"] for r in cl if (r.get("result_r") or 0) <= 0]
    gw = sum(x for x in (r["net_r"] for r in cl) if x > 0); gl = -sum(x for x in (r["net_r"] for r in cl) if x < 0)
    dd, ddp = _dd(cum)
    return dict(realized_r=round(s, 3), unrealized_r=round(unreal, 3), equity_r=round(s + unreal, 3),
                closed=len(cl), open=len(opened), pending=len(pending), open_priced=sum(r.get("price_now") is not None for r in opened),
                open_in_profit=sum((r.get("live_net_r") or 0) > 0 for r in opened),
                win_rate=round(100 * len(wins) / len(cl), 1) if cl else None,
                avg_r=round(s / len(cl), 3) if cl else None, expectancy_r=round(s / len(cl), 3) if cl else None,
                avg_win_r=round(sum(wins) / len(wins), 3) if wins else None, avg_loss_r=round(sum(losses) / len(losses), 3) if losses else None,
                profit_factor=round(gw / gl, 2) if gl > 0 else (None if not gw else 999),
                max_dd_r=dd, max_dd_peak_r=ddp, since=first,
                last7_r=round(sum(r["net_r"] for r in cl if (_ts(r.get("closed_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= datetime.now(timezone.utc) - timedelta(days=7)), 3),
                series=pts)

def _health(db_err_now=None):
    from . import scanner
    now = time.time(); st = scanner.STATE
    last = st.get("last_scan_ts"); age = round(now - last) if last else None
    started = st.get("scan_started_ts")
    errs = list(db.ERRORS)[-50:]; recent = [e for e in errs if now - e["t"] < 3600]
    quota = [e for e in recent if e.get("kind") == "quota"]
    scan_errs = [str(e) for e in st.get("errors", [])[-20:]]
    notes = []
    if quota or any("quota" in e.lower() for e in scan_errs[-10:]):
        notes.append(dict(level="bad", text="Database quota errors in the last hour (Neon free plan). Signals may be missed until the quota resets."))
    elif recent or db_err_now:
        notes.append(dict(level="warn", text=f"{len(recent) or 1} database error(s) in the last hour. Data shown may be a few minutes old."))
    if age is not None and age > 1800:
        notes.append(dict(level="bad", text=f"No completed scan for {age // 60} min (normally every {C.SCAN_MINUTES} min)."))
    elif age is None and st.get("leader") is False:
        notes.append(dict(level="warn", text="This instance is not the scanner leader yet."))
    return dict(last_scan=st.get("last_scan"), last_scan_age_s=age, scan_started_age_s=round(now - started) if started else None,
                stale=bool(age is not None and age > 1800), scan_minutes=C.SCAN_MINUTES, leader=st.get("leader"),
                db_errors_1h=len(recent), db_quota_errors_1h=len(quota), last_db_error_age_s=round(now - errs[-1]["t"]) if errs else None,
                scan_errors=len(scan_errs), sessions=st.get("sessions"), counts=st.get("last_counts"), notes=notes)

def _aux():
    """Rarely-changing extras (10 min cache): strategy listing, alert mode/profitable table, monthly backtest."""
    if _C["aux"] and time.time() - _C["aux_t"] < CLOSED_TTL: return _C["aux"]
    from . import alerts, variants as V
    out = dict(listing=[dict(x, stop=V.DESC.get(V.MODE.get(x["key"]), "strategy rules")) for x in SG.listing()])
    try: out["alerts"] = alerts.state()
    except Exception: out["alerts"] = None
    try:
        from .webapp import latest_backtest; out["backtest"] = latest_backtest()
    except Exception: out["backtest"] = None
    _C.update(aux=out, aux_t=time.time()); return out

def _alerts_feed(sigs, dons, muted):
    """Recent alerts (7 days): signal rows with posted flag + DON20 entries (muted = saved but not pushed by alert mode)."""
    since = datetime.now(timezone.utc) - timedelta(days=7); out = []
    mk = {(m.get("symbol"), m.get("strategy")) for m in muted}
    for r in sigs:
        t = _ts(r.get("created_at"))
        if t and t >= since: out.append(dict(r, sent=r["posted"]))
    for r in dons:
        t = _ts(r.get("created_at"))
        if t and t >= since: out.append(dict(r, sent=(r["symbol"], "DON20") not in mk))
    out.sort(key=lambda r: str(_ts(r.get("created_at")) or ""), reverse=True)
    keep = ("kind", "id", "symbol", "market", "strategy", "strategy_status", "strategy_short", "direction", "status", "entry", "sl", "tp", "rr",
            "created_at", "net_r", "live_net_r", "sent")
    return [{k: r.get(k) for k in keep} for r in out[:80]]

POS_KEYS = ("kind", "id", "symbol", "market", "strategy", "strategy_status", "strategy_short", "direction", "status", "entry", "sl", "init_stop",
            "tp", "rr", "created_at", "filled_at", "price_now", "live_pct", "live_r", "live_net_r", "risk_frac")

def compute():
    from . import trades, alerts
    now = time.time(); db_err = None
    # open/pending signals (small) + all DON20 rows (small table) every call
    act = [_sig(r) for r in _q(f"SELECT {COLS} FROM signals WHERE status IN ('open','pending') OR created_at >= ?",
                                ((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),))]
    act = [r for r in act if SG.active(r["strategy"])]
    dons = trades._don_rows()
    op = trades.live([r for r in act if r["status"] == "open"] + [r for r in dons if r["status"] == "open"])
    pend = [r for r in act if r["status"] == "pending"]
    ids = {r["id"] for r in op if r["kind"] == "signal"}
    gone = sorted(_C["open_ids"] - ids)
    if now - _C["closed_t"] > CLOSED_TTL or not _C["closed_t"]:
        _C["closed"] = _closed_rows(); _C["closed_t"] = now
    elif gone:   # trades that closed since the last call: fetch just those rows
        have = {r["id"] for r in _C["closed"]}
        new = [_sig(r) for r in _q(f"SELECT {COLS} FROM signals WHERE id IN ({','.join('?' * len(gone[:500]))})", tuple(gone[:500]))]
        _C["closed"] = _C["closed"] + [r for r in new if r["status"] in db.CLOSED and r["id"] not in have and SG.active(r["strategy"]) and r.get("net_r") is not None]
    _C["open_ids"] = ids
    closed = _C["closed"] + [r for r in dons if r["status"] == "closed" and r.get("net_r") is not None]
    keys = [k for k in SG.STATUS if SG.active(k)]
    strat = {}
    for k in keys:
        b = _block([r for r in closed if r["strategy"] == k], [r for r in op if r["strategy"] == k], [r for r in pend if r["strategy"] == k], 60)
        strat[k] = dict(b, key=k, tier=SG.status(k), short=SG.short(k), name=SG.name(k), paused=SG.paused(k))
    tiers = {t: dict(_block([r for r in closed if SG.status(r["strategy"]) == t], [r for r in op if SG.status(r["strategy"]) == t],
                            [r for r in pend if SG.status(r["strategy"]) == t], 100), tier=t, strategies=[k for k in keys if SG.status(k) == t]) for t in SG.TIERS}
    total = _block(closed, op, pend, 240)
    try: muted = alerts.muted_since(168)
    except Exception: muted = []
    op.sort(key=lambda r: -(r.get("live_net_r") if r.get("live_net_r") is not None else -99))
    aux = _aux()
    return dict(as_of=datetime.now(timezone.utc).isoformat(), total=total, tiers=tiers, strategies=strat,
                positions=dict(open=[{k: r.get(k) for k in POS_KEYS} for r in op], pending=[{k: r.get(k) for k in POS_KEYS} for r in pend]),
                alerts_feed=_alerts_feed([r for r in act if r["kind"] == "signal"], [r for r in dons], muted),
                alert_mode=(aux.get("alerts") or {}).get("mode"), alert_label=(aux.get("alerts") or {}).get("mode_label"),
                listing=aux["listing"], alerts=aux.get("alerts"), backtest=aux.get("backtest"),
                account_default=dict(start=1000, risk=10), health=_health(db_err), cached_s=TTL)

def get():
    """Cached desk payload. On a DB error, serve the last good payload (marked stale) with a fresh health block."""
    with _LOCK:
        if _C["v"] is not None and time.time() - _C["t"] < TTL: return dict(_C["v"], health=_health())
        try:
            v = compute(); _C.update(v=v, t=time.time()); return v
        except Exception as e:
            db.note_error(e)
            if _C["v"] is not None:
                _C["t"] = time.time() - TTL + 20   # retry in ~20s
                return dict(_C["v"], stale=True, health=_health(True))
            raise
