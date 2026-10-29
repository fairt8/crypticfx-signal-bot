"""Aggregate out/*.csv -> results.md / results.json. Net R = gross R - 0.10% round-trip cost / stop distance (as app/backtest_all).
In-sample = first 2/3 of the window, out-of-sample = last 1/3. Seasons = BTC daily vs 200D SMA + 20d slope (backtest_all.season_series)."""
import sys, os, glob, json, pickle, itertools
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import numpy as np, pandas as pd
from app.backtest_all import season_series, season_at
COST = 0.001
B = pd.concat([pd.read_csv(f) for f in glob.glob("out/*_base.csv") if os.path.getsize(f) > 5])
V = pd.concat([pd.read_csv(f) for f in glob.glob("out/*_v2.csv") if os.path.getsize(f) > 5])
for d in (B, V): d["t"] = pd.to_datetime(d.t, utc=True)
T0, T1 = min(B.t.min(), V.t.min()), max(B.t.max(), V.t.max()); SPLIT = T0 + (T1 - T0) * 2 / 3
_, _, d1 = pickle.load(open("data/BTCUSDT.pkl", "rb")); d1 = d1.copy(); d1["ct"] = d1.t + pd.Timedelta("1D"); SS = season_series(d1)
def seas(t): return season_at(SS, t - pd.Timedelta("1D"))
for d in (B, V): d["season"] = [seas(t) for t in d.t]; d["month"] = d.t.dt.strftime("%Y-%m"); d["oos"] = d.t >= SPLIT
def net(df, col="r"): return df[col] - COST / df.rf
def stats(df, col="r"):
    df = df[df[col].notna()].sort_values("t")
    if not len(df): return dict(n=0, win=None, net=0.0, avg=None, dd=0.0, is_=0.0, oos=0.0, last120=0.0)
    n = net(df, col); eq = n.cumsum(); dd = float((eq.cummax().clip(lower=0) - eq).max())
    return dict(n=len(df), win=round(100 * (df[col] > 0).mean(), 1), net=round(float(n.sum()), 1), avg=round(float(n.mean()), 3), dd=round(dd, 1),
                is_=round(float(n[~df.oos].sum()), 1), oos=round(float(n[df.oos].sum()), 1), n_oos=int(df.oos.sum()),
                last120=round(float(n[df.t >= T1 - pd.Timedelta(days=120)].sum()), 1),
                is_avg=round(float(n[~df.oos].mean()), 3) if (~df.oos).any() else None, oos_avg=round(float(n[df.oos].mean()), 3) if df.oos.any() else None,
                ci90=[round(float(q), 3) for q in np.percentile([np.random.default_rng(i).choice(n.values, len(n)).mean() for i in range(400)], [5, 95])])
def by(df, key, col="r"):
    df = df[df[col].notna()]; return {k: (len(g), round(float(net(g, col).sum()), 1), round(100 * (g[col] > 0).mean())) for k, g in df.groupby(key)}
# ---- V2 config grid ----
V["cfg"] = V.src + "|" + V.tol.astype(str) + "|" + V.entry + "|" + V.tp
def v2sel(bias="st", zone=0, sess=0, src="15m", tol=0.001, entry="fvg", tp="liq"):
    d = V[(V.src == src) & (V.tol == tol) & (V.entry == entry) & (V.tp == tp)]
    if bias == "st": d = d[d.bias_st == 1]
    elif bias == "ema": d = d[d.bias_ema == 1]
    elif bias == "both": d = d[(d.bias_st == 1) & (d.bias_ema == 1)]
    if zone: d = d[d.in_zone == 1]
    if sess: d = d[d.sess == 1]
    return d
