"""Trade lists by state + live / closed PnL (Telegram commands, dashboard 'Trades' panel, /api/trades*).
States (signals table): pending = signalled, entry (limit) not hit yet (expires after PENDING_EXPIRY);
open = entry filled, stop/TP not hit; closed = tp | sl | be (TP1 hit, rest at entry); new = any signal created in the period.
DON20 positions (don20 table) are included as open/closed trades (market entry, trailing stop, no TP).
Net PnL uses the stats convention: db.net_r (signals) and don20 per-side fee (DON20)."""
import time, threading
from datetime import datetime, timezone, timedelta
from . import config as C, db
PERIODS = {"day": 1, "today": 1, "week": 7, "month": 30, "all": None}
def period_days(p): return PERIODS.get((p or "all").lower(), None)
def _since(days): return None if days is None else datetime.now(timezone.utc) - timedelta(days=days)
def _ts(x):
    if not x: return None
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except Exception: return None
def _in(x, since): t = _ts(x); return since is None or (t is not None and t >= since)

# ---------- live prices: batched, cached 60s ----------
_PX = {"t": 0, "crypto": {}, "fx": {}}; _LOCK = threading.Lock()
def _crypto_prices():
    from . import binance
    return {d["symbol"]: float(d["price"]) for d in binance.get("/api/v3/ticker/price")}   # one call, all symbols
def _fx_prices(pairs):
    from . import forex
    pv = forex.provider(); out = {}
    if getattr(pv, "name", "") != "yfinance" or not pairs: return out
    real = list(dict.fromkeys(q for p in pairs for q in forex.SYNTH.get(p, (p,))))
    tk = {pv.ticker(p): p for p in real}
    raw = pv._dl(list(tk), "5m", "5d")
    last = {}
    for t, p in tk.items():
        try:
            df = pv._norm(raw[t] if t in raw.columns.get_level_values(0) else raw)
            if len(df): last[p] = float(df.c.iloc[-1])
        except Exception: pass
    for p in pairs:
        if p in forex.SYNTH:
            a, b = forex.SYNTH[p]
            if a in last and b in last: out[p] = last[a] / last[b]   # synthetic, e.g. XAUAUD = XAUUSD / AUDUSD
        elif p in last: out[p] = last[p]
    return out
def prices(syms_crypto, syms_fx, ttl=60):
    with _LOCK:
        now = time.time(); fresh = now - _PX["t"] < ttl
        if syms_crypto and (not fresh or not _PX["crypto"]):
            try: _PX["crypto"] = _crypto_prices()
            except Exception: pass
        miss = [p for p in syms_fx if not fresh or p not in _PX["fx"]]
        if miss:
            try: _PX["fx"].update(_fx_prices(miss))
            except Exception: pass
        if not fresh: _PX["t"] = now
        return {**{s: _PX["crypto"].get(s) for s in syms_crypto}, **{s: _PX["fx"].get(s) for s in syms_fx}}

# ---------- rows ----------
def _cost(sym, market):
    return db.COST["metal"] if sym.startswith("XA") else db.COST.get(market, 0.0002)
def _sig(r):
    risk = abs(r["entry"] - r["sl"]); rf = risk / r["entry"] if r["entry"] else 0
    d = dict(kind="signal", id=r["id"], symbol=r["symbol"], market=r["market"], strategy=r.get("strategy") or "FVG",
             direction=r["direction"], status=r["status"], entry=r["entry"], sl=r["sl"], tp=r["tp"], rr=r.get("rr"),
             created_at=r.get("created_at"), filled_at=r.get("filled_at"), closed_at=r.get("closed_at"),
             risk_frac=rf, cost=_cost(r["symbol"], r["market"]))
    if r["status"] in db.CLOSED and r.get("result_r") is not None:
        d["result_r"] = round(r["result_r"], 3); n = db.net_r(r); d["net_r"] = round(n, 3)
        d["gross_pct"] = round(r["result_r"]*rf*100, 3); d["net_pct"] = round(n*rf*100, 3)
    return d
def _don(p):
    st = "open" if p["status"] == "open" else "closed"; risk = abs(p["entry"] - p["init_stop"])
    d = dict(kind="don20", id=p["id"], symbol=p["symbol"], market="crypto", strategy="DON20", direction=p["direction"],
             status=st, entry=p["entry"], sl=p["stop"], init_stop=p["init_stop"], tp=None, rr=None,
             created_at=p.get("opened_at"), filled_at=p.get("opened_at"), closed_at=p.get("closed_at"),
             risk_frac=risk/p["entry"] if p["entry"] else 0, cost=0.001)
    if st == "closed" and p.get("exit_price") is not None:
        sd = 1 if p["direction"] == "long" else -1; x = p["exit_price"]
        d.update(exit_price=x, result_r=round(p["result_r"] or 0, 3), net_r=round(p["net_r"] or 0, 3),
                 gross_pct=round(sd*(x-p["entry"])/p["entry"]*100, 3),
                 net_pct=round((sd*(x-p["entry"]) - 0.001*(p["entry"]+x))/p["entry"]*100, 3))
    return d
