"""Market Fluidity helpers shared by the live MF-REJ signal (copied verbatim from app/backtest_mf.py)."""
import numpy as np, pandas as pd
AGG = {"o":"first","h":"max","l":"min","c":"last","v":"sum"}
def rs(m, f):
    x = m.set_index("t").resample(f, **({"origin": "epoch"} if f[-1] in "hn" else {})).agg(AGG).dropna(); x["t"] = x.index
    x["ct"] = x.t + pd.Timedelta(f); x = x.reset_index(drop=True); return x[x.ct <= m.ct.iloc[-1]].reset_index(drop=True)
def atr(x, n=14):
    return pd.concat([x.h-x.l, (x.h-x.c.shift()).abs(), (x.l-x.c.shift()).abs()], axis=1).max(axis=1).rolling(n).mean().values
def struct_bias(x, k=2):
    """HH+HL=up(1), LH+LL=down(-1) from confirmed pivots; value known at close of bar (pivot confirmed k bars later)."""
    H, L = x.h.values, x.l.values; hs, ls = [], []; b = np.zeros(len(x))
    for i in range(len(x)):
        j = i-k
        if j >= k:
            if H[j] == H[j-k:j+k+1].max(): hs.append(H[j])
            if L[j] == L[j-k:j+k+1].min(): ls.append(L[j])
        if len(hs) >= 2 and len(ls) >= 2:
            b[i] = 1 if hs[-1] > hs[-2] and ls[-1] > ls[-2] else -1 if hs[-1] < hs[-2] and ls[-1] < ls[-2] else 0
    return b
def at(ct, vals, t):
    k = np.searchsorted(ct, t, side="right")-1; return vals[k] if k >= 0 else 0
def pip(sym): return 0.01 if sym.endswith("JPY") else 0.0001
def zones(x):
    """Course structure: structural high = bullish candle then bearish close; zone wick->body. Confirmed at close of 2nd candle."""
    O, H, L, Cl = x.o.values, x.h.values, x.l.values, x.c.values; R = [None]*len(x); S = [None]*len(x); r = s = None
    for i in range(6, len(x)):
        if Cl[i-1] > O[i-1] and Cl[i] < O[i]:
            j = i-1 if H[i-1] >= H[i] else i
            if H[j] >= H[i-6:i+1].max(): r = (max(O[j], Cl[j]), H[j])
        if Cl[i-1] < O[i-1] and Cl[i] > O[i]:
            j = i-1 if L[i-1] <= L[i] else i
            if L[j] <= L[i-6:i+1].min(): s = (L[j], min(O[j], Cl[j]))
        R[i], S[i] = r, s
    return R, S

# ---- Strong body-based S/R (bt_mfs/run.py, best variant: body bias, T2|HTF, pad 0.5, next-zone TP >= 0.5R) ----
import time as _time
def body(x):
    y = x.copy(); y["h"] = np.maximum(x.o, x.c); y["l"] = np.minimum(x.o, x.c); return y
def pivots(x, k):
    """Body swing extremes -> (confirm_time, level) arrays, highs+lows mixed (S/R flip allowed)."""
    bh = np.maximum(x.o.values, x.c.values); bl = np.minimum(x.o.values, x.c.values); ct = x.ct.values; T = []; P = []
    for j in range(k, len(x)-k):
        if bh[j] == bh[j-k:j+k+1].max(): T.append(ct[j+k]); P.append(bh[j])
        if bl[j] == bl[j-k:j+k+1].min(): T.append(ct[j+k]); P.append(bl[j])
    if not T: return np.array([], dtype="datetime64[ns]"), np.array([])
    o = np.argsort(T, kind="stable"); return np.array(T)[o], np.array(P)[o]
def cluster(levels, anchor, tol):
    c = levels[np.abs(levels-anchor) <= tol]
    return (c.min(), c.max(), len(c)) if len(c) else (anchor, anchor, 0)

_HTF = {}   # symbol -> (fetched_at, h4)   longer 1H history (1y) for 4H/Daily levels; refreshed every 6h
def _h4_from(a):
    h4 = a.resample("4h", origin="epoch").agg(AGG).dropna(); h4["t"] = h4.index; h4["ct"] = h4.t + pd.Timedelta("4h")
    h4 = h4.reset_index(drop=True); return h4[h4.ct <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True)
def prefetch_htf(symbols, deadline=None):
    """One batched 1y 1H download for all symbols not cached (<6h). Only called for pairs that passed mf_precheck,
    so a typical scan downloads 0-3 pairs. Skipped when past `deadline` (epoch s): htf_h4 then falls back to 60d."""
    now = _time.time(); need = [s for s in dict.fromkeys(symbols) if not (_HTF.get(s) and now - _HTF[s][0] < 6*3600)]
    if not need or (deadline and now > deadline): return
    try:
        from . import forex
        pv = forex.provider()
        if getattr(pv, "name", "") != "yfinance": return
        tk = {pv.ticker(s): s for s in need}
        raw = pv._dl(list(tk), "1h", "1y")   # time-capped download (YF_BUDGET_S)
        for t, s in tk.items():
            try:
                a = pv._norm(raw[t] if t in raw.columns.get_level_values(0) else raw)
                if len(a): _HTF[s] = (now, _h4_from(a))
            except Exception: _HTF[s] = (now - 5*3600, _HTF[s][1]) if s in _HTF else None
        for s in [k for k, v in _HTF.items() if v is None]: _HTF.pop(s)
    except Exception: pass
def htf_h4(symbol, fallback):
    now = _time.time(); c = _HTF.get(symbol)
    if c and len(c[1]) >= len(fallback): return c[1]
    if c is None: prefetch_htf([symbol]); c = _HTF.get(symbol)
    return c[1] if c and len(c[1]) >= len(fallback) else fallback