grid = []
_st = stats
stats = lambda df, col="r": {k: v for k, v in _st(df, col).items() if k != "ci90"} if True else None
def stats_ci(df, col="r"): return _st(df, col)
for bias, zone, sess, src, tol, entry, tp in itertools.product(("st", "ema", "both", "none"), (0, 1), (0, 1), ("15m", "1h"), (0.0005, 0.001, 0.002), ("fvg", "ob", "ote62", "ote705"), ("liq", "htf", "2R", "3R")):
    s = stats(v2sel(bias, zone, sess, src, tol, entry, tp)); s.update(bias=bias, zone=zone, sess=sess, src=src, tol=tol, entry=entry, tp=tp); grid.append(s)
G = pd.DataFrame(grid); G.to_csv("grid.csv", index=False)
# in-sample pick
cand = G[(G.n - G.n_oos) >= 60].sort_values("is_", ascending=False)
# ---- baseline + add-ons ----
B["r_liqf"] = B.r_liq.fillna(B.r)   # liquidity TP, fall back to 3R if no target >= 1R
addons = {"current FVG-PLAN (3R)": (B, "r"),
          "+ 4H structure bias agrees": (B[B.bias_st == 1], "r"), "+ 4H structure not against": (B[B.bias_st >= 0], "r"),
          "+ 4H EMA50 bias agrees": (B[B.bias_ema == 1], "r"),
          "+ 15m EQH/EQL sweep (0.1%) in last 4h": (B[B["sweep_15m_0.001"] == 1], "r"), "+ 1H EQH/EQL sweep in last 4h": (B[B["sweep_1h_0.001"] == 1], "r"),
          "+ any 15m swing sweep in last 4h": (B[B.sweep_swing == 1], "r"),
          "+ 4H structure bias + any swing sweep": (B[(B.bias_st == 1) & (B.sweep_swing == 1)], "r"),
          "TP 2R instead of 3R": (B, "r_2R"), "TP at opposing liquidity": (B, "r_liqf"),
          "+ 4H structure bias, TP 2R": (B[B.bias_st == 1], "r_2R"),
          "+ 15m EQ sweep + 4H EMA50 bias": (B[(B["sweep_15m_0.001"] == 1) & (B.bias_ema == 1)], "r"),
          "+ 15m EQ sweep + 4H structure bias": (B[(B["sweep_15m_0.001"] == 1) & (B.bias_st == 1)], "r"),
          "+ 15m EQ sweep, TP at opposing liquidity": (B[B["sweep_15m_0.001"] == 1], "r_liqf")}
stats = stats_ci
A = {k: stats(d, c) for k, (d, c) in addons.items()}
out = dict(window=[str(T0), str(T1)], split=str(SPLIT), coins=int(V.sym.nunique()), addons=A,
           base_month=by(B, "month"), base_season=by(B, "season"))
L = [f"Window {T0:%Y-%m-%d} → {T1:%Y-%m-%d}, {B.sym.nunique()} coins; split IS < {SPLIT:%Y-%m-%d} ≤ OOS. Net R after 0.10% round-trip fees.", "",
     "## Current FVG-PLAN and single-step add-ons", "", "|variant|trades|win%|net R|avg R (90% CI)|max DD|IS R (avg)|OOS R (n, avg)|last 120d|", "|-|-|-|-|-|-|-|-|-|"]
f = lambda s: f"{s['n']}|{s['win']}|{s['net']:+.1f}|{s['avg']:+.3f} ({s['ci90'][0]:+.2f}..{s['ci90'][1]:+.2f})|{s['dd']:.1f}|{s['is_']:+.1f} ({s['is_avg']:+.3f})|{s['oos']:+.1f} ({s['n_oos']}, {s['oos_avg']:+.3f})|{s['last120']:+.1f}" if s['n'] else "0|–|0|–|0|0|0|0"
for k, s in A.items(): L.append(f"|{k}|{f(s)}|")
named = {"FULL PLAN (4H structure, 15m EQ 0.1%, FVG entry, TP opposing liquidity)": dict(),
         "full plan, TP 2R": dict(tp="2R"), "full plan, TP 3R": dict(tp="3R"), "full plan, TP HTF only (4H swing / 4H FVG)": dict(tp="htf"),
         "full plan, OB entry": dict(entry="ob"), "full plan, OTE 62% entry": dict(entry="ote62"), "full plan, OTE 70.5% entry": dict(entry="ote705"),
         "full plan, OTE 62%, 3R": dict(entry="ote62", tp="3R"),
         "full plan + sweep inside unfilled 4H FVG": dict(zone=1), "full plan + London/NY session": dict(sess=1),
         "full plan, 4H EMA50 bias": dict(bias="ema"), "full plan, no 4H bias": dict(bias="none"), "full plan, 1H EQ levels": dict(src="1h"),
         "full plan, EQ tol 0.05%": dict(tol=0.0005), "full plan, EQ tol 0.2%": dict(tol=0.002)}
