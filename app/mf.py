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