def _don_rows(where="", params=()):
    try:
        from . import don20
        return [_don(p) for p in don20._rows("SELECT * FROM don20" + where + " ORDER BY id DESC", params)]
    except Exception: return []
def _sig_rows(where, params=()):
    with db.conn() as c:
        return [_sig(db.row(r)) for r in c.execute("SELECT * FROM signals " + where + " ORDER BY id DESC", params)]
def live(rows):
    """Add price_now, live_pct, live_r (gross) and live_net_r (minus round-trip cost) to open rows; direction respected."""
    op = [r for r in rows if r["status"] == "open"]
    px = prices(sorted({r["symbol"] for r in op if r["market"] == "crypto"}), sorted({r["symbol"] for r in op if r["market"] != "crypto"}))
    for r in op:
        p = px.get(r["symbol"]); r["price_now"] = p
        if not p: continue
        sd = 1 if r["direction"] == "long" else -1; risk = r["risk_frac"]*r["entry"]
        r["live_pct"] = round(sd*(p-r["entry"])/r["entry"]*100, 3)
        r["live_r"] = round(sd*(p-r["entry"])/risk, 3) if risk else None
        if r["kind"] == "don20": fee = 0.001*(r["entry"]+p)/risk if risk else 0
        else: fee = r["cost"]/r["risk_frac"] if r["risk_frac"] else 0
        r["live_net_r"] = round(r["live_r"] - fee, 3) if r["live_r"] is not None else None
    return rows
def by_state(state, period="all"):
    since = _since(period_days(period)); state = (state or "open").lower()
    if state == "open": rows = _sig_rows("WHERE status='open'") + _don_rows(" WHERE status='open'"); return live(rows)
    if state == "pending": return [r for r in _sig_rows("WHERE status='pending'") if _in(r["created_at"], since)]
    if state == "closed":
        rows = _sig_rows("WHERE status IN ('tp','sl','be')") + _don_rows(" WHERE status<>'open'")
        rows = [r for r in rows if _in(r["closed_at"] or r["created_at"], since)]
        rows.sort(key=lambda r: str(_ts(r["closed_at"]) or ""), reverse=True); return rows
    if state == "new":
        rows = [r for r in _sig_rows("WHERE 1=1") if _in(r["created_at"], since)] + [r for r in _don_rows() if _in(r["created_at"], since)]
        rows.sort(key=lambda r: str(_ts(r["created_at"]) or ""), reverse=True); return live(rows)
    raise ValueError("state must be open|pending|closed|new")
def norm_symbol(s):
    s = (s or "").upper().replace("/", "").replace("-", "").strip()
    with db.conn() as c:
        if c.execute("SELECT 1 FROM signals WHERE symbol=? LIMIT 1", (s,)).fetchone(): return s
    if not s.endswith("USDT") and len(s) <= 6 and s not in ("XAUUSD","XAGUSD","XAUAUD"):
        try:
            with db.conn() as c:
                if c.execute("SELECT 1 FROM signals WHERE symbol=? LIMIT 1", (s+"USDT",)).fetchone(): return s+"USDT"
        except Exception: pass
        if _don_rows(" WHERE symbol=?", (s+"USDT",)): return s+"USDT"
    return s
def history(symbol):
    s = norm_symbol(symbol)
    rows = live(_sig_rows("WHERE symbol=?", (s,)) + _don_rows(" WHERE symbol=?", (s,)))
    rows.sort(key=lambda r: str(_ts(r["created_at"]) or ""), reverse=True)
    cl = [r for r in rows if r.get("net_r") is not None]
    w = sum(r["result_r"] > 0 for r in cl)
    summ = dict(symbol=s, trades=len(rows), open=sum(r["status"] == "open" for r in rows), pending=sum(r["status"] == "pending" for r in rows),
                closed=len(cl), win_rate=round(100*w/len(cl), 1) if cl else None, net_r=round(sum(r["net_r"] for r in cl), 2),
                net_pct=round(sum(r["net_pct"] for r in cl), 2),
                open_live_net_r=round(sum(r.get("live_net_r") or 0 for r in rows if r["status"] == "open"), 2))
    return dict(summary=summ, trades=rows)
