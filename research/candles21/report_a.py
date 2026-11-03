"""Aggregate out/*.pkl (part A) -> results_a.md + results_a.json + top_families.json, and build CANDLE-21.
Blocks as report3y: Y3 = last 12 months before the last data day, Y2 the 12 months before, Y1 the rest.
Selection uses Y1+Y2 ONLY (in-sample); Y3 is the untouched hold-out."""
import os, glob, json
import numpy as np, pandas as pd
from patterns import base_name
HERE = os.path.dirname(os.path.abspath(__file__))
MIN_IS = {"crypto": 40, "forex": 20}

def load():
    d = pd.concat([pd.read_pickle(f) for f in glob.glob(f"{HERE}/out/*.pkl") if "filter_b" not in f], ignore_index=True)
    d["yr"] = d.t.dt.year; d["blk"] = ""
    ends = {}
    for mk, g in d.groupby("market"):
        end = g.t.max().normalize() + pd.Timedelta("1D"); E = [end - pd.DateOffset(years=k) for k in (2, 1)]; ends[mk] = (g.t.min(), E, end)
        d.loc[g.index, "blk"] = np.where(g.t < E[0], "Y1", np.where(g.t < E[1], "Y2", "Y3"))
    d["fam"] = d.pat.map(base_name); d["cfg"] = d.trend + "/x" + d.sx.map(lambda v: f"{v:g}") + "/" + d.rr.map(lambda v: f"{v:g}R")
    return d, ends

def st(x):
    b = {k: round(float(x[x.blk == k].net.sum()), 1) for k in ("Y1", "Y2", "Y3")}
    bn = {k: int((x.blk == k).sum()) for k in ("Y1", "Y2", "Y3")}
    return dict(n=len(x), win=round(100*float((x.r > 0).mean()), 1), net=round(float(x.net.sum()), 1), avg=round(float(x.net.mean()), 3),
                blocks=b, blocks_n=bn, years={int(y): round(float(g.net.sum()), 1) for y, g in x.groupby("yr")},
                is_avg=round(float(x[x.blk != "Y3"].net.mean()), 3) if (x.blk != "Y3").any() else None)

def row(name, s): return (f"|{name}|{s['n']}|{s['win']}|{s['net']:+.1f}|{s['avg']:+.3f}|" + "|".join(f"{s['blocks'][k]:+.1f}" for k in ("Y1", "Y2", "Y3"))
                          + f"|{s['blocks_n']['Y3']}|" + " ".join(f"{y}:{v:+.0f}" for y, v in s["years"].items()) + "|")
HDR = ["|Pattern / config|Trades|Win%|Net R|Avg R|Y1|Y2|Y3 (OOS)|Y3 n|Calendar years|", "|-|-|-|-|-|-|-|-|-|-|"]