NS = {}
L += ["", "## New 6-step plan (V2) and variants", "", "|variant|trades|win%|net R|avg R (90% CI)|max DD|IS R (avg)|OOS R (n, avg)|last 120d|", "|-|-|-|-|-|-|-|-|-|"]
for k, kw in named.items(): NS[k] = stats(v2sel(**kw)); L.append(f"|{k}|{f(NS[k])}|")
out["v2_named"] = NS
L += ["", f"## Walk-forward: best 10 V2 configs chosen on in-sample only (≥60 IS trades) of {len(G)}", "", "|bias|zone|sess|liq|tol|entry|TP|IS R (n)|OOS R (n)|OOS avg|", "|-|-|-|-|-|-|-|-|-|-|"]
for _, r in cand.head(10).iterrows():
    d = v2sel(r.bias, r.zone, r.sess, r.src, r.tol, r.entry, r.tp); o = d[d.oos]
    L.append(f"|{r.bias}|{r.zone}|{r.sess}|{r.src}|{r.tol}|{r.entry}|{r.tp}|{r.is_:+.1f} ({r.n - r.n_oos})|{r.oos:+.1f} ({r.n_oos})|{(net(o).mean() if len(o) else 0):+.3f}|")
pos = G[G.n_oos >= 20]; L += ["", f"Share of V2 configs (≥20 OOS trades) with positive OOS net R: {100*(pos.oos > 0).mean():.0f}% of {len(pos)}; "
     f"with positive full-period net R: {100*(G[G.n>=30].net > 0).mean():.0f}% of {len(G[G.n>=30])}."]
best = cand.iloc[0]; bd = v2sel(best.bias, best.zone, best.sess, best.src, best.tol, best.entry, best.tp)
fp = v2sel()
months = sorted(set(B.month) | set(V.month))
L += ["", "## Net R per month (trades)", "", "|strategy|" + "|".join(months) + "|", "|-|" + "-|" * len(months)]
for nm, d, c in (("current FVG-PLAN", B, "r"), ("full plan V2", fp, "r"), ("IS-best V2", bd, "r"), ("FVG-PLAN + 15m EQ sweep", B[B["sweep_15m_0.001"] == 1], "r")):
    m = by(d, "month", c); L.append(f"|{nm}|" + "|".join(f"{m[x][1]:+.1f} ({m[x][0]})" if x in m else "–" for x in months) + "|")
L += ["", "## By BTC season (net R, trades, win%)", "", "|strategy|bull|bear|range|", "|-|-|-|-|"]
for nm, d, c in (("current FVG-PLAN", B, "r"), ("full plan V2", fp, "r"), ("IS-best V2", bd, "r"), ("FVG-PLAN + 15m EQ sweep", B[B["sweep_15m_0.001"] == 1], "r")):
    m = by(d, "season", c); L.append(f"|{nm}|" + "|".join(f"{m[x][1]:+.1f} ({m[x][0]}, {m[x][2]}%)" if x in m else "–" for x in ("bull", "bear", "range")) + "|")
out["is_best"] = dict(best.to_dict()); out["grid_size"] = len(G)
json.dump(out, open("results.json", "w"), indent=1, default=str); open("results.md", "w").write("\n".join(L) + "\n"); print("\n".join(L))
