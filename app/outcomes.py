"""Outcome tracking on 5m candles: pending -> open (entry touched) -> tp/sl; pending >24h -> expired.
Same-candle TP+SL counts as SL (conservative)."""
import pandas as pd
from . import config as C, db, binance, forex
def simulate(sig, m5, expiry=None):
    expiry = expiry or C.PENDING_EXPIRY
    """Pure: returns (status, filled_at, closed_at, result_r). Same-candle TP+SL -> SL; fill candle may also stop out."""
    st = sig.get("status", "pending"); long = sig["direction"] == "long"; filled = sig.get("filled_at")
    t0 = pd.Timestamp(sig["confirm_time"]); m = m5[m5.t >= t0]
    for b in m.itertuples():
        if st == "pending":
            if (b.l <= sig["entry"]) if long else (b.h >= sig["entry"]):
                st = "open"; filled = str(b.t)
            elif b.t - t0 > pd.Timedelta(expiry): return "expired", None, str(b.t), None
            else: continue
        hit_sl = (b.l <= sig["sl"]) if long else (b.h >= sig["sl"])
        hit_tp = (b.h >= sig["tp"]) if long else (b.l <= sig["tp"])
        if hit_sl: return "sl", filled, str(b.t), -1.0
        if hit_tp: return "tp", filled, str(b.t), float(sig["rr"])
    return st, filled, None, None

def check(sig, m5):
    st, filled, closed, r = simulate(sig, m5)
    kw = {"status": st}
    if filled and not sig.get("filled_at"): kw["filled_at"] = filled
    if closed: kw["closed_at"] = closed
    if r is not None: kw["result_r"] = r
    if st != sig["status"] or len(kw) > 1: db.update(sig["id"], **kw)
    return st

def update_all(cache=None):
    cache = cache or {}; out = {}
    sigs = db.open_signals()
    fx = [s["symbol"] for s in sigs if s["market"]=="forex" and s["symbol"] not in cache]
    if fx: cache.update(forex.provider().fetch_many(sorted(set(fx))))
    for s in sigs:
        try:
            if s["symbol"] in cache: m5 = cache[s["symbol"]][1]
            else: m5 = binance.klines(s["symbol"], C.LTF, 1000)
            out[s["id"]] = check(s, m5)
        except Exception as e: out[s["id"]] = f"err {e}"
    return out
