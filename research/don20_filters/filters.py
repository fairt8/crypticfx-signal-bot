# DON20 entry-filter backtest: current live entry rules + current exits (3xATR20 stop, 3xATR chandelier trail, no TP), fees 0.1%/side.
# Filters are applied at the signal bar using only information known at that close.
import json, numpy as np, pandas as pd, itertools
N, COST, K = 20, 0.001, 3.0
syms = json.load(open("syms.json"))
T0, WF, END = pd.Timestamp("2024-02-01"), pd.Timestamp("2025-07-01"), None
def load(s):
    d = pd.read_csv(f"d1x/{s}.csv"); d["t"] = pd.to_datetime(d.t, unit="ms"); d = d.iloc[:-1].reset_index(drop=True)
    tr = pd.concat([d.h-d.l,(d.h-d.c.shift()).abs(),(d.l-d.c.shift()).abs()],axis=1).max(axis=1); d["atr"] = tr.rolling(N).mean()
    ma = d.c.rolling(200).mean(); sl = ma/ma.shift(20)-1
    d["ctrend"] = np.where(ma.isna(), "n/a", np.where((d.c>ma)&(sl>0), "bull", np.where((d.c<ma)&(sl<0), "bear", "range")))
    d["cma"] = np.where(ma.isna(), 0, np.where(d.c>ma, 1, -1))          # coin above(+1)/below(-1) own 200D SMA
    d["rp"] = K*d.atr/d.c                                                # initial stop distance as fraction of price
    d["rpct"] = d.rp.rolling(250, min_periods=100).apply(lambda x: (x[:-1] < x[-1]).mean()*100, raw=True)  # percentile vs own past
    return d
btc = load("BTCUSDT")
BT = dict(zip(btc.t.dt.date, btc.ctrend)); BMA = dict(zip(btc.t.dt.date, btc.cma))
def allow(f, side, r, day):
    for kind, p in f:
        if kind == "btc_strict":
            s = BT.get(day, "n/a")
            if not ((side == 1 and s == "bull") or (side == -1 and s == "bear")): return False
        elif kind == "btc_soft":
            s = BT.get(day, "n/a")
            if (side == 1 and s == "bear") or (side == -1 and s == "bull"): return False
        elif kind == "btc_ma":
            m = BMA.get(day, 0)
            if m and m != side: return False
        elif kind == "coin_strict":
            s = r.ctrend
            if not ((side == 1 and s == "bull") or (side == -1 and s == "bear")): return False
        elif kind == "coin_soft":
            if (side == 1 and r.ctrend == "bear") or (side == -1 and r.ctrend == "bull"): return False
        elif kind == "coin_ma":
            if r.cma and r.cma != side: return False
        elif kind == "stop_max":
            if r.rp*100 > p: return False
        elif kind == "atr_pctl":
            if r.rpct == r.rpct and r.rpct > p: return False
    return True
def run(d, f):
    A = d.atr.values; o,h,l,c,qv = (d[x].values for x in "o h l c qv".split()); t = d.t.values; out = []; pos = None
    def fin(pos, x, i, st):
        g = pos["sd"]*(x-pos["e"])/pos["risk"]; n = g - COST*(pos["e"]+x)/pos["risk"]
        out.append(dict(t=t[pos["i"]], exit=t[i], days=i-pos["i"], dir=pos["dir"], n=n, status=st, risk_pct=pos["risk"]/pos["e"]))
    for i in range(N+2, len(d)):
        if pos:
            sd, stp = pos["sd"], pos["stop"]
            if (sd == 1 and l[i] <= stp) or (sd == -1 and h[i] >= stp):
                fin(pos, min(stp,o[i]) if sd == 1 else max(stp,o[i]), i, "closed"); pos = None; continue
            pos["best"] = max(pos["best"],c[i]) if sd == 1 else min(pos["best"],c[i])
            ns = pos["best"]-sd*K*A[i]; pos["stop"] = max(stp,ns) if sd == 1 else min(stp,ns); continue
        a = A[i]
        if not a or a != a or a <= 0 or qv[i] < 1e6: continue
        side = 1 if c[i] > h[i-N:i].max() else (-1 if c[i] < l[i-N:i].min() else 0)
        if not side: continue
        if f and not allow(f, side, d.iloc[i], pd.Timestamp(t[i]).date()): continue
        e = c[i]; st = e-side*K*a
        if side == 1 and st <= 0: continue
        pos = dict(sd=side, dir="long" if side == 1 else "short", e=e, risk=abs(e-st), stop=st, best=e, i=i)
    if pos: fin(pos, c[-1], len(d)-1, "open")
    return out
