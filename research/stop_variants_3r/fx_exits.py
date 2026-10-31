"""Exit times for the forex 'live' rows (MF-REJ, PAT-TRIPLE), which bt_fx3y.py saved without exit_t.
Replays the same live signals as bt_fx3y.py (FXSRC=yahoo data, same functions and horizons) and records outcomes.simulate's
closed_at (+ bar length = bar close), or the last bar's close time for trades still open at the horizon (marked to market).
Writes out3y_exits/fx_live_exits.csv (symbol, strategy, t, direction, exit_t, live_r). Box only, one pair at a time, low memory."""
import sys, os, pickle
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
import pandas as pd
from app import config as C, strategy, outcomes
from app import patterns_live as P
from app.backtest_all import resample, mtm
T0 = pd.Timestamp("2023-10-01", tz="UTC")

def exits(sym, h1):
    out = []
    h4 = resample(h1[["t", "o", "h", "l", "c", "v"]], "4h"); h4 = h4[h4.ct <= h1.ct.iloc[-1]].reset_index(drop=True)
    def xt(closed, fut, bar):
        if closed: return pd.Timestamp(closed) + bar
        return fut.ct.iloc[-1] if len(fut) else None
    if sym in strategy.MF_PAIRS:
        for i in range(300, len(h1) - 1):
            if h1.t.iloc[i] < T0: continue
            x = h1.iloc[max(0, i-800):i+1]; ct = x.ct.iloc[-1]
            if strategy.mf_session(sym, ct) is None: continue
            hh = h4[h4.ct <= ct]
            try: sig = strategy.analyze_mf(sym, hh.tail(400), x, max_age_min=10**8, h4_long=hh.tail(2400))
            except Exception: continue
            if not sig: continue
            fut = h1.iloc[i+1:i+1+240]; st, _, cl, r = outcomes.simulate(sig, fut)
            out.append(dict(symbol=sym, strategy="MF-REJ", t=str(ct), direction=sig["direction"], exit_t=str(xt(cl, fut, pd.Timedelta("1h"))),
                            live_r=r if st in ("tp", "sl", "be") else mtm(sig, fut)))
    if sym in C.PAT_FX:
        dd, aa, E = P.pat_series("PAT-TRIPLE", h4, "forex"); seen = set(); R = P.PAT["PAT-TRIPLE"][5]
        for e in E:
            ct = dd.ct.iloc[e["k"]]
            if (e["k"], e["dir"]) in seen or ct < T0: continue
            seen.add((e["k"], e["dir"])); entry, sl = float(e["entry"]), float(e["sl"]); sd = 1 if e["dir"] == "long" else -1
            s = dict(direction=e["dir"], entry=entry, sl=sl, tp=entry + sd*R*abs(entry-sl), rr=R, confirm_time=str(ct), status="open", filled_at=str(ct), strategy="PAT-TRIPLE")
            fut = dd.iloc[e["k"]+1:e["k"]+181]; st, _, cl, r = outcomes.simulate(s, fut)
            out.append(dict(symbol=sym, strategy="PAT-TRIPLE", t=str(ct), direction=e["dir"], exit_t=str(xt(cl, fut, pd.Timedelta("4h"))),
                            live_r=r if st in ("tp", "sl", "be") else mtm(s, fut)))
    return out

if __name__ == "__main__":
    fx = pickle.load(open(f"{HERE}/data/fx.pkl", "rb"))[0]; rows = []; os.makedirs(f"{HERE}/out3y_exits", exist_ok=True)
    for p in list(fx):
        h1 = fx.pop(p); r = exits(p, h1); rows += r; print(p, len(r), flush=True); del h1
    pd.DataFrame(rows).to_csv(f"{HERE}/out3y_exits/fx_live_exits.csv", index=False)
