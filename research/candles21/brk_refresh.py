"""BRK + opposite-pattern block (blk_sig_all_2 + blk_htf_all_2) re-checked on the refreshed Nov 2026 3-year run (stop_variants_3r/out3y).
Same detectors / windows as filter_b.py. Writes brk_refresh.json / prints a small table. Research only."""
import os, glob, json
import numpy as np, pandas as pd
from filter_b import pat_table, hit, rs, SV, HERE
VARS = ["cur", "live", "w1.5", "w2"]
d = pd.concat([pd.read_csv(f, usecols=lambda c: True) for f in glob.glob(f"{SV}/out3y/*USDT.csv")], ignore_index=True)
d = d[(d.strategy == "BRK") & d.variant.isin(VARS)].dropna(subset=["net_r"]).copy()
d["t"] = pd.to_datetime(d.t, utc=True, format="mixed"); d = d.reset_index(drop=True); keep = np.ones(len(d), bool)
for sym, g in d.groupby("symbol"):
    base = pd.read_pickle(f"{SV}/data/c15_{sym}.pkl")[["t", "o", "h", "l", "c", "v", "ct"]]
    tabs = {tf: pat_table(rs(base, tf)[lambda x: x.ct <= base.ct.iloc[-1]])["all"] for tf in ("4h", "1D")}
    tt = g.t.values.astype("datetime64[ns]").astype(np.int64); opp = np.where(g.direction.values == "long", "short", "long")
    ok = np.ones(len(g), bool)
    for tf, lo in (("4h", tt - 2*pd.Timedelta("4h").value), ("1D", tt - 3*pd.Timedelta("1D").value + 1)):
        op = np.where(opp == "short", hit(tabs[tf]["short"], tt, lo), hit(tabs[tf]["long"], tt, lo)); ok &= ~op
    keep[g.index.values] = ok; del base, tabs
end = d.t.max().normalize() + pd.Timedelta("1D"); E = [end - pd.DateOffset(years=k) for k in (2, 1)]
d["blk"] = np.where(d.t < E[0], "Y1", np.where(d.t < E[1], "Y2", "Y3"))
def st(x): return dict(n=len(x), win=round(100*float((x.r > 0).mean()), 1), net=round(float(x.net_r.sum()), 1),
                       blocks={b: round(float(x[x.blk == b].net_r.sum()), 1) for b in ("Y1", "Y2", "Y3")},
                       years={int(y): round(float(g.net_r.sum()), 1) for y, g in x.groupby(x.t.dt.year)})
res = {v: dict(base=st(d[d.variant == v]), filt=st(d[(d.variant == v) & keep])) for v in VARS}
json.dump(dict(end=str(end), results=res), open(f"{HERE}/brk_refresh.json", "w"), indent=1)
for v, r in res.items(): print(v, "base", r["base"], "\n   filt", r["filt"])