def mdd(cl):
    eq = cl.sort_values("exit").groupby(cl.exit.dt.date).n.sum().cumsum(); return float((eq.cummax().clip(lower=0)-eq).max()) if len(eq) else 0.0
def st(x):
    cl = x[x.status == "closed"]
    return dict(n=len(cl), win=round(100*(cl.n > 0).mean(),1) if len(cl) else 0, net=round(cl.n.sum(),1), avg=round(cl.n.mean(),3) if len(cl) else 0,
                mdd=round(mdd(cl),1), open=int((x.status == "open").sum()), open_r=round(x[x.status == "open"].n.sum(),1))
A_ = {"none": [], "BTC strict (long bull/short bear)": [("btc_strict",0)], "BTC soft (no counter-trend)": [("btc_soft",0)],
      "BTC vs 200D SMA (no slope)": [("btc_ma",0)], "coin strict own 200D+slope": [("coin_strict",0)],
      "coin soft own 200D+slope": [("coin_soft",0)], "coin vs own 200D SMA": [("coin_ma",0)]}
B_ = {"none": []} | {f"stop<={p}%": [("stop_max",p)] for p in (10,12,15,20,25)} | {f"ATR pctl<={p}": [("atr_pctl",p)] for p in (50,70,80,90)}
data = {s: load(s) for s in syms}
V = {}
for an, af in A_.items():
    for bn, bf in B_.items():
        if an == "none" or bn == "none" or an in ("BTC soft (no counter-trend)","BTC vs 200D SMA (no slope)","coin vs own 200D SMA","BTC strict (long bull/short bear)","coin soft own 200D+slope"):
            V[(an, bn)] = af+bf
R = {}
for key, f in V.items():
    rows = []
    for s, d in data.items():
        for r in run(d, f):
            if pd.Timestamp(r["t"]) >= T0: r["sym"] = s; rows.append(r)
    df = pd.DataFrame(rows); df["t"] = pd.to_datetime(df.t); df["exit"] = pd.to_datetime(df.exit); R[key] = df
last = max(df.t.max() for df in R.values()); L120 = last - pd.Timedelta("120D")
def row(df):
    cl = df[df.status == "closed"]; y = {yr: round(cl[cl.t.dt.year == yr].n.sum(),1) for yr in (2024,2025,2026)}
    return st(df) | {"y2024": y[2024], "y2025": y[2025], "y2026": y[2026], "last120": round(cl[cl.t >= L120].n.sum(),1),
                     "IS": st(df[df.t < WF]), "OOS": st(df[df.t >= WF])}
T = {k: row(df) for k, df in R.items()}
base = T[("none","none")]
print(f"coins {len(data)}, entries {T0.date()}..{last.date()}, IS < {WF.date()} <= OOS. BTC trend known from {btc.t[btc.ctrend!='n/a'].iloc[0].date()}")
hdr = f"{'trend filter':34s} {'vol filter':14s} {'n':>5s} {'win%':>5s} {'netR':>7s} {'avgR':>6s} {'maxDD':>6s} | {'2024':>6s} {'2025':>6s} {'2026':>6s} {'120d':>6s} | {'IS':>6s} {'OOS':>6s} {'OOSdd':>6s} | open(R) | yrs>base"
print(hdr)
for k, r in T.items():
    beats = sum(r[f"y{y}"] > base[f"y{y}"] for y in (2024,2025,2026))
    print(f"{k[0]:34s} {k[1]:14s} {r['n']:5d} {r['win']:5.1f} {r['net']:+7.1f} {r['avg']:+6.3f} {r['mdd']:6.1f} | {r['y2024']:+6.1f} {r['y2025']:+6.1f} {r['y2026']:+6.1f} {r['last120']:+6.1f} | {r['IS']['net']:+6.1f} {r['OOS']['net']:+6.1f} {r['OOS']['mdd']:6.1f} | {r['open']}({r['open_r']:+.1f}) | {beats}/3")
