"""Aggregate out3y/*.csv -> results3y.md / results3y.json. Same stats as report.py plus out-of-sample by period:
three 12-month blocks ending at the last data day (Y1 = first ~13 months from 2023-10-01, Y2, Y3 = last 12 months),
calendar-year net R, and first 2/3 vs last 1/3. ✅ = net R > 0 AND positive in >= 2 of the 3 blocks AND positive in the
last 12 months. Crypto 'survivors' = coins whose Binance data starts at the 2022-10-01 fetch start (listed 3+ years ago)."""
import os, glob, json
import numpy as np, pandas as pd
from report import fm, mdd, ci, VN
HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = [("DON20", "crypto"), ("CHK", "crypto"), ("FVG-D1", "crypto"), ("FVG-PLAN", "crypto"), ("BRK", "crypto"),
         ("MF-REJ", "forex"), ("PAT-TRIPLE", "forex"), ("MF-REJ", "crypto"), ("PAT-TRIPLE", "crypto"),
         ("FVG", "crypto"), ("FVG+TREND", "crypto"), ("PAT-WEDGE", "crypto"), ("PAT-CUP", "crypto")]
def load():
    d = pd.concat([pd.read_csv(f) for f in glob.glob(f"{HERE}/out3y/*.csv")], ignore_index=True)
    fx = glob.glob(f"{HERE}/out3y_fixmf/*.csv")      # crypto MF-REJ re-run with the 694-day max-age bug fixed
    if fx:
        f = pd.concat([pd.read_csv(x) for x in fx], ignore_index=True)
        d = pd.concat([d[~(d.symbol.isin(f.symbol.unique()) & d.strategy.isin(["MF-REJ"]))], f[f.strategy.isin(["MF-REJ"])]], ignore_index=True)
    d["t"] = pd.to_datetime(d.t, utc=True, format="mixed"); d["market"] = np.where(d.symbol.str.endswith("USDT"), "crypto", "forex")
    d = d.dropna(subset=["net_r"]); keep = []
    for (sym, v), g in d[d.strategy == "DON20"].groupby(["symbol", "variant"]):   # DON20: one position per coin per variant
        last = None
        for i, r in g.sort_values("t").iterrows():
            ft = pd.Timestamp(r.fill_t) if isinstance(r.fill_t, str) and r.fill_t else r.t
            if ft.tzinfo is None: ft = ft.tz_localize("UTC")
            if last is not None and ft <= last: continue
            keep.append(i); xt = pd.Timestamp(r.exit_t) if isinstance(r.exit_t, str) and r.exit_t else ft
            last = xt.tz_localize("UTC") if xt.tzinfo is None else xt
    return pd.concat([d[d.strategy != "DON20"], d.loc[keep]]).sort_values("t")
def survivors():
    out = []
    for f in glob.glob(f"{HERE}/data/c15_*.pkl"):
        t0 = pd.read_pickle(f).t.iloc[0]
        if t0 <= pd.Timestamp("2022-10-02", tz="UTC"): out.append(os.path.basename(f)[4:-4])
    return set(out)
