"""Parity check: live DON28 entry logic (app/don20.py signal() + don28_ok() on the same 259-bar closed daily window the live bot
fetches, DAILY_BARS=260) vs the research engine (don28_3y.run(d, filt=True)) on the research daily data (d1x3/).
Exits/trailing come from the research engine in both (live trail = same rule); only the entry decision is swapped.
Also counts research DON28 entries taken while SMA200 was unknown (< 200 bars), which the research lets through unfiltered."""
import sys, os, json, glob
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
os.environ.setdefault("TELEGRAM_BOT_TOKEN", ""); os.environ.setdefault("DATABASE_URL", "")
import numpy as np, pandas as pd
import don28_3y as R
from app import don20 as L
W = L.DAILY_BARS - 1   # closed bars in the live window

def run_live(d, filt):
    """research run() with the entry decision replaced by the live functions on a W-bar window."""
    A = d.atr.values; o, h, l, c, qv = (d[x].values for x in "o h l c qv".split()); t = d.t.values; out = []; pos = None
    for i in range(R.N+2, len(d)):
        if pos:
            sd, stp = pos["sd"], pos["stop"]
            if (sd == 1 and l[i] <= stp) or (sd == -1 and h[i] >= stp): out.append((str(t[pos["i"]])[:10], pos["sd"], "closed")); pos = None; continue
            pos["best"] = max(pos["best"], c[i]) if sd == 1 else min(pos["best"], c[i]); ns = pos["best"]-sd*R.K*A[i]
            pos["stop"] = max(stp, ns) if sd == 1 else min(stp, ns); continue
        if pd.Timestamp(t[i]) < R.T0 or qv[i] < 1e6: continue   # research liquidity rule (live uses its own 24h floor for DON20 and DON28 alike)
        w = d.iloc[max(0, i-W+1):i+1]
        sg = L.signal(w)
        if not sg: continue
        side, a = sg
        if filt and not L.don28_ok(w, side)[0]: continue
        sd = 1 if side == "long" else -1; st = c[i] - sd*R.K*a
        if sd == 1 and st <= 0: continue
        pos = dict(sd=sd, stop=st, best=c[i], i=i)
    if pos: out.append((str(t[pos["i"]])[:10], pos["sd"], "open"))
    return out

if __name__ == "__main__":
    files = sorted(glob.glob(f"{R.D}/*.csv")); res = dict(coins=0, research=0, live=0, mismatch=[], unknown_sma_entries=0, short_history_coins=[])
    for f in files:
        s = os.path.basename(f)[:-4]
        d = R.load(s)
        if len(d) < R.N + 3: continue
        res["coins"] += 1
        rr = R.run(d, True); a = {(str(x["t"])[:10], x["dir"], x["status"]) for x in rr}
        b = set(run_live(d, True))
        res["research"] += len(a); res["live"] += len(b)
        for x in sorted(a ^ b): res["mismatch"].append([s, *x, "research_only" if x in a else "live_only"])
        cm = dict(zip(d.t.astype(str).str[:10], d.cma))
        n0 = sum(1 for x in rr if cm.get(str(x["t"])[:10]) == 0); res["unknown_sma_entries"] += n0
        if n0: res["short_history_coins"].append([s, n0])
    res["mismatches"] = len(res["mismatch"])
    json.dump(res, open(f"{HERE}/don28_parity.json", "w"), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k != "mismatch"}, indent=1)); print("first mismatches:", res["mismatch"][:20])