# walk-forward: choose the best variant on IS (by net R, and by net R / maxDD), report its OOS
for crit, fn in (("IS net R", lambda r: r["IS"]["net"]), ("IS net/maxDD", lambda r: r["IS"]["net"]/max(r["IS"]["mdd"],1))):
    for fam, keys in (("vol threshold only", [k for k in T if k[0] == "none"]), ("all combos", list(T))):
        b = max(keys, key=lambda k: fn(T[k])); r = T[b]
        print(f"WF [{fam}, pick by {crit}] -> {b}: IS {r['IS']['net']:+.1f} (base {base['IS']['net']:+.1f}) | OOS {r['OOS']['net']:+.1f}/{r['OOS']['n']} dd {r['OOS']['mdd']} (base {base['OOS']['net']:+.1f}/{base['OOS']['n']} dd {base['OOS']['mdd']})")
json.dump({" | ".join(k): v for k, v in T.items()}, open("filters_res.json","w"), indent=1)
# live impact: apply each filter to the live DON20 trades at their signal bar
live = json.load(open("live.json")); feats = {}
for s in {x["sym"] for x in live}:
    try: feats[s] = load(s)
    except FileNotFoundError: pass
lv = []
for x in live:
    d = feats.get(x["sym"]); side = 1 if x["dir"] == "long" else -1; hit = None
    if d is None: continue
    for off in (1, 0, 2):   # live 'day' = alert day; signal bar is normally the prior daily close
        day = (pd.Timestamp(x["day"]) - pd.Timedelta(days=off)).date(); m = d[d.t.dt.date == day]
        if len(m):
            i = m.index[0]
            if i > N and ((side == 1 and d.c[i] > d.h[i-N:i].max()) or (side == -1 and d.c[i] < d.l[i-N:i].min())): hit = (i, day); break
    if hit is None: m = d[d.t.dt.date == (pd.Timestamp(x["day"]) - pd.Timedelta(days=1)).date()]; hit = (m.index[0], m.t.iloc[0].date()) if len(m) else None
    if hit: lv.append((x, d.iloc[hit[0]], hit[1], side))
print(f"\nlive DON20 trades matched to a signal bar: {len(lv)}/{len(live)} (open {sum(1 for x,*_ in lv if x['status']=='open')})")
pnl = lambda x: (x["now_n"] if x["status"] == "open" else x["net_r"]) or 0
tot = sum(pnl(x) for x,*_ in lv); print(f"all matched live trades: net {tot:+.2f}R (open {sum(pnl(x) for x,*_ in lv if x['status']=='open'):+.2f}R)")
print(f"{'filter':52s} blocked open (their now R) | blocked closed (their R) | kept open R")
for k, f in V.items():
    if not f: continue
    bo = [x for x,r,day,sd in lv if x["status"] == "open" and not allow(f, sd, r, day)]
    bc = [x for x,r,day,sd in lv if x["status"] == "closed" and not allow(f, sd, r, day)]
    ko = sum(pnl(x) for x,*_ in lv if x["status"] == "open") - sum(pnl(x) for x in bo)
    print(f"{k[0]+' + '+k[1]:52s} {len(bo):3d} ({sum(pnl(x) for x in bo):+6.2f}) | {len(bc):2d} ({sum(pnl(x) for x in bc):+6.2f}) | {ko:+6.2f}")
