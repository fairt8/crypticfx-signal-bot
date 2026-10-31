"""3-year forex replay (bt_fx.py on longer data): MF-REJ (1H, MF_PAIRS incl. GBPCNH + synthetic XAUAUD) and PAT-TRIPLE
(4H, PAT_FX) with the live functions, on Dukascopy 1H history from Sep 2022 + Yahoo for the current month (data/fx3y.pkl from
fetch_fx.py). Signals from T0=2023-10-01 (one year of warm-up for the daily/4H zones). Variants simulated on 1H bars.
The 30m candle stop needs 30m candles, which Yahoo only serves for the last 60 days -> c30 exists only for those signals.
Writes out/fx_<PAIR>.csv."""
import sys, os, pickle, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
import numpy as np, pandas as pd
from app import config as C, strategy, outcomes, forex
from app import patterns_live as P
from app.backtest_all import fx_data, fx_cost, resample, mtm
from engine import Candles, run_variants
OUT = os.path.join(HERE, os.environ.get("FXOUT", "out3y"))
T0 = pd.Timestamp(os.environ.get("T0", "2023-10-01"), tz="UTC"); DATA = os.path.join(HERE, "data")

def fx30(pairs):
    import yfinance as yf
    pv = forex.YFinanceProvider(); real = list(dict.fromkeys(q for p in pairs for q in forex.SYNTH.get(p, (p,))))
    tk = {pv.ticker(p): p for p in real}
    raw = yf.download(list(tk), interval="30m", period="60d", group_by="ticker", progress=False, auto_adjust=False, threads=True)
    one = {}
    for t, p in tk.items():
        try: one[p] = pv._norm(raw[t])
        except Exception: pass
    out = {}
    for p in pairs:
        try:
            a = forex.synth(one[forex.SYNTH[p][0]], one[forex.SYNTH[p][1]]) if p in forex.SYNTH else one[p]
            a = a.copy(); a["t"] = a.index; a["ct"] = a.t + pd.Timedelta("30min"); out[p] = a.reset_index(drop=True)
        except Exception as e: print("30m skip", p, e)
    return out

def run(sym, h1, m30):
    cost = fx_cost(sym); rows = []; sigs = []
    h4 = resample(h1[["t", "o", "h", "l", "c", "v"]], "4h"); h4 = h4[h4.ct <= h1.ct.iloc[-1]].reset_index(drop=True)
    T = h1.t.values; H, L, Cc = h1.h.values, h1.l.values, h1.c.values; ct1 = h1.ct.values
    cnd = {"c60": Candles(h1), "c30": Candles(m30) if m30 is not None and len(m30) else None}
    if sym in strategy.MF_PAIRS:
        for i in range(300, len(h1) - 1):
            if h1.t.iloc[i] < T0: continue
            x = h1.iloc[max(0, i-800):i+1]; ct = x.ct.iloc[-1]
            if strategy.mf_session(sym, ct) is None: continue
            hh = h4[h4.ct <= ct]
            try: sig = strategy.analyze_mf(sym, hh.tail(400), x, max_age_min=10**8, h4_long=hh.tail(2400))
            except Exception: continue
            if not sig: continue
            fut = h1.iloc[i+1:i+1+240]; st, _, _, r = outcomes.simulate(sig, fut)
            sigs.append(dict(strategy="MF-REJ", t=ct, direction=sig["direction"], entry=sig["entry"], sl=sig["sl"], limit=False, j0=i+1, hz=240,
                             live_status=st, live_r=r if st in ("tp", "sl", "be") else mtm(sig, fut)))
    if sym in C.PAT_FX:
        dd, aa, E = P.pat_series("PAT-TRIPLE", h4, "forex"); seen = set(); R = P.PAT["PAT-TRIPLE"][5]
        for e in E:
            ct = dd.ct.iloc[e["k"]]
            if (e["k"], e["dir"]) in seen or ct < T0: continue
            seen.add((e["k"], e["dir"])); entry, sl = float(e["entry"]), float(e["sl"]); sd = 1 if e["dir"] == "long" else -1
            s = dict(direction=e["dir"], entry=entry, sl=sl, tp=entry + sd*R*abs(entry-sl), rr=R, confirm_time=str(ct), status="open", filled_at=str(ct), strategy="PAT-TRIPLE")
            fut = dd.iloc[e["k"]+1:e["k"]+181]; st, _, _, r = outcomes.simulate(s, fut)
            s0 = int(np.searchsorted(T, ct.to_datetime64() if hasattr(ct, "to_datetime64") else np.datetime64(ct), side="left"))
            sigs.append(dict(strategy="PAT-TRIPLE", t=ct, direction=e["dir"], entry=entry, sl=sl, limit=False, j0=s0, hz=720,
                             live_status=st, live_r=r if st in ("tp", "sl", "be") else mtm(s, fut)))
    for k, s in enumerate(sigs):
        rf = abs(s["entry"] - s["sl"])/s["entry"]
        base = dict(sid=f"{sym}-{k}", strategy=s["strategy"], symbol=sym, t=str(s["t"]), direction=s["direction"])
        rows.append(dict(base, variant="live", status=s["live_status"], r=s["live_r"], net_r=s["live_r"] - cost/rf if rf > 0 else None,
                         risk_pct=100*rf, floored=False, fill_t=str(s["t"]), exit_t=""))
        if rf <= 0: continue
        for v in run_variants(s, T, H, L, Cc, s["j0"], s["j0"] + s["hz"], cnd, 0.0, cost): rows.append(dict(base, **v))
    return rows

def one(a):
    sym, h1, m30 = a; t = time.time()
    try: rows = run(sym, h1, m30)
    except Exception as e: return sym, f"ERR {type(e).__name__}: {e}"
    pd.DataFrame(rows).to_csv(f"{OUT}/fx_{sym}.csv", index=False); return sym, f"{len(rows)} rows {time.time()-t:.0f}s"

if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    os.makedirs(OUT, exist_ok=True); os.makedirs(DATA, exist_ok=True)
    _, f30 = pickle.load(open(f"{DATA}/fx.pkl", "rb"))     # Yahoo 30m, last 60 days (c30 only exists there)
    if os.environ.get("FXSRC") == "yahoo": fx = pickle.load(open(f"{DATA}/fx.pkl", "rb"))[0]   # fallback: Yahoo 1H only (from 2024-01)
    else: fx = pickle.load(open(f"{DATA}/fx3y.pkl", "rb"))
    for p in fx: print(p, len(fx[p]), fx[p].t.iloc[0], "30m:", len(f30.get(p, [])), flush=True)
    with ProcessPoolExecutor(int(os.environ.get("W", "3"))) as ex:
        for s, msg in ex.map(one, [(p, fx[p], f30.get(p)) for p in fx]): print(s, msg, flush=True)
