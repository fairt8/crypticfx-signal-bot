import pandas as pd, numpy as np
d2 = pd.read_csv("backtest2_trades.csv"); d2["t"] = pd.to_datetime(d2.t, format="ISO8601")
T0, T1 = d2.t.min(), d2.t.max(); CUT = T0 + (T1-T0)*2/3
df = pd.read_csv("backtest3_trades.csv"); df["t"] = pd.to_datetime(df.t, format="ISO8601"); df = df.sort_values("t")
df["period"] = np.where(df.t < CUT, "IS", "OOS")
def cost(d): return np.where(d.market=="crypto", 0.001, np.where(d.symbol.isin(["XAUUSD","XAGUSD"]), 0.0005, 0.0002))
def stats(d, tag, rr=3):
    st, r, rk = f"st{rr}_{tag}", f"r{rr}_{tag}", f"risk_{tag}"
    c = d[d[st].isin(["tp","sl"])]
    if not len(c): return dict(n=0)
    net = c[r] - cost(c)/c[rk]; eq = net.cumsum(); dd = (eq.cummax().clip(lower=0)-eq).max()
    return dict(n=len(c), win=round(100*(c[st]=="tp").mean(),1), gross=round(c[r].mean(),3), net=round(net.mean(),3), net_tot=round(net.sum(),1), maxdd=round(dd,1), med_stop=round(100*c[rk].median(),2))
ms = lambda d, tag: d[(d.market=="forex") | (d[f"risk_{tag}"] >= 0.003)]
grid = []
for q in (4, 8, 16):
    s = stats(ms(df[(df.period=="IS") & (df.ttc <= q)], "swing"), "swing"); grid.append((q, s)); 
best = max([g for g in grid if g[1]["n"] >= 100], key=lambda g: g[1]["net"])[0]
V = {"LIVE (3-candle stop)": (ms(df,"fvg"), "fvg", 3), "PLAN (swing stop)": (ms(df,"swing"), "swing", 3),
     f"PLAN + quick reaction (tap→15m FVG ≤{best} bars)": (ms(df[df.ttc<=best],"swing"), "swing", 3),
     "PLAN, 2R (comparison)": (ms(df,"swing"), "swing", 2), "PLAN + 4H trend filter": (ms(df[df.trend_ok],"swing"), "swing", 3),
     "LIVE + 4H trend filter (current EXP)": (ms(df[df.trend_ok],"fvg"), "fvg", 3)}
rows = {}
for name, (d, tag, rr) in V.items():
    for mk in ("crypto", "forex"):
        x = d[d.market==mk]
        a, b = stats(x[x.period=="IS"], tag, rr), stats(x[x.period=="OOS"], tag, rr)
        rows[(name, mk)] = {**{f"IS_{k}":v for k,v in a.items()}, **{f"OOS_{k}":v for k,v in b.items()}}
t = pd.DataFrame(rows).T
txt = f"Split IS {T0:%Y-%m-%d}→{CUT:%Y-%m-%d %H:%M} UTC, OOS→{T1:%Y-%m-%d}. Quick-reaction grid on IS (swing stop): " + ", ".join(f"≤{q}: n={s['n']} net={s['net']}" for q,s in grid) + f" → {best}\n\n" + t.to_markdown()
o = ms(df[df.period=="OOS"], "swing"); o = o[o.st3_swing.isin(["tp","sl"])]
txt += "\n\n**PLAN OOS win % by setup score**\n\n" + o.groupby(pd.cut(o.score,[0,54,64,74,100]),observed=True).st3_swing.agg(n="count", win=lambda s: round(100*(s=="tp").mean(),1)).to_markdown()
open("bt3_tables.md","w").write(txt); print(txt)
