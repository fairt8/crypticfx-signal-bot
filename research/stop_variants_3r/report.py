"""Aggregate out/*.csv -> results.md / results.json. DON20: one position per coin, enforced separately for each variant
(a new signal is taken only after that variant's previous position on the coin has exited). OOS = last 1/3 of each market's window."""
import os, glob, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
ORDER = ["DON20", "CHK", "FVG-D1", "FVG-PLAN", "BRK", "MF-REJ", "PAT-TRIPLE", "FVG", "FVG+TREND", "PAT-WEDGE", "PAT-CUP"]
VN = {"live": "Current live rules", "cur": "Current stop, 3R TP", "w1.5": "1.5x wider stop, 3R", "w2": "2x wider stop, 3R",
      "c30": "30m candle stop, 3R", "c60": "1h candle stop, 3R"}
def load():
    fs = glob.glob(f"{HERE}/out/*.csv"); d = pd.concat([pd.read_csv(f) for f in fs], ignore_index=True)
    d["t"] = pd.to_datetime(d.t, utc=True, format="mixed"); d["market"] = np.where(d.symbol.str.endswith("USDT"), "crypto", "forex")
    d = d.dropna(subset=["net_r"])
    # DON20 one position per coin per variant
    keep = []
    for (sym, v), g in d[d.strategy == "DON20"].groupby(["symbol", "variant"]):
        last = None
        for i, r in g.sort_values("t").iterrows():
            ft = pd.Timestamp(r.fill_t) if isinstance(r.fill_t, str) and r.fill_t else r.t
            if ft.tzinfo is None: ft = ft.tz_localize("UTC")
            if last is not None and ft <= last: continue
            keep.append(i); xt = pd.Timestamp(r.exit_t) if isinstance(r.exit_t, str) and r.exit_t else ft
            last = xt.tz_localize("UTC") if xt.tzinfo is None else xt
    return pd.concat([d[d.strategy != "DON20"], d.loc[keep]]).sort_values("t")
def fm(v): return '–' if v is None else f'{v:+.3f}'
def mdd(x):
    c = np.cumsum(x); return float(np.max(np.maximum.accumulate(np.r_[0, c])[1:] - c)) if len(c) else 0.0
def stats(g):
    n = g.net_r.values
    return dict(n=len(n), win=round(100*float((g.r > 0).mean()), 1) if len(n) else None, net=round(float(n.sum()), 1),
                avg=round(float(n.mean()), 3) if len(n) else None, dd=round(mdd(n), 1), stop=round(float(g.risk_pct.median()), 2) if len(n) else None,
                floored=round(100*float(g.floored.astype(bool).mean()), 0) if len(n) else None,
                open=round(100*float(g.status.astype(str).str.startswith("open").mean()), 0) if len(n) else None,
                gross=round(float(g.r.mean()), 3) if len(n) else None, ci=ci(n))
def ci(n, B=2000):
    if len(n) < 20: return None
    rng = np.random.default_rng(0); m = rng.choice(n, (B, len(n))).mean(axis=1); return [round(float(np.percentile(m, 5)), 3), round(float(np.percentile(m, 95)), 3)]
def main():
    d = load(); res = {}; split = {}
    for mk, g in d.groupby("market"):
        a, b = g.t.min(), g.t.max(); split[mk] = a + (b - a)*2/3
    L = ["# All strategies × stop variants at a fixed 3R take-profit (research only)", "",
         f"Crypto window {d[d.market=='crypto'].t.min():%Y-%m-%d} → {d[d.market=='crypto'].t.max():%Y-%m-%d} (30 coins), OOS from {split['crypto']:%Y-%m-%d}. "
         f"Forex window {d[d.market=='forex'].t.min():%Y-%m-%d} → {d[d.market=='forex'].t.max():%Y-%m-%d}, OOS from {split['forex']:%Y-%m-%d}. Net R after fees.", ""]
    for s in ORDER:
        g = d[d.strategy == s]
        if not len(g): continue
        sp = split[g.market.iloc[0]]; res[s] = {}
        L += [f"## {s}", "", "|Variant|Trades|Win%|Net R|Avg R (90% CI)|Gross avg R|Max DD|Median stop %|Floored %|Open at horizon %|IS avg|OOS avg (n)|", "|-|-|-|-|-|-|-|-|-|-|-|-|"]
        for v in VN:
            x = g[g.variant == v]
            if not len(x): continue
            st = stats(x); i, o = x[x.t < sp], x[x.t >= sp]
            st.update(is_avg=round(float(i.net_r.mean()), 3) if len(i) else None, is_net=round(float(i.net_r.sum()), 1),
                      oos_avg=round(float(o.net_r.mean()), 3) if len(o) else None, oos_net=round(float(o.net_r.sum()), 1), oos_n=len(o))
            st["robust"] = bool(st["net"] > 0 and (st["is_avg"] or 0) > 0 and (st["oos_avg"] or 0) > 0)
            res[s][v] = st
            L.append(f"|{VN[v]}|{st['n']}|{st['win']}|{st['net']:+.1f}|{st['avg']:+.3f}{'' if not st['ci'] else f" ({st['ci'][0]:+.2f}..{st['ci'][1]:+.2f})"}|{st['gross']:+.3f}|{st['dd']:.1f}|{st['stop']}|{st['floored']:.0f}|{st['open']:.0f}|"
                     f"{fm(st['is_avg'])}|{fm(st['oos_avg'])} ({st['oos_n']})|" + (" ✅" if st["robust"] else ""))
        if s in ("MF-REJ", "PAT-TRIPLE"):   # 30m only exists for the last 60 days: paired comparison on that subset
            ids = set(g[g.variant == "c30"].sid)
            if ids:
                L += ["", f"Last-60-day subset (where 30m candles exist), {len(ids)} signals: " + ", ".join(
                    f"{v} {g[(g.variant == v) & g.sid.isin(ids)].net_r.sum():+.1f}R" for v in VN if v != "live" or True)]
        L.append("")
    L += ["Robust (✅) = net R > 0 over the whole window AND avg R > 0 in both the first 2/3 and last 1/3."]
    open(f"{HERE}/results.md", "w").write("\n".join(L) + "\n"); json.dump(dict(split={k: str(v) for k, v in split.items()}, results=res), open(f"{HERE}/results.json", "w"), indent=1)
    print("\n".join(L))
if __name__ == "__main__": main()
