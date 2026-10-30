"""Shared variant engine: given a signal (entry, original stop, direction, fill rule) and price arrays of the simulation
timeframe, build the stop for each variant and simulate a fixed 3R take-profit. Same-bar SL+TP -> SL (as outcomes.simulate).
Unresolved at the follow horizon -> marked to market at the last close (gross R)."""
import numpy as np, pandas as pd
RR = 3.0
VARIANTS = ("cur", "w1.5", "w2", "c30", "c60")
BUF = 0.1          # candle stop buffer, x ATR14 of that candle timeframe
EXPIRY = np.timedelta64(48, "h")

def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h-l, np.maximum(abs(h-pc), abs(l-pc)))
    return pd.Series(tr).rolling(n, min_periods=1).mean().values

class Candles:
    """Completed candles of one timeframe built from the sim bars (or given directly)."""
    def __init__(s, df):
        s.ct = df.ct.values; s.h = df.h.values; s.l = df.l.values; s.a = atr(df.h.values, df.l.values, df.c.values)
    def stop(s, t_fill, sd, entry):
        """Stop beyond the last candle that CLOSED at/before the fill bar opened (no look-ahead).
        Long: min(candle low, entry) - 0.1 ATR; short mirror. Returns None if no candle."""
        k = int(np.searchsorted(s.ct, t_fill, side="right")) - 1
        if k < 0 or s.ct[k] < t_fill - np.timedelta64(2, "D"): return None
        return (min(s.l[k], entry) - BUF*s.a[k]) if sd == 1 else (max(s.h[k], entry) + BUF*s.a[k])

def resample(df, f):
    x = df.set_index("t").resample(f, origin="epoch").agg(dict(o="first", h="max", l="min", c="last")).dropna()
    x["t"] = x.index; x["ct"] = x.t + pd.Timedelta(f); return x.reset_index(drop=True)

def find_fill(T, H, L, j0, entry, sd, limit, end):
    """First bar index >= j0 where the order is filled (market: j0). None if a limit order is not touched within 48h."""
    if j0 >= len(T): return None
    if not limit: return j0
    for b in range(j0, min(end, len(T))):
        if T[b] - T[j0] > EXPIRY: return None
        if (L[b] <= entry) if sd == 1 else (H[b] >= entry): return b
    return None

def sim(T, H, L, Cc, b0, end, entry, sl, sd, rr=RR):
    """From fill bar b0 (inclusive) to end (exclusive). Returns (status, gross_r, exit_index)."""
    risk = abs(entry - sl); tp = entry + sd*rr*risk; end = min(end, len(T))
    if b0 >= end: return "nodata", None, b0
    h, l = H[b0:end], L[b0:end]
    hs = (l <= sl) if sd == 1 else (h >= sl); ht = (h >= tp) if sd == 1 else (l <= tp)
    i_s = int(np.argmax(hs)) if hs.any() else 10**9; i_t = int(np.argmax(ht)) if ht.any() else 10**9
    if i_s == 10**9 and i_t == 10**9: return "open", sd*(Cc[end-1]-entry)/risk, end-1
    if i_s <= i_t: return "sl", -1.0, b0+i_s
    return "tp", rr, b0+i_t

def run_variants(sig, T, H, L, Cc, j0, end, candles, min_stop, cost):
    """sig: dict(direction, entry, sl, limit). candles: {'c30': Candles|None, 'c60': Candles|None}.
    Returns list of dict(variant, status, r, net_r, risk_pct, floored, exit_i, fill_t)."""
    sd = 1 if sig["direction"] == "long" else -1; e = float(sig["entry"]); risk0 = abs(e - float(sig["sl"]))
    b0 = find_fill(T, H, L, j0, e, sd, sig.get("limit", False), end)
    if b0 is None: return []
    out = []
    for v in VARIANTS:
        floored = False
        if v == "cur": sl = float(sig["sl"])
        elif v.startswith("w"): sl = e - sd*float(v[1:])*risk0
        else:
            c = candles.get(v)
            if c is None: continue
            sl = c.stop(T[b0], sd, e)
            if sl is None: continue
        if abs(e - sl)/e < min_stop: sl = e - sd*min_stop*e; floored = True
        st, r, xi = sim(T, H, L, Cc, b0, end, e, sl, sd)
        if r is None: continue
        rf = abs(e - sl)/e
        out.append(dict(variant=v, status=st, r=r, net_r=r - cost/rf, risk_pct=100*rf, floored=floored, exit_t=str(pd.Timestamp(T[xi])), fill_t=str(pd.Timestamp(T[b0]))))
    return out
