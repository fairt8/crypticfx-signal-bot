"""Monthly backtest of ALL strategies (active + retired) with the live code paths, broken down per month and per market season.
Usage:  python -m app.backtest_all [--days 120] [--crypto 20] [--workers 2] [--no-telegram] [--out bt_all]
Writes <out>/backtest-all-YYYY-MM-DD.md and .json; sends a short Telegram summary (TELEGRAM_* env) unless --no-telegram.

Strategies and how they are replayed (same functions the live scan calls):
  FVG / FVG-D1 / FVG-PLAN / FVG+TREND  strategy.analyze on 4H + 15m (Binance), live gate setup_score >= MIN_POST_SCORE (70);
        FVG-D1 = daily_bias agrees, FVG-PLAN = strategy.plan_variant, FVG+TREND = EMA50/200 aligned. Outcome: outcomes.simulate
        on the next 400 15m bars (limit entry, 48h expiry, 50%-at-TP1 rule for PTP_STRATS).
  CHK         strategy.analyze_chk on every closed 1H bar (market entry), outcomes.simulate on 15m.
  DON20       don20.signal on daily candles, entry at the signal close, 3xATR chandelier trail, exit at stop (or open if gapped);
              one position per coin; still-open positions are marked to the last close.
  MF-REJ      strategy.analyze_mf on 1H for every pair/session in MF_PAIRS (incl. GBPCNH and synthetic XAUAUD) with its 1y 4H history;
              outcome on 1H bars at the next-zone TP. (The dynamic 'strong pair' is not replayed.)
  PAT-TRIPLE (forex) / PAT-WEDGE, PAT-CUP, BRK (crypto)  patterns_live.pat_series / brk_series on 4H, outcome on 4H at the tracked R.
Costs (round trip, in R = cost / stop distance): crypto 0.10%, forex majors 0.02%, crosses + CNH 0.03%, metals 0.05%.
Seasons: crypto = BTC daily vs its 200D SMA and the SMA's 20-day slope (bull: above & rising, bear: below & falling, else range);
forex = the same rule on each pair's own daily closes. A trade gets the season of the day before its entry."""
import argparse, json, os, sys, time, resource
from datetime import datetime, timezone
from concurrent.futures import ProcessPoolExecutor
import numpy as np, pandas as pd
from . import config as C, strategy, outcomes, strategies as SG
AGG = {"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}
CRYPTO_COST = 0.001
def fx_cost(sym): return 0.0005 if sym.startswith("XA") else (0.0002 if "USD" in sym and "CNH" not in sym else 0.0003)
def resample(df, f):
    x = df.set_index("t").resample(f, origin="epoch").agg(AGG).dropna(); x["t"] = x.index; x["ct"] = x.t + pd.Timedelta(f)
    return x.reset_index(drop=True)
def season_series(d1):
    """Daily season label (known at that day's close)."""
    c = d1.c; ma = c.rolling(200).mean(); sl = ma / ma.shift(20) - 1
    s = np.where((c > ma) & (sl > 0), "bull", np.where((c < ma) & (sl < 0), "bear", "range"))
    s = pd.Series(s, index=d1.ct.values); s[ma.isna().values] = "n/a"; return s
def season_at(ss, t):
    k = np.searchsorted(ss.index.values, np.datetime64(pd.Timestamp(t).tz_convert(None) if pd.Timestamp(t).tzinfo else pd.Timestamp(t)), side="right") - 1
    return ss.iloc[k] if k >= 0 else "n/a"
def rec(strat, sym, market, t, d, entry, sl, r, cost, status):
    rf = abs(entry - sl) / entry if entry else 0
    net = None if r is None else r - (cost / rf if rf > 0 else 0)
    return dict(strategy=strat, symbol=sym, market=market, t=str(t), direction=d, status=status, r=r, net_r=net)

# ---------------- data ----------------
def daily(sym, n):
    from . import binance
    d = binance.get("/api/v3/klines", symbol=sym, interval="1d", limit=min(1000, n))
    d1 = pd.DataFrame(d, columns="t o h l c v ct qv n tb tq i".split())[["t", "o", "h", "l", "c", "v"]].astype(float)
    d1["t"] = pd.to_datetime(d1.t, unit="ms", utc=True); d1["ct"] = d1.t + pd.Timedelta("1D")
    return d1[d1.ct <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True)
def crypto_data(sym, days):
    from .backtest import hist_klines
    end = int(time.time()*1000); st = end - days*86400_000
    h4 = hist_klines(sym, "4h", st - 70*86400_000, end); m15 = hist_klines(sym, "15m", st - 3*86400_000, end)
    d1 = daily(sym, days + 260); now = pd.Timestamp.now(tz="UTC")
    return tuple(x[x.ct <= now].reset_index(drop=True) for x in (h4, m15, d1))
def fx_data(pairs):
    from . import forex
    pv = forex.YFinanceProvider(); real = list(dict.fromkeys(q for p in pairs for q in forex.SYNTH.get(p, (p,))))
    tk = {pv.ticker(p): p for p in real}
    import yfinance as yf
    raw = yf.download(list(tk), interval="1h", period="730d", group_by="ticker", progress=False, auto_adjust=False, threads=True)
    one = {}
    for t, p in tk.items():
        try: one[p] = pv._norm(raw[t])
        except Exception: pass
    out = {}
    for p in pairs:
        try:
            a = forex.synth(one[forex.SYNTH[p][0]], one[forex.SYNTH[p][1]]) if p in forex.SYNTH else one[p]
            a = a.copy(); a["t"] = a.index; a["ct"] = a.t + pd.Timedelta("1h"); a = a.reset_index(drop=True)
            out[p] = a[a.ct <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True)
        except Exception as e: print("fx skip", p, e, flush=True)
    return out

# ---------------- replays ----------------
def run_crypto(a):
    sym, days, t0 = a; rows = []
    try: h4, m, d1 = crypto_data(sym, days)
    except Exception as e: return sym, [], f"data: {e}"
    if len(m) < 500 or len(h4) < 260: return sym, [], "short history"
    C.MIN_STOP_PCT_CRYPTO = float(os.environ.get("MIN_STOP_PCT_CRYPTO", "0.3"))
    # FVG family
    h, l = m.h.values, m.l.values; c4 = h4.ct.values; seen = set()
    for j in range(400, len(m) - 1):
        if m.t.iloc[j] < t0 or not (l[j] > h[j-2] or h[j] < l[j-2]): continue
        now = m.ct.iloc[j]; k = np.searchsorted(c4, now.to_datetime64(), side="right")
        if k < 60: continue
        try: sig = strategy.analyze(sym, "crypto", h4.iloc[max(0, k-300):k].reset_index(drop=True), m.iloc[j-399:j+1].reset_index(drop=True))
        except Exception: continue
        if not sig or sig["confirm_time"] in seen or (sig.get("setup_score") or 0) < C.MIN_POST_SCORE: continue
        seen.add(sig["confirm_time"]); fut = m.iloc[j+1:j+401]
        variants = [("FVG", sig)]
        if strategy.daily_bias(d1[d1.ct <= now], now) == sig["direction"]: variants.append(("FVG-D1", dict(sig, strategy="FVG-D1")))
        if any("EMA50/EMA200 trend aligned" in w for w in sig["reasons"]): variants.append(("FVG+TREND", dict(sig, strategy="FVG+TREND")))
        pv = strategy.plan_variant(sig)
        if pv: variants.append(("FVG-PLAN", pv))
        for nm, s in variants:
            st, _, _, r = outcomes.simulate(dict(s, status="pending", filled_at=None), fut)
            if st in ("pending", "expired"): continue   # never filled -> no trade
            rows.append(rec(nm, sym, "crypto", now, s["direction"], s["entry"], s["sl"], r, CRYPTO_COST, st))
    # CHK on 1H
    h1 = resample(m[["t", "o", "h", "l", "c", "v"]], "1h"); h1 = h1[h1.ct <= m.ct.iloc[-1]].reset_index(drop=True); ct15 = m.ct.values
    for i in range(225, len(h1) - 1):
        if h1.t.iloc[i] < t0: continue
        now = h1.ct.iloc[i]
        try: sig = strategy.analyze_chk(sym, "crypto", h4[h4.ct <= now].tail(300).reset_index(drop=True), h1.iloc[i-260:i+1].reset_index(drop=True), max_age_min=10**6)
        except Exception: continue
        if not sig: continue
        s0 = np.searchsorted(ct15, now.to_datetime64(), side="right"); st, _, _, r = outcomes.simulate(sig, m.iloc[s0:s0+400])
        rows.append(rec("CHK", sym, "crypto", now, sig["direction"], sig["entry"], sig["sl"], r if st in outcomes_closed() else mtm(sig, m.iloc[s0:s0+400]), CRYPTO_COST, st))
    # PAT-WEDGE / PAT-CUP / BRK on 4H (crypto)
    from . import patterns_live as P
    todo = [("BRK",) + P.brk_series(h4, "crypto", levels=C.BRK_LEVELS)] + [(nm,) + P.pat_series(nm, h4, "crypto") for nm, v in P.PAT.items() if v[0] == "crypto"]
    for nm, dd, aa, E in todo:
        R = 3.0 if nm == "BRK" else P.PAT[nm][5]; seen = set()
        for e in E:
            ct = dd.ct.iloc[e["k"]] if "ct" in dd else dd.t.iloc[e["k"]] + pd.Timedelta("4h")
            if ct < t0 or abs(e["entry"]-e["sl"])/e["entry"] < 0.003 or (e["k"], e["dir"]) in seen: continue
            seen.add((e["k"], e["dir"])); rows.append(pat_outcome(nm, sym, "crypto", dd, e, R, CRYPTO_COST, ct))
    # DON20 on daily
    rows += don20_replay(sym, d1, t0)
    return sym, rows, None
def outcomes_closed(): return ("tp", "sl", "be")
def mtm(sig, fut):
    if not len(fut): return 0.0
    sd = 1 if sig["direction"] == "long" else -1; return sd*(fut.c.iloc[-1] - sig["entry"])/abs(sig["entry"] - sig["sl"])
def pat_outcome(nm, sym, market, dd, e, R, cost, ct):
    entry, sl = float(e["entry"]), float(e["sl"]); sd = 1 if e["dir"] == "long" else -1; risk = abs(entry - sl)
    sig = dict(direction=e["dir"], entry=entry, sl=sl, tp=entry + sd*R*risk, rr=R, confirm_time=str(ct), status="open", filled_at=str(ct), strategy=nm)
    fut = dd.iloc[e["k"]+1:e["k"]+181]; st, _, _, r = outcomes.simulate(sig, fut)
    return rec(nm, sym, market, ct, e["dir"], entry, sl, r if st in outcomes_closed() else mtm(sig, fut), cost, st)
def don20_replay(sym, d1, t0):
    from . import don20 as D
    if D.is_stock(sym) or len(d1) < 60: return []
    out = []; pos = None; A = D.atr(d1)
    for i in range(30, len(d1)):
        b = d1.iloc[i]
        if pos:
            sd = pos["sd"]
            if (sd == 1 and b.l <= pos["stop"]) or (sd == -1 and b.h >= pos["stop"]):
                x = min(pos["stop"], b.o) if sd == 1 else max(pos["stop"], b.o); g, n = D._r(dict(direction=pos["dir"], entry=pos["entry"], init_stop=pos["init"]), x)
                out.append(dict(strategy="DON20", symbol=sym, market="crypto", t=str(pos["t"]), direction=pos["dir"], status="closed", r=g, net_r=n)); pos = None; continue
            pos["best"] = max(pos["best"], b.c) if sd == 1 else min(pos["best"], b.c)
            ns = pos["best"] - sd*D.K*float(A.iloc[i]); pos["stop"] = max(pos["stop"], ns) if sd == 1 else min(pos["stop"], ns)
            continue
        if b.ct < t0: continue
        sg = D.signal(d1.iloc[:i+1])
        if not sg: continue
        side, a = sg; sd = 1 if side == "long" else -1; e = float(b.c)
        pos = dict(dir=side, sd=sd, entry=e, init=e - sd*D.K*a, stop=e - sd*D.K*a, best=e, t=b.ct)
    if pos:
        g, n = D._r(dict(direction=pos["dir"], entry=pos["entry"], init_stop=pos["init"]), float(d1.c.iloc[-1]))
        out.append(dict(strategy="DON20", symbol=sym, market="crypto", t=str(pos["t"]), direction=pos["dir"], status="open (marked to market)", r=g, net_r=n))
    return out
def run_fx(a):
    sym, h1, t0 = a; rows = []; cost = fx_cost(sym)
    h4 = resample(h1[["t", "o", "h", "l", "c", "v"]], "4h"); h4 = h4[h4.ct <= h1.ct.iloc[-1]].reset_index(drop=True)
    if sym in strategy.MF_PAIRS:
        for i in range(300, len(h1) - 1):
            if h1.t.iloc[i] < t0: continue
            x = h1.iloc[max(0, i-800):i+1]; ct = x.ct.iloc[-1]
            if strategy.mf_session(sym, ct) is None: continue
            hh = h4[h4.ct <= ct]
            try: sig = strategy.analyze_mf(sym, hh.tail(400), x, max_age_min=10**6, h4_long=hh.tail(2400))
            except Exception: continue
            if not sig: continue
            fut = h1.iloc[i+1:i+1+240]; st, _, _, r = outcomes.simulate(sig, fut)
            rows.append(rec("MF-REJ", sym, "forex", ct, sig["direction"], sig["entry"], sig["sl"], r if st in outcomes_closed() else mtm(sig, fut), cost, st))
    if sym in C.PAT_FX:
        from . import patterns_live as P
        dd, aa, E = P.pat_series("PAT-TRIPLE", h4, "forex"); seen = set()
        for e in E:
            ct = dd.ct.iloc[e["k"]]
            if ct < t0 or (e["k"], e["dir"]) in seen: continue
            seen.add((e["k"], e["dir"])); rows.append(pat_outcome("PAT-TRIPLE", sym, "forex", dd, e, P.PAT["PAT-TRIPLE"][5], cost, ct))
    return sym, rows, None

# ---------------- report ----------------
def agg(df):
    n = df.net_r.dropna(); return dict(n=int(len(n)), win=round(100*(df.loc[n.index, "r"] > 0).mean(), 1) if len(n) else None,
                                       net_r=round(float(n.sum()), 2), r_per_trade=round(float(n.mean()), 3) if len(n) else None)
def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--days", type=int, default=120); ap.add_argument("--crypto", type=int, default=20)
    ap.add_argument("--workers", type=int, default=2); ap.add_argument("--no-telegram", action="store_true"); ap.add_argument("--out", default="bt_all")
    a = ap.parse_args(); T = time.time(); t0 = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=a.days)
    from . import binance, don20
    syms = [s for s in binance.top_usdt_symbols(a.crypto + 10) if not don20.is_stock(s)][:a.crypto]
    for s in ("BTCUSDT", "ETHUSDT"):
        if s not in syms: syms.append(s)
    fxp = list(dict.fromkeys(list(strategy.MF_PAIRS) + C.PAT_FX))
    print(f"[bt_all] window {t0:%Y-%m-%d} → now · crypto {len(syms)} · forex {len(fxp)}", flush=True)
    fx = fx_data(fxp); rows = []; errs = []
    with ProcessPoolExecutor(a.workers) as ex:
        for sym, r, err in ex.map(run_crypto, [(s, a.days, t0) for s in syms]):
            rows += r; print(f"  {sym}: {len(r)} trades" + (f" ({err})" if err else ""), flush=True)
            if err: errs.append(f"{sym}: {err}")
        for sym, r, err in ex.map(run_fx, [(s, fx[s], t0) for s in fx]):
            rows += r; print(f"  {sym}: {len(r)} trades", flush=True)
    df = pd.DataFrame(rows, columns=["strategy", "symbol", "market", "t", "direction", "status", "r", "net_r"])
    df["t"] = pd.to_datetime(df.t, utc=True); df["month"] = df.t.dt.strftime("%Y-%m")
    # seasons
    btc = daily("BTCUSDT", a.days + 260)
    from .backtest_all import season_series as _ss
    sb = _ss(btc) if btc is not None else None; sfx = {}
    for p, h1 in fx.items(): sfx[p] = _ss(resample(h1[["t", "o", "h", "l", "c", "v"]], "1D"))
    df["season"] = [season_at(sb if m == "crypto" else sfx.get(s), t - pd.Timedelta("1D")) if (sb is not None or m != "crypto") else "n/a" for s, m, t in zip(df.symbol, df.market, df.t)]
    res = {"generated": datetime.now(timezone.utc).isoformat(), "window_days": a.days, "since": str(t0), "crypto_symbols": syms, "forex_pairs": list(fx),
           "season_rule": "200D SMA + 20d slope: bull above & rising, bear below & falling, else range (crypto: BTC; forex: each pair)",
           "btc_season_now": str(sb.iloc[-1]) if sb is not None else None, "strategies": {}}
    for k in SG.STATUS:
        g = df[df.strategy == k]
        res["strategies"][k] = dict(status=SG.status(k), label=SG.label(k), total=agg(g),
                                    by_month={m: agg(x) for m, x in g.groupby("month")}, by_season={s: agg(x) for s, x in g.groupby("season")})
    res["runtime_s"] = round(time.time() - T); res["max_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
    res["max_rss_worker_mb"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
    res["errors"] = errs
    os.makedirs(a.out, exist_ok=True); stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    jp = os.path.join(a.out, f"backtest-all-{stamp}.json"); mp = os.path.join(a.out, f"backtest-all-{stamp}.md")
    json.dump(res, open(jp, "w"), indent=1, default=str); df.to_csv(os.path.join(a.out, f"trades-{stamp}.csv"), index=False)
    f = lambda v: "–" if v is None else (f"{v:+.3f}" if isinstance(v, float) else str(v))
    L = [f"# All-strategy backtest {stamp}", "", f"Window: last {a.days} days (since {t0:%Y-%m-%d}). Crypto: {len(syms)} top coins; forex: {len(fx)} pairs. "
         f"BTC season now: **{res['btc_season_now']}**. Net R after costs. Runtime {res['runtime_s']}s, peak RSS {res['max_rss_mb']} MB main / {res['max_rss_worker_mb']} MB per worker.", "",
         "## Totals", "", "|Strategy|Status|Trades|Win%|Net R|R/trade|", "|-|-|-|-|-|-|"]
    for k, v in res["strategies"].items():
        t = v["total"]; L.append(f"|{k}|{v['label']}|{t['n']}|{'–' if t['win'] is None else t['win']}|{t['net_r']:+.2f}|{f(t['r_per_trade'])}|")
    months = sorted(df.month.unique()) if len(df) else []
    L += ["", "## Net R per month (trades)", "", "|Strategy|" + "|".join(months) + "|", "|-|" + "-|"*len(months)]
    for k, v in res["strategies"].items():
        L.append(f"|{k}|" + "|".join(f"{v['by_month'][m]['net_r']:+.1f} ({v['by_month'][m]['n']})" if m in v["by_month"] else "–" for m in months) + "|")
    L += ["", "## By market season (net R, trades, win%)", "", "|Strategy|bull|bear|range|", "|-|-|-|-|"]
    for k, v in res["strategies"].items():
        L.append(f"|{k}|" + "|".join(f"{v['by_season'][s]['net_r']:+.1f} ({v['by_season'][s]['n']}, {v['by_season'][s]['win']}%)" if s in v["by_season"] else "–" for s in ("bull", "bear", "range")) + "|")
    L += ["", "Notes: replays the live functions; DON20 open positions marked to market; MF-REJ dynamic strong pair not replayed; "
          "per-scan caps (PAT/BRK 3, MF 4) not applied. " + __doc__.split("Seasons:")[1].strip()]
    open(mp, "w").write("\n".join(L) + "\n")
    print("\n".join(L[:20 + len(SG.STATUS)]), flush=True); print(f"[bt_all] wrote {mp} and {jp} in {res['runtime_s']}s, peak RSS {res['max_rss_mb']} MB main / {res['max_rss_worker_mb']} MB per worker", flush=True)
    if not a.no_telegram:
        from . import telegram
        if telegram.enabled():
            print(f"[bt_all] telegram bot: @{telegram.token_shape().get('bot_username')}", flush=True)   # username only
            T2 = [f"🧪 <b>Monthly backtest – all strategies</b>", f"<i>last {a.days} days · {len(syms)} coins · {len(fx)} FX pairs · BTC season: {res['btc_season_now']}</i>", "━━━━━━━━━━━━"]
            for k, v in res["strategies"].items():
                t = v["total"]
                if not t["n"]: T2.append(f"{v['label'].split()[0]} <b>{k}</b>: no trades"); continue
                best = max(v["by_season"].items(), key=lambda kv: kv[1]["net_r"])[0] if v["by_season"] else "–"
                T2.append(f"{v['label'].split()[0]} <b>{k}</b>: {t['n']} tr · win {t['win']}% · {'🟩' if t['net_r'] > 0 else '🟥'} {t['net_r']:+.1f}R ({t['r_per_trade']:+.2f}/tr) · best: {best}")
            T2.append(f"\n📄 {mp}")
            telegram.send_long("\n".join(T2), html=True)
if __name__ == "__main__": main()
