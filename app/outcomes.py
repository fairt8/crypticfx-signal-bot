"""Outcome tracking on 5m candles: pending -> open (entry touched) -> tp/sl; pending >24h -> expired.
Same-candle TP+SL counts as SL (conservative).
PTP_STRATS: 50% closed at TP1 (1.5R), stop moved to entry; runner to TP (+0.75+0.5*rr) or back to entry ("be", +0.75R)."""
import pandas as pd
from . import config as C, db, binance, forex
def simulate(sig, m5, expiry=None):
    expiry = expiry or C.PENDING_EXPIRY
    """Pure: returns (status, filled_at, closed_at, result_r). Same-candle TP+SL -> SL; fill candle may also stop out."""
    st = sig.get("status", "pending"); long = sig["direction"] == "long"; filled = sig.get("filled_at")
    t0 = pd.Timestamp(sig["confirm_time"]); m = m5[m5.t >= t0]
    ptp = sig.get("strategy") in C.PTP_STRATS and float(sig.get("rr") or 0) > 1.5   # backtest bt_ptp/: partial TP improved net R + win rate in both halves
    sl = sig["sl"]; half = False; tp1 = sig["entry"] + (1.5 if long else -1.5) * abs(sig["entry"] - sig["sl"])
    for b in m.itertuples():
        if st == "pending":
            if (b.l <= sig["entry"]) if long else (b.h >= sig["entry"]):
                st = "open"; filled = str(b.t)
            elif b.t - t0 > pd.Timedelta(expiry): return "expired", None, str(b.t), None
            else: continue
        hit_sl = (b.l <= sl) if long else (b.h >= sl)
        hit_tp = (b.h >= sig["tp"]) if long else (b.l <= sig["tp"])
        if hit_sl: return ("be", filled, str(b.t), 0.75) if half else ("sl", filled, str(b.t), -1.0)
        if hit_tp: return "tp", filled, str(b.t), (0.75 + 0.5 * float(sig["rr"])) if ptp else float(sig["rr"])
        if ptp and not half and ((b.h >= tp1) if long else (b.l <= tp1)): half = True; sl = sig["entry"]   # 50% off at TP1, SL to entry
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
