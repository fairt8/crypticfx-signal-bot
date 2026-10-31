"""Compounding equity simulation on the real chronological trade order of the 3-year backtest (research only, no live change).
Seven best setups (results3y.md): DON20 live, PAT-WEDGE w1.5, BRK cur, PAT-TRIPLE forex live, FVG+TREND c60, FVG-PLAN w1.5,
MF-REJ forex live. Trades come from out3y/*.csv (the same rows report3y.py aggregates; DON20 one position per coin), forex live
exit times from out3y_exits/fx_live_exits.csv (fx_exits.py).
Sizing: risk = pct x realised balance when the trade opens (open trades share the balance; PnL realised at exit). net_r is after
fees. Balance <= 0 -> blown up (frozen at 0, no further trades). Fixed-$ runs: constant $ risk, no compounding.
Writes compound_results.md and compound_results.json."""
import os, glob, json
import numpy as np, pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__))
SETUPS = [("DON20", "crypto", "live", "DON20, current rules"), ("PAT-WEDGE", "crypto", "w1.5", "PAT-WEDGE, 1.5x stop 3R"),
          ("BRK", "crypto", "cur", "BRK, current stop 3R"), ("PAT-TRIPLE", "forex", "live", "PAT-TRIPLE forex, current rules"),
          ("FVG+TREND", "crypto", "c60", "FVG+TREND, 1h candle stop 3R"), ("FVG-PLAN", "crypto", "w1.5", "FVG-PLAN, 1.5x stop 3R"),
          ("MF-REJ", "forex", "live", "MF-REJ forex, current rules")]
START = 1000.0
COLS = ["strategy", "symbol", "t", "direction", "variant", "status", "r", "net_r", "risk_pct", "fill_t", "exit_t"]
def ts(s): x = pd.to_datetime(s, utc=True, format="mixed"); return x

def load():
    keep = {(s, m, v) for s, m, v, _ in SETUPS}; parts = []
    for f in sorted(glob.glob(f"{HERE}/out3y/*.csv")):
        x = pd.read_csv(f, usecols=COLS); x["market"] = np.where(x.symbol.str.endswith("USDT"), "crypto", "forex")
        x = x[[k in keep for k in zip(x.strategy, x.market, x.variant)]]
        parts.append(x.dropna(subset=["net_r"]))
    d = pd.concat(parts, ignore_index=True); d["t"] = ts(d.t); d["open_t"] = ts(d.fill_t.fillna(d.t.astype(str)))
    # exit times: crypto 3R variants store the 15m bar OPEN of the exit bar -> +15m (bar close). DON20 live stores the daily close.
    ex = ts(d.exit_t.where(d.exit_t.astype(str).str.len() > 4))
    d["close_t"] = ex + pd.to_timedelta(np.where((d.market == "crypto") & (d.variant != "live"), 15, 0), unit="min")
    fx = pd.read_csv(f"{HERE}/out3y_exits/fx_live_exits.csv"); fx["t"] = ts(fx.t); fx["xt"] = ts(fx.exit_t)
    m = d[(d.market == "forex") & (d.variant == "live")].merge(fx[["symbol", "strategy", "t", "direction", "xt", "live_r"]],
                                                               on=["symbol", "strategy", "t", "direction"], how="left")
    assert m.xt.notna().all(), f"{m.xt.isna().sum()} forex live rows without an exit time"
    assert np.allclose(m.r.values, m.live_r.values), "forex replay R differs from out3y"
    fm_ = (d.market == "forex") & (d.variant == "live"); d.loc[fm_, "close_t"] = m.xt.set_axis(d.index[fm_])
    d["close_t"] = pd.to_datetime(d.close_t, utc=True); assert d.close_t.notna().all()
    keep = []   # DON20: one position per coin (same rule as report3y.load)
    for sym, g in d[d.strategy == "DON20"].groupby("symbol"):
        last = None
        for i, r in g.sort_values("t").iterrows():
            if last is not None and r.open_t <= last: continue
            keep.append(i); last = r.close_t
    d = pd.concat([d[d.strategy != "DON20"], d.loc[keep]])
    bad = d.close_t <= d.open_t; d.loc[bad, "close_t"] = d.loc[bad, "open_t"] + pd.Timedelta("1ns")   # same-bar exits
    return d.sort_values(["open_t", "close_t"]).reset_index(drop=True)

