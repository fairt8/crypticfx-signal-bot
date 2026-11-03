"""Part B report: baseline vs candle filters per strategy -> results_b.md / results_b.json."""
import os, json
import numpy as np, pandas as pd
from filter_b import STRATS, TFS, HTF, one_pos
HERE = os.path.dirname(os.path.abspath(__file__))
END = pd.Timestamp("2026-10-31", tz="UTC")     # = report3y 'end' of the prev_oct30 run (last signal day + 1)
E = [END - pd.DateOffset(years=k) for k in (2, 1)]
FILTERS = ["base"] + [f"{a}_{l}_{s}_{k}" for l in ("sig", "htf") for s in ("all", "top") for a in ("req", "blk") for k in (0, 2)] \
          + ["req_sig_all_2+blk_sig_all_2", "blk_sig_all_2+blk_htf_all_2"]
def stats(x):
    x = x.assign(blk=np.where(x.t < E[0], "Y1", np.where(x.t < E[1], "Y2", "Y3")))
    b = {k: round(float(x[x.blk == k].net_r.sum()), 1) for k in ("Y1", "Y2", "Y3")}
    return dict(n=len(x), win=round(100*float((x.r > 0).mean()), 1) if len(x) else 0, net=round(float(x.net_r.sum()), 1),
                avg=round(float(x.net_r.mean()), 3) if len(x) else 0, blocks=b, y3n=int((x.blk == "Y3").sum()),
                years={int(y): round(float(g.net_r.sum()), 1) for y, g in x.groupby(x.t.dt.year)})
def main():
    d = pd.read_pickle(f"{HERE}/out/filter_b_rows.pkl"); res = {}
    L = ["# Part B — candlestick confirmation / block filters on the existing strategies (research only)", "",
         f"Baseline = stop_variants_3r/prev_oct30 3-year trades (crypto 2023-10-01 → 2026-10-29, forex 2024-01 → 2026-10-30; CHK from 2024-12). "
         f"Blocks Y1 → {E[0]:%Y-%m-%d}, Y2 → {E[1]:%Y-%m-%d}, Y3 = last 12 months. Net R after fees. DON20 one-position rule applied after filtering.",
         "Filter names: req = keep only if a same-direction pattern; blk = drop if an opposite-direction pattern; "
         "sig = on the strategy's own timeframe (entry candle + k earlier), htf = on the next timeframe up (last 1+k completed candles); "
         "all = every detector, top = families picked in part A; _0 / _2 = k.", ""]
    for s, mk, v in STRATS:
        g = d[(d.strategy == s) & (d.market == mk) & (d.variant == v)]; key = f"{s} ({mk}, {v})"; res[key] = {}
        L += [f"## {key} — signal tf {TFS[s]}, htf {HTF[TFS[s]] or 'n/a'}", "",
              "|Filter|Trades|Win%|Net R|Avg R|Y1|Y2|Y3|Y3 n|Calendar years|Δ net|Δ Y3|", "|-|-|-|-|-|-|-|-|-|-|-|-|"]
        for f in FILTERS:
            if "htf" in f and HTF[TFS[s]] is None: continue
            m = np.ones(len(g), bool)
            if f != "base":
                for p in f.split("+"): m &= g[p].values
            x = g[m]
            if s == "DON20":
                x = pd.concat([x.loc[one_pos(gg)] for _, gg in x.groupby("symbol")]) if len(x) else x
            st = stats(x); res[key][f] = st; b0 = res[key]["base"]
            L.append(f"|{f}|{st['n']}|{st['win']}|{st['net']:+.1f}|{st['avg']:+.3f}|" + "|".join(f"{st['blocks'][k]:+.1f}" for k in ("Y1", "Y2", "Y3"))
                     + f"|{st['y3n']}|" + " ".join(f"{y}:{r:+.0f}" for y, r in st["years"].items())
                     + f"|{st['net']-b0['net']:+.1f}|{st['blocks']['Y3']-b0['blocks']['Y3']:+.1f}|")
        L.append("")
    open(f"{HERE}/results_b.md", "w").write("\n".join(L) + "\n"); json.dump(res, open(f"{HERE}/results_b.json", "w"), indent=1)
if __name__ == "__main__": main()