def main():
    d = load(); end = d.t.max().normalize() + pd.Timedelta("1D")
    E = [end - pd.DateOffset(years=k) for k in (2, 1)]; BL = ["Y1", "Y2", "Y3"]
    def blk(t): return np.where(t < E[0], "Y1", np.where(t < E[1], "Y2", "Y3"))
    d["blk"] = blk(d.t); d["yr"] = d.t.dt.year; split = {}
    for mk, g in d.groupby("market"): a, b = g.t.min(), g.t.max(); split[mk] = a + (b - a)*2/3
    surv = survivors(); res = {}
    per = {mk: f"{g.t.min():%Y-%m-%d} → {g.t.max():%Y-%m-%d} ({(g.t.max()-g.t.min()).days/365.25:.2f} y)" for mk, g in d.groupby("market")}
    nc = d[d.market == "crypto"].symbol.nunique(); nf = d[d.market == "forex"].symbol.nunique()
    L = ["# 3-year backtest: all strategies × stop variants at a fixed 3R take-profit (research only)", "",
         f"Signals: crypto {per['crypto']}, {nc} coins (top-50 by volume today + BTC/ETH, from listing; {len(surv)} survivors listed before Oct 2022). "
         f"Forex {per.get('forex','–')}, {nf} pairs. Net R after fees.",
         f"Blocks: Y1 = {d.t.min():%Y-%m-%d} → {E[0]:%Y-%m-%d}, Y2 = → {E[1]:%Y-%m-%d}, Y3 = last 12 months → {end:%Y-%m-%d}. "
         f"2/3 split: crypto {split['crypto']:%Y-%m-%d}, forex {split.get('forex', d.t.max()):%Y-%m-%d}.",
         "Every strategy covers the full period (CHK max-age bug fixed in the Nov 2026 re-run). 'live' = pre-2026-10-31 rules; today's live setups are the variant rows (see README). "
         "✅ = net R > 0, positive in a majority of Y1–Y3, and positive in Y3.", ""]
    for s, mk in ORDER:
        g = d[(d.strategy == s) & (d.market == mk)]
        if not len(g): continue
        key = f"{s} ({mk})"; res[key] = {}; sp = split[mk]
        L += [f"## {key}", "", "|Variant|Trades|Win%|Net R|Avg R (90% CI)|Max DD|Median stop %|Y1 R|Y2 R|Y3 (last 12m) R|First 2/3 avg|Last 1/3 avg|", "|-|-|-|-|-|-|-|-|-|-|-|-|"]
        for v in VN:
            x = g[g.variant == v]
            if not len(x): continue
            n = x.net_r.values; i, o = x[x.t < sp], x[x.t >= sp]
            st = dict(n=len(n), win=round(100*float((x.r > 0).mean()), 1), net=round(float(n.sum()), 1), avg=round(float(n.mean()), 3),
                      dd=round(mdd(n), 1), stop=round(float(x.risk_pct.median()), 2), ci=ci(n),
                      blocks={b: round(float(x[x.blk == b].net_r.sum()), 1) for b in BL}, blocks_n={b: int((x.blk == b).sum()) for b in BL},
                      years={int(y): round(float(gg.net_r.sum()), 1) for y, gg in x.groupby("yr")},
                      is_avg=round(float(i.net_r.mean()), 3) if len(i) else None, oos_avg=round(float(o.net_r.mean()), 3) if len(o) else None)
            pos = sum(st["blocks"][b] > 0 for b in BL)
            st["robust"] = bool(st["net"] > 0 and pos >= 2 and st["blocks"]["Y3"] > 0)
            if mk == "crypto":
                xs = x[x.symbol.isin(surv)]; st["surv"] = dict(n=len(xs), net=round(float(xs.net_r.sum()), 1),
                                                              blocks={b: round(float(xs[xs.blk == b].net_r.sum()), 1) for b in BL})
            res[key][v] = st; c = st["ci"]
            L.append(f"|{VN[v]}|{st['n']}|{st['win']}|{st['net']:+.1f}|{st['avg']:+.3f}{'' if not c else f' ({c[0]:+.2f}..{c[1]:+.2f})'}|{st['dd']:.1f}|{st['stop']}|"
                     + "|".join(f"{st['blocks'][b]:+.1f}" for b in BL) + f"|{fm(st['is_avg'])}|{fm(st['oos_avg'])}|" + (" ✅" if st["robust"] else ""))
        if mk == "crypto":
            L += ["", "Survivors only (coins listed before Oct 2022): " + "; ".join(
                f"{v} {res[key][v]['surv']['n']} tr {res[key][v]['surv']['net']:+.1f}R (Y3 {res[key][v]['surv']['blocks']['Y3']:+.1f})" for v in res[key])]
        L += ["", "Calendar years net R: " + "; ".join(f"{v} " + " ".join(f"{y}:{r:+.1f}" for y, r in res[key][v]["years"].items()) for v in res[key]), ""]
    L += ["✅ = net R > 0 AND positive in at least 2 of the 3 twelve-month blocks AND positive in the last 12 months (Y3)."]
    open(f"{HERE}/results3y.md", "w").write("\n".join(L) + "\n")
    json.dump(dict(period=per, blocks=[str(e) for e in E], split={k: str(v) for k, v in split.items()}, survivors=sorted(surv), results=res),
              open(f"{HERE}/results3y.json", "w"), indent=1)
    print("\n".join(L))
if __name__ == "__main__": main()