def simulate(tr, pct=None, fixed=None):
    """Event replay. Closes are processed before opens at the same timestamp."""
    ev = [(t, 0, i) for i, t in enumerate(tr.close_t)] + [(t, 1, i) for i, t in enumerate(tr.open_t)]
    ev.sort(key=lambda e: (e[0], e[1])); R = tr.net_r.values; RP = tr.risk_pct.values / 100
    bal = START; peak = START; mdd = 0.0; minfrac = 1.0; risk = {}; nopen = 0; maxopen = 0; lev = 0.0; expo = 0.0
    blown = None; curve = [(tr.open_t.min(), START)]; outcomes = []
    for t, k, i in ev:
        if k == 1:
            if blown is not None: continue
            a = fixed if fixed else bal*pct; risk[i] = a; nopen += 1; maxopen = max(maxopen, nopen)
            expo += a/RP[i]; lev = max(lev, expo/bal if bal > 0 else np.inf)
        else:
            if i not in risk: continue
            a = risk.pop(i); nopen -= 1; expo -= a/RP[i]
            if blown is not None: continue
            bal += a*R[i]; outcomes.append(R[i])
            if bal <= 0: bal = 0.0; blown = t
            peak = max(peak, bal); mdd = max(mdd, 1 - bal/peak); minfrac = min(minfrac, bal/peak); curve.append((t, bal))
    c = pd.Series([b for _, b in curve], index=pd.DatetimeIndex([t for t, _ in curve]))
    ls = cur = 0
    for r in outcomes: cur = cur + 1 if r < 0 else 0; ls = max(ls, cur)
    mo = c.resample("ME").last().ffill(); mo_start = mo.shift(1).fillna(START); mret = (mo/mo_start - 1).replace([np.inf, -np.inf], np.nan)
    yr = c.resample("YE").last().ffill(); yr_start = yr.shift(1).fillna(START)
    years = {int(i.year): (round(100*(b/s - 1), 1) if s > 0 else None) for i, b, s in zip(yr.index, yr.values, yr_start.values)}
    wm = mret.idxmin() if mret.notna().any() else None
    return dict(trades=len(outcomes), end=round(bal, 2), ret=round(100*(bal/START - 1), 1), mdd=round(100*mdd, 1), streak=ls, maxopen=maxopen,
                below10=bool(minfrac <= 0.10), blown=str(blown) if blown is not None else None, max_lev=round(lev, 1),
                worst_month=(f"{wm:%Y-%m}", round(100*float(mret.min()), 1)) if wm is not None else None, years=years)

def fmt(x):
    if x["blown"]: return f"**$0 — blown up {x['blown'][:10]}** after {x['trades']} trades"
    e = x["end"]; return f"${e:,.0f}" if e < 1e7 else f"${e:.3g}"

