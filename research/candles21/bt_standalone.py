"""A) Each candlestick pattern alone as a signal. Crypto: 50 coins (stop_variants_3r/data, Binance 15m from Oct 2022; signals
from 2023-10-01), patterns on 1h / 4h / 1D candles, simulated on 15m bars. Forex: 19 pairs, Yahoo 1H from 2024-01, patterns on
1h / 4h / 1D, simulated on 1H bars. Entry at the close of the completing candle (market). Stop = beyond the pattern's extreme
(lowest low / highest high of the pattern + confirmation candles) +/- 0.1 ATR14; variant 1.5x that distance. TP 3R or 2R.
Trend: 'pdf' = the PDF prior-trend rule only (built into every detector); 'sma200' = also long only above / short only below
the 200-period SMA of the pattern timeframe. Fees as stop_variants_3r (crypto 0.10% round trip, forex fx_cost), net R.
Crypto stops < 0.3% skipped (as BRK/PAT), $1M 24h-volume gate. One open trade per symbol x pattern x config. Unresolved at
the horizon (1h: 10 days, 4h: 30 days, 1D: 60 days) -> marked to market. Writes out/<sym>.pkl."""
import sys, os, json, pickle, time
HERE = os.path.dirname(os.path.abspath(__file__)); SV = os.path.join(HERE, "../stop_variants_3r")
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../.."))); sys.path.insert(0, SV); sys.path.insert(0, HERE)
import numpy as np, pandas as pd
from engine import sim
from patterns import F, detect, signals
OUT = os.path.join(HERE, "out"); T0 = pd.Timestamp("2023-10-01", tz="UTC")
HZ = {"1h": pd.Timedelta(days=10), "4h": pd.Timedelta(days=30), "1D": pd.Timedelta(days=60)}
CFG = [(tr, sx, rr) for tr in ("pdf", "sma200") for sx in (1.0, 1.5) for rr in (3.0, 2.0)]

def rs(m, f):
    x = m.set_index("t").resample(f).agg(dict(o="first", h="max", l="min", c="last", v="sum")).dropna()
    x["t"] = x.index; x["ct"] = x.t + pd.Timedelta(f); return x.reset_index(drop=True)

def fx_cost(sym): return 0.0005 if sym.startswith("XA") else (0.0002 if "USD" in sym and "CNH" not in sym else 0.0003)

def run(sym, market, base):
    """base: simulation bars (crypto 15m, forex 1h) with t/o/h/l/c/v/ct."""
    T = base.t.values.astype("datetime64[ns]").astype(np.int64); H, L, Cc = base.h.values, base.l.values, base.c.values; now_ = base.ct.iloc[-1]
    if market == "crypto":
        QV = pd.Series(base.v.values*Cc).rolling(96, min_periods=1).sum().values; cost = 0.001; minstop = 0.003
        t0 = max(T0, base.t.iloc[0] + pd.Timedelta(days=12))
    else:
        QV = None; cost = fx_cost(sym); minstop = 0.0; t0 = base.t.iloc[0] + pd.Timedelta(days=5)
    rows = []
    for tf in ("1h", "4h", "1D"):
        x = base if (market == "forex" and tf == "1h") else rs(base, tf)
        x = x[x.ct <= now_].reset_index(drop=True); s = F(x); R = detect(s); sg = signals(s, R)
        ct = x.ct.values.astype("datetime64[ns]").astype(np.int64); hz = HZ[tf].value
        by = {}
        for nm, d, i, f in sg: by.setdefault(nm, []).append((i, f, d))
        for nm, lst in by.items():
            last = {c: -1 for c in CFG}
            for i, f, d in sorted(lst):
                if x.t.iloc[i] < t0: continue
                sd = 1 if d == "long" else -1; e = float(s.c[i])
                ext = float(s.l[f:i+1].min()) if sd == 1 else float(s.h[f:i+1].max())
                sl0 = ext - sd*0.1*s.atr[i]; risk0 = sd*(e - sl0)
                if risk0 <= 0 or risk0/e < minstop: continue
                j0 = int(np.searchsorted(T, ct[i], side="left"))
                if j0 >= len(T) - 1: continue
                if QV is not None and QV[max(j0-1, 0)] < 1e6: continue
                end = int(np.searchsorted(T, ct[i] + hz, side="left"))
                above = s.c[i] > s.sma200[i] if not np.isnan(s.sma200[i]) else None
                for cfg in CFG:
                    tr, sx, rr = cfg
                    if tr == "sma200" and (above is None or above != (sd == 1)): continue
                    if j0 <= last[cfg]: continue
                    sl = e - sd*sx*risk0; st, r, xi = sim(T, H, L, Cc, j0, end, e, sl, sd, rr=rr)
                    if r is None: continue
                    last[cfg] = xi; rf = sx*risk0/e
                    rows.append((sym, market, tf, nm, d, tr, sx, rr, pd.Timestamp(ct[i], tz="UTC"), st, float(r), float(r - cost/rf), 100*rf))
    return pd.DataFrame(rows, columns="sym market tf pat dir trend sx rr t status r net risk_pct".split())

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    syms = json.load(open(f"{SV}/data/syms50.json")); only = sys.argv[1:]
    for sym in syms:
        if only and sym not in only: continue
        f = f"{OUT}/{sym}.pkl"
        if os.path.exists(f) and not only: continue
        t = time.time(); m = pd.read_pickle(f"{SV}/data/c15_{sym}.pkl"); d = run(sym, "crypto", m); d.to_pickle(f)
        print(sym, len(d), f"{time.time()-t:.0f}s", flush=True); del m, d
    if not only or "fx" in only:
        fx = pickle.load(open(f"{SV}/data/fx.pkl", "rb"))[0]
        for p in sorted(fx):
            t = time.time(); b = fx[p][["t", "o", "h", "l", "c"]].copy(); b["v"] = 0.0; b["ct"] = b.t + pd.Timedelta("1h")
            b = b.dropna().reset_index(drop=True); d = run(p, "forex", b); d.to_pickle(f"{OUT}/fx_{p}.pkl")
            print(p, len(d), f"{time.time()-t:.0f}s", flush=True)
