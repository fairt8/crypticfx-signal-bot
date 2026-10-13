import pandas as pd, numpy as np, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
df = pd.read_csv("backtest2_trades.csv"); df["t"] = pd.to_datetime(df.t, format="ISO8601"); df = df.sort_values("t")
T0 = df.t.min(); T1 = df.t.max(); CUT = T0 + (T1-T0)*2/3
df["period"] = np.where(df.t < CUT, "IS", "OOS")
METAL = df.symbol.isin(["XAUUSD","XAGUSD"])
taker = np.where(df.market=="crypto", 0.001, np.where(METAL, 0.0005, 0.0002))
def cost(d, rr, maker):
    st = d[f"st{rr}"]; base = taker[d.index] if False else None
    t = np.where(d.market=="crypto", 0.001, np.where(d.symbol.isin(["XAUUSD","XAGUSD"]), 0.0005, 0.0002))
    if maker: t = np.where(d.market=="crypto", np.where(st=="tp", 0.0004, 0.0007), t)
    return t / d.risk_pct
def stats(d, rr=3, maker=False):
    c = d[d[f"st{rr}"].isin(["tp","sl"])]
    if len(c) == 0: return dict(n=0)
    g = c[f"r{rr}"]; net = g - cost(c, rr, maker); eq = net.cumsum(); dd = (eq.cummax().clip(lower=0) - eq).max()
    return dict(n=len(c), win=round(100*(c[f"st{rr}"]=="tp").mean(),1), gross=round(g.mean(),3), net=round(net.mean(),3),
                net_tot=round(net.sum(),1), maxdd=round(dd,1))
def both(d, **k):
    a, b = stats(d[d.period=="IS"], **k), stats(d[d.period=="OOS"], **k)
    return {**{f"IS_{x}":y for x,y in a.items()}, **{f"OOS_{x}":y for x,y in b.items()}}
F = df[df.strat=="FVG"]; S = df[df.strat=="SWEEP"]; K = df[df.strat=="CHK"]
ms = lambda d, x: d[(d.market=="forex") | (d.risk_pct >= x/100)]
choice = {}; out = []
def pick(name, d, grid):   # choose on IS net expectancy (n>=100)
    best = None
    for key, sub in grid(d):
        s = stats(sub[sub.period=="IS"])
        out.append(f"- {name} IS grid {key}: n={s.get('n')}, net={s.get('net')}")
        if s.get("n",0) >= 100 and (best is None or s["net"] > best[1]): best = (key, s["net"], sub)
    choice[name] = best[0]; return best[2]
# FVG
F0 = ms(F, 0.3)
F3 = pick("FVG min 4H gap", F0, lambda d: [(f">={g}%", d[d.gap_pct >= g/100]) for g in (0.2, 0.5, 1.0)])
Sx = pick("SWEEP params", S, lambda d: [(f"lb={lb},minstop={x}%", ms(d[d.lookback==lb], x)) for lb in (48,96) for x in (0, 0.3)])
Kx = pick("CHK params", K, lambda d: [(f"S/R<={tol}ATR,minstop={x}%", ms(d[d.sr_dist_atr<=tol], x)) for tol in (0.5,1.0) for x in (0,0.3)])
V = {"FVG raw (no min stop)": (F, {}), "FVG live (crypto stop>=0.3%)": (F0, {}), "FVG live, 2R (comparison)": (F0, {"rr":2}),
     "FVG + 4H trend hard filter": (F0[F0.trend_ok], {}), f"FVG + 4H gap {choice['FVG min 4H gap']}": (F3, {}),
     "FVG live, futures maker/taker fees": (F0, {"maker":True}),
     f"SWEEP {choice['SWEEP params']}": (Sx, {}), "SWEEP, 2R (comparison)": (Sx, {"rr":2}), "SWEEP, futures fees": (Sx, {"maker":True}),
     f"CHK {choice['CHK params']}": (Kx, {}), "CHK, 2R (comparison)": (Kx, {"rr":2}), "CHK, futures fees": (Kx, {"maker":True})}
rows = {}
for name,(d,k) in V.items():
    for mk in ("crypto","forex"):
        rows[(name, mk)] = both(d[d.market==mk], **k)
tab = pd.DataFrame(rows).T
cols = ["IS_n","IS_win","IS_gross","IS_net","IS_maxdd","OOS_n","OOS_win","OOS_gross","OOS_net","OOS_net_tot","OOS_maxdd"]
tab = tab[[c for c in cols if c in tab]]
cal = []
for name, d, col, bins in [("FVG live", F0, "score", [0,54,64,74,100]), ("CHK", Kx, "score", [-1,0,1,2]), ]:
    o = d[(d.period=="OOS") & d.st3.isin(["tp","sl"])]
    g = o.groupby(pd.cut(o[col], bins), observed=True).st3.agg(n="count", win=lambda s: round(100*(s=="tp").mean(),1))
    cal.append(f"\n**{name}: OOS win % by score**\n\n" + g.to_markdown())
sess = []
for name, d in [("FVG live", F0), ("SWEEP", Sx), ("CHK", Kx)]:
    o = d[(d.period=="OOS")]
    sess.append(f"\n**{name}: OOS by session/direction**\n\n" + pd.DataFrame({f"{a}={v}": stats(o[o[a]==v]) for a in ("in_session","direction") for v in sorted(o[a].unique())}).T.to_markdown())
open("bt2_tables.md","w").write(f"Split: IS {T0:%Y-%m-%d} to {CUT:%Y-%m-%d %H:%M}, OOS to {T1:%Y-%m-%d} (UTC)\n\nParameter grid (chosen on IS only):\n" + "\n".join(out) +
    "\n\n" + tab.to_markdown() + "\n" + "\n".join(cal) + "\n" + "\n".join(sess))
print(open("bt2_tables.md").read())
fig, ax = plt.subplots(figsize=(12,6))
for name in ["FVG live (crypto stop>=0.3%)", f"SWEEP {choice['SWEEP params']}", f"CHK {choice['CHK params']}", "FVG + 4H trend hard filter"]:
    d, k = V[name]; c = d[d.st3.isin(["tp","sl"])]; net = c.r3 - cost(c, 3, False)
    ax.plot(c.t, net.cumsum(), label=name+" (net)")
    ax.plot(c.t, c.r3.cumsum(), "--", alpha=.5, label=name+" (gross)")
ax.axvline(CUT, color="k", ls=":", label="IS | OOS split"); ax.axhline(0, color="k", lw=.5)
ax.set_ylabel("cumulative R"); ax.set_title("v2 backtest: all markets, 3R, 15m entry"); ax.legend(fontsize=7)
plt.tight_layout(); plt.savefig("comparison_chart.png", dpi=110)