def main():
    d = load(); res = {}; FIX = []; L = ["# Compounding simulation: 7 best setups of the 3-year backtest (research only, no live change)", ""]
    L += [f"Trades replayed in real time order: {d.open_t.min():%Y-%m-%d} → {d.close_t.max():%Y-%m-%d}. Start $1,000. Risk % of the realised balance when "
          "each trade opens (compounding); open trades share the balance; PnL realised at exit; net R is after fees. Balance ≤ $0 = blown up.", ""]
    L += ["|Setup|Trades|Net R|Risk|End balance|Return|Max DD|Longest losing streak|Fell below 10% of peak|Worst month|Per-year return|",
          "|-|-|-|-|-|-|-|-|-|-|-|"]
    def row(name, n, nr, lab, x, extra=""):
        yrs = " ".join(f"{y}: {'n/a' if v is None else f'{v:+,.0f}%'}" for y, v in x["years"].items())
        wm = f"{x['worst_month'][0]} {x['worst_month'][1]:+.0f}%" if x["worst_month"] else "–"
        L.append(f"|{name}|{n}|{nr:+.1f}|{lab}|{fmt(x)}|{x['ret']:+,.0f}%|{x['mdd']:.0f}%|{x['streak']}|{'yes' if x['below10'] else 'no'}|{wm}|{yrs}|{extra}")
    for s, mk, v, name in SETUPS:
        g = d[(d.strategy == s) & (d.market == mk) & (d.variant == v)].reset_index(drop=True); res[name] = dict(n=len(g), net=round(float(g.net_r.sum()), 1))
        for p in (0.01, 0.10):
            x = simulate(g, pct=p); res[name][f"{int(p*100)}%"] = x; row(name, len(g), g.net_r.sum(), f"{int(p*100)}%", x)
        fx10 = simulate(g, fixed=10.0); res[name]["fixed $10"] = fx10; FIX.append((name, fx10))
        del g
    L += ["", "Fixed $10 per trade, no compounding (sanity check: end = $1,000 + $10 × net R): " + "; ".join(
          f"{n} {fmt(x)} (max DD {x['mdd']:.0f}%)" for n, x in FIX)]
    a = d.reset_index(drop=True); res["ALL 7"] = dict(n=len(a), net=round(float(a.net_r.sum()), 1))
    L += ["", "## All 7 in one shared account", "",
          "|Sizing|Trades|End balance|Return|Max DD|Longest losing streak|Most trades open at once|Max notional / balance|Fell below 10% of peak|Worst month|Per-year return|",
          "|-|-|-|-|-|-|-|-|-|-|-|"]
    for lab, kw in (("1% compounding", dict(pct=0.01)), ("10% compounding", dict(pct=0.10)), ("Fixed $10 / trade", dict(fixed=10.0)), ("Fixed $100 / trade", dict(fixed=100.0))):
        x = simulate(a, **kw); res["ALL 7"][lab] = x
        yrs = " ".join(f"{y}: {'n/a' if v is None else f'{v:+,.0f}%'}" for y, v in x["years"].items())
        wm = f"{x['worst_month'][0]} {x['worst_month'][1]:+.0f}%" if x["worst_month"] else "–"
        L.append(f"|{lab}|{x['trades']}|{fmt(x)}|{x['ret']:+,.0f}%|{x['mdd']:.0f}%|{x['streak']}|{x['maxopen']}|{x['max_lev']}×|{'yes' if x['below10'] else 'no'}|{wm}|{yrs}|")
    L += ["", "## Assumptions and caveats",
          "- Same trades, fees and rules as results3y.md (net R per trade after the backtest fee model; no extra slippage or funding).",
          "- Crypto 3R-variant exits are stamped at the close of the 15m exit bar; forex live exits from fx_exits.py (1H / 4H bar close); DON20 at the daily close.",
          "- Trades still open at the follow horizon / end of data are closed at their marked-to-market R (as in results3y.md).",
          "- Risk is a % of the REALISED balance at entry; unrealised PnL of open trades is not counted. Drawdown is on the realised balance at each close.",
          "- No cap on concurrent trades or leverage; 'max notional / balance' shows the position size the stops imply (risk ÷ stop %).",
          "- Signals that the live bot would have skipped (cooldowns, duplicates across strategies on the same coin) are all taken here.",
          "- Backtest on today's top-50 coins (some survivorship), forex 2.77 years (Yahoo 1H limit). Not a forecast."]
    open(f"{HERE}/compound_results.md", "w").write("\n".join(L) + "\n")
    json.dump(res, open(f"{HERE}/compound_results.json", "w"), indent=1, default=str)
    print("\n".join(L))

if __name__ == "__main__": main()
