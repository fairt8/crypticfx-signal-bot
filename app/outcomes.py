"""Outcome tracking on 5m candles: pending -> open (entry touched) -> tp/sl; pending >24h -> expired.
Same-candle TP+SL counts as SL (conservative).
PTP_STRATS: 50% closed at TP1 (1.5R), stop moved to entry; runner to TP (+0.75+0.5*rr) or back to entry ("be", +0.75R)."""
import pandas as pd
from . import config as C, db, binance, forex
def simulate(sig, m5, expiry=None, info=None):
    """Pure: returns (status, filled_at, closed_at, result_r). Same-candle TP+SL -> SL; fill candle may also stop out.
    FVG+TREND (variants.MODE 'c60'): SL/TP are (re)set at the fill from the last closed 1h candle; pass info={} to get them back."""
    expiry = expiry or C.PENDING_EXPIRY
    from . import variants as V
    st = sig.get("status", "pending"); long = sig["direction"] == "long"; filled = sig.get("filled_at")
    t0 = pd.Timestamp(sig["confirm_time"]); m = m5[m5.t >= t0]
    ptp = sig.get("strategy") in C.PTP_STRATS and float(sig.get("rr") or 0) > 1.5   # backtest bt_ptp/: partial TP improved net R + win rate in both halves
    sl = sig["sl"]; half = False; tp1 = sig["entry"] + (1.5 if long else -1.5) * abs(sig["entry"] - sig["sl"])
    for b in m.itertuples():
        if st == "pending":
            if (b.l <= sig["entry"]) if long else (b.h >= sig["entry"]):
                st = "open"; filled = str(b.t)
                if V.MODE.get(sig.get("strategy")) == "c60":
                    c = V.c60_stop(m5, b.t, sig["direction"], sig["entry"])
                    if c is None: c = float(sig.get("orig_sl") or sig["sl"])   # no 1h candle within 2 days: original stop
                    sl, tp = V.levels(sig["entry"], c, sig["direction"], sig.get("market", "crypto"))
                    sig = dict(sig, sl=sl, tp=tp, rr=V.RR)
                    if info is not None: info.update(sl=sl, tp=tp)
            elif b.t - t0 > pd.Timedelta(expiry): return "expired", None, str(b.t), None
            else: continue
        hit_sl = (b.l <= sl) if long else (b.h >= sl)
        hit_tp = (b.h >= sig["tp"]) if long else (b.l <= sig["tp"])
        if hit_sl: return ("be", filled, str(b.t), 0.75) if half else ("sl", filled, str(b.t), -1.0)
        if hit_tp: return "tp", filled, str(b.t), (0.75 + 0.5 * float(sig["rr"])) if ptp else float(sig["rr"])
        if ptp and not half and ((b.h >= tp1) if long else (b.l <= tp1)): half = True; sl = sig["entry"]   # 50% off at TP1, SL to entry
    return st, filled, None, None

def check(sig, m5, post=False):
    info = {}; st, filled, closed, r = simulate(sig, m5, info=info)
    kw = {"status": st}
    if info and sig["status"] == "pending":   # FVG+TREND: final stop/target set at the fill
        kw.update(sl=info["sl"], tp=info["tp"])
        if post and sig.get("posted"): _fill_note(sig, info, filled)
    if filled and not sig.get("filled_at"): kw["filled_at"] = filled
    if closed: kw["closed_at"] = closed
    if r is not None: kw["result_r"] = r
    if st != sig["status"] or len(kw) > 1: db.update(sig["id"], **kw)
    return st

def _fill_note(sig, info, filled):
    try:
        from . import telegram
        telegram.send(telegram.fmt_fill(sig, info, filled), html=True)
    except Exception as e: print(f"[outcomes] fill note: {e}", flush=True)

def update_all(cache=None, post=False):
    cache = cache or {}; out = {}
    sigs = db.open_signals()
    fx = [s["symbol"] for s in sigs if s["market"]=="forex" and s["symbol"] not in cache]
    if fx: cache.update(forex.provider().fetch_many(sorted(set(fx))))
    for s in sigs:
        try:
            if s["symbol"] in cache: m5 = cache[s["symbol"]][1]
            else: m5 = binance.klines(s["symbol"], C.LTF, 1000)
            out[s["id"]] = check(s, m5, post)
        except Exception as e: out[s["id"]] = f"err {e}"
    return out