def main():
    d, ends = load(); res = {"periods": {k: [str(v[0]), [str(e) for e in v[1]], str(v[2])] for k, v in ends.items()}}
    L = ["# Part A — each candlestick pattern as a standalone strategy (research only)", ""]
    for mk, (a, E, end) in ends.items():
        L.append(f"- {mk}: signals {a:%Y-%m-%d} → {end:%Y-%m-%d}; Y1 → {E[0]:%Y-%m-%d}, Y2 → {E[1]:%Y-%m-%d}, Y3 = last 12 months (hold-out).")
    L += ["", "Net R after fees. Config = trend filter / stop multiple / target. 'pdf' = PDF prior-trend rule only, 'sma200' = + 200-SMA side.", ""]
    # 1) overview: pattern x tf at the base config, both trend variants
    for mk in ("crypto", "forex"):
        for tf in ("1h", "4h", "1D"):
            g = d[(d.market == mk) & (d.tf == tf)]
            if not len(g): continue
            L += [f"## {mk} {tf} — every pattern, stop at pattern extreme, 3R (pdf trend | sma200)", "",
                  "|Pattern|pdf: n|win%|net R|Y1|Y2|Y3|sma200: n|win%|net R|Y1|Y2|Y3|best cfg (by in-sample avg)|", "|-|-|-|-|-|-|-|-|-|-|-|-|-|-|"]
            for p, gp in sorted(g.groupby("pat"), key=lambda kv: -kv[1][(kv[1].cfg == "pdf/x1/3R")].net.sum()):
                cells = []
                for c in ("pdf/x1/3R", "sma200/x1/3R"):
                    x = gp[gp.cfg == c]
                    if len(x): s = st(x); cells.append(f"{s['n']}|{s['win']}|{s['net']:+.1f}|{s['blocks']['Y1']:+.1f}|{s['blocks']['Y2']:+.1f}|{s['blocks']['Y3']:+.1f}")
                    else: cells.append("0|–|–|–|–|–")
                bc = gp[gp.blk != "Y3"].groupby("cfg").net.agg(["mean", "count"]); bc = bc[bc["count"] >= 10]
                best = f"{bc['mean'].idxmax()} ({bc['mean'].max():+.3f})" if len(bc) else "–"
                L.append(f"|{p}|" + "|".join(cells) + f"|{best}|")
                res.setdefault("patterns", {}).setdefault(f"{mk}|{tf}|{p}", {c: st(x) for c, x in gp.groupby("cfg")})
            L.append("")
    # 2) selection on in-sample only
    sel = []
    for (mk, tf, p, c), x in d.groupby(["market", "tf", "pat", "cfg"]):
        i = x[x.blk != "Y3"]
        if len(i) < MIN_IS[mk]: continue
        y1, y2 = i[i.blk == "Y1"].net.sum(), i[i.blk == "Y2"].net.sum()
        if y1 > 0 and y2 > 0 and i.net.mean() >= 0.10: sel.append((mk, tf, p, c, float(i.net.mean()), len(i)))
    S = pd.DataFrame(sel, columns="market tf pat cfg is_avg is_n".split())
    # one config per pattern (best in-sample avg), and drop the relaxed twin if the strict one is also picked
    S = S.sort_values("is_avg", ascending=False).drop_duplicates(["market", "tf", "pat"])
    L += ["## In-sample selection (Y1 and Y2 both positive, in-sample avg ≥ +0.10R, enough trades; best config per pattern)", "", *HDR]
    picks = []
    for _, r in S.iterrows():
        x = d[(d.market == r.market) & (d.tf == r.tf) & (d.pat == r.pat) & (d.cfg == r.cfg)]; s = st(x)
        L.append(row(f"{r.market} {r.tf} {r.pat} [{r.cfg}] IS {r.is_avg:+.3f}", s)); picks.append(dict(r) | {"stats": s})
    res["picks"] = picks
    # 3) CANDLE-21 = union of picks per market (same symbol/tf/direction/time de-duplicated)
    L += ["", "## CANDLE-21 candidate (all in-sample picks together; Y3 = out-of-sample)", "", *HDR]
    cand = {}
    for mk in ("crypto", "forex"):
        P = S[S.market == mk]
        if not len(P): continue
        key = set(zip(P.tf, P.pat, P.cfg))
        x = d[(d.market == mk) & np.array([k in key for k in zip(d.tf, d.pat, d.cfg)])].sort_values("t")
        x = x.drop_duplicates(["sym", "tf", "dir", "t"]); s = st(x); cand[mk] = s; L.append(row(f"CANDLE-21 {mk} ({len(P)} pattern×tf)", s))
        for tf, xt in x.groupby("tf"): L.append(row(f"  · {tf} only", st(xt)))
    res["candle21"] = cand
    fams = sorted(set(S[S.tf.isin(["4h", "1D"])].pat.map(base_name)))
    json.dump(fams, open(f"{HERE}/top_families.json", "w")); res["top_families"] = fams
    L += ["", f"Top families (picked on 4h/1D, used as the 'top' set in part B): {', '.join(fams) or '–'}"]
    open(f"{HERE}/results_a.md", "w").write("\n".join(L) + "\n"); json.dump(res, open(f"{HERE}/results_a.json", "w"), indent=1, default=str)
    print("\n".join(L[-60:]))

if __name__ == "__main__": main()
