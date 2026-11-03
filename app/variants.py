"""Live stop/target variants (user 2026-10-31), identical to research/stop_variants_3r/engine.py:
  w<k>  stop = entry − k × (original stop distance)            (long; short mirrored)
  c60   stop beyond the last *completed* 1h candle that closed at/before the fill bar opened:
        long min(candle low, entry) − 0.1×ATR14(1h), short max(candle high, entry) + 0.1×ATR14(1h);
        1h candles resampled from the 15m bars (origin=epoch); candle older than 2 days -> keep the original stop.
  cur   original stop.
All: crypto stop floored to 0.3% of entry, fixed take-profit = 3R of the final stop, no partial TP."""
import numpy as np, pandas as pd
RR = 3.0
MIN_STOP = {"crypto": 0.003}
BUF = 0.1
MODE = {"PAT-WEDGE": "w1.5", "FVG-PLAN": "w1.5", "PAT-TRIPLE-C": "w2", "FVG+TREND": "c60", "BRK": "cur"}
DESC = {"w1.5": "1.5× the pattern stop", "w2": "2× the pattern stop", "c60": "beyond the last closed 1h candle at fill (−/+0.1 ATR)", "cur": "level ∓ 0.5 ATR"}

def levels(entry, sl, direction, market, rr=RR):
    """Floor the stop (crypto 0.3%) and return (sl, tp) with tp = rr × final risk."""
    sd = 1 if direction == "long" else -1; e = float(entry); sl = float(sl); ms = MIN_STOP.get(market)
    if ms and abs(e - sl)/e < ms: sl = e - sd*ms*e
    return sl, e + sd*rr*abs(e - sl)

def widen(sig, k):
    e = float(sig["entry"]); sd = 1 if sig["direction"] == "long" else -1; risk0 = abs(e - float(sig["sl"]))
    return e - sd*k*risk0

def apply(strategy, sig):
    """Return a copy of sig with the variant's stop / 3R target (c60: provisional; final levels are set at fill by outcomes)."""
    m = MODE.get(strategy)
    if not m: return sig
    s = dict(sig); s["orig_sl"] = float(sig["sl"])
    sl = widen(s, float(m[1:])) if m.startswith("w") else float(sig["sl"])
    s["sl"], s["tp"] = levels(s["entry"], sl, s["direction"], s.get("market", "crypto")); s["rr"] = RR; s["stop_mode"] = m
    return s

def h1_candles(m15):
    """Completed-or-not 1h candles from 15m/5m bars (+ ATR14 'a'). Empty input -> empty frame (no crash)."""
    if m15 is None or not len(m15): return pd.DataFrame(columns=["o", "h", "l", "c", "t", "ct", "a"])
    x = m15[["t", "o", "h", "l", "c"]].set_index("t").resample("1h", origin="epoch").agg(dict(o="first", h="max", l="min", c="last")).dropna()
    x["t"] = x.index; x["ct"] = x.t + pd.Timedelta("1h"); x = x.reset_index(drop=True)
    if not len(x): x["a"] = []; return x
    h, l, c = x.h.values, x.l.values, x.c.values; pc = np.r_[c[0], c[:-1]]
    x["a"] = pd.Series(np.maximum(h-l, np.maximum(abs(h-pc), abs(l-pc)))).rolling(14, min_periods=1).mean().values
    return x

def c60_stop(m15, t_fill, direction, entry):
    """Stop beyond the last 1h candle with close time <= t_fill (fill bar open). None if no candle within 2 days."""
    t_fill = pd.Timestamp(t_fill)
    if t_fill.tzinfo is None: t_fill = t_fill.tz_localize("UTC")
    if m15 is None or not len(m15): return None   # no candles -> caller falls back to the signal's own stop
    x = h1_candles(m15[m15.t < t_fill])   # only bars before the fill bar -> completed candles, no look-ahead
    x = x[x.ct <= t_fill]
    if not len(x): return None
    k = x.iloc[-1]
    if k.ct < t_fill - pd.Timedelta("2D"): return None
    e = float(entry)
    return (min(float(k.l), e) - BUF*float(k.a)) if direction == "long" else (max(float(k.h), e) + BUF*float(k.a))
