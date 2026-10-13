"""v2 backtest: FVG variants + Varsity checklist strategy + liquidity-sweep FVG. Reuses live strategy/outcomes code.
Writes backtest2_trades.csv; analysis in analyze_bt2.py."""
import pickle, argparse, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
from . import config as C, binance, forex, strategy, outcomes
from .backtest import load_crypto, FxRank, _FxExtra, DATA

def outcome(sig, fut, rr):
    s = dict(sig); s["rr"] = rr
    s["tp"] = s["entry"] + rr*(s["entry"]-s["sl"]) if s["direction"]=="long" else s["entry"] - rr*(s["sl"]-s["entry"])
    st, f, cl, r = outcomes.simulate(s, fut)
    return st, r

def rec(strat, sym, market, sig, fut, **kw):
    o3 = outcome(sig, fut, 3.0); o2 = outcome(sig, fut, 2.0)
    return dict(strat=strat, symbol=sym, market=market, direction=sig["direction"], t=str(sig["confirm_time"]),
        entry=sig["entry"], sl=sig["sl"], risk_pct=abs(sig["entry"]-sig["sl"])/sig["entry"],
        st3=o3[0], r3=o3[1], st2=o2[0], r2=o2[1], **kw)

# ---------- FVG (live analyze, min-stop disabled; filters applied post hoc) ----------
def fvg_trades(sym, market, h4, m, extra_fn, t0):
    C.MIN_STOP_PCT_CRYPTO = 0; C.MIN_STOP_PCT_FOREX = 0
    h, l = m.h.values, m.l.values; c4 = h4.ct.values; seen = set(); out = []
    for j in range(400, len(m)):
        if m.t.iloc[j] < t0 or not (l[j] > h[j-2] or h[j] < l[j-2]): continue
        now = m.ct.iloc[j]; k = np.searchsorted(c4, now.to_datetime64(), side="right")
        if k < 60: continue
        try: sig = strategy.analyze(sym, market, h4.iloc[max(0,k-300):k].reset_index(drop=True), m.iloc[j-399:j+1].reset_index(drop=True), extra_fn(now) if extra_fn else None)
        except Exception: continue
        if not sig or sig["confirm_time"] in seen: continue
        seen.add(sig["confirm_time"]); rs = "|".join(sig["reasons"])
        out.append(rec("FVG", sym, market, sig, m.iloc[j+1:j+401], score=sig["setup_score"], in_session=sig["in_session"],
            trend_ok="EMA50/EMA200 trend aligned" in rs, gap_pct=(sig["htf_top"]-sig["htf_bottom"])/sig["entry"]))
    return out

def trend_series(h4):
    e50, e200 = strategy.ema(h4.c,50), strategy.ema(h4.c,200)
    return pd.DataFrame({"ct": h4.ct, "up": (e50>e200)&(h4.c>e50), "dn": (e50<e200)&(h4.c<e50)})

def trend_at(ts, now):
    k = np.searchsorted(ts.ct.values, now.to_datetime64(), side="right") - 1
    return (bool(ts.up.iloc[k]), bool(ts.dn.iloc[k])) if k >= 200 else (False, False)

# ---------- Varsity Grand Checklist (1H) ----------
def chk_trades(sym, market, h4, m, t0):
    h1 = m.set_index("t").resample("1h", origin="epoch").agg({"o":"first","h":"max","l":"min","c":"last","v":"sum"}).dropna()
    h1["t"] = h1.index; h1["ct"] = h1.t + pd.Timedelta("1h"); h1 = h1.reset_index(drop=True)
    h1 = h1[h1.ct <= m.ct.iloc[-1]].reset_index(drop=True)
    ts = trend_series(h4); tr = (h1.h-h1.l).rolling(14).mean(); vs = h1.v.rolling(20).mean()
    r = strategy.rsi(h1.c); mh = strategy.macd_hist(h1.c)
    H, L = h1.h.values, h1.l.values; k = 5; out = []
    for i in range(220, len(h1)):
        if h1.t.iloc[i] < t0: continue
        now = h1.ct.iloc[i]; up, dn = trend_at(ts, now)
        if not (up or dn): continue                                   # item 4: Dow theory primary trend
        d = "long" if up else "short"; w = h1.iloc[i-2:i+1]
        b = h1.iloc[i]; body = abs(b.c-b.o); rng = max(b.h-b.l, 1e-12)
        pat = strategy.candle_pattern(h1.iloc[:i+1], d)                # item 1: recognisable candlestick pattern
        if not pat and body/rng >= 0.9 and ((b.c > b.o) == (d=="long")): pat = "marubozu"
        if not pat: continue
        if market == "crypto" and not (b.v > vs.iloc[i]): continue    # item 3: above-average volume
        # item 2: stop around S&R: pattern low near a confirmed pivot low (long) / high near pivot high (short)
        lo, hi = w.l.min(), w.h.max(); a = tr.iloc[i]
        piv = [j for j in range(i-200, i-k) if (L[j] == L[j-k:j+k+1].min() if d=="long" else H[j] == H[j-k:j+k+1].max())]
        lv = [L[j] for j in piv] if d=="long" else [H[j] for j in piv]
        ref = lo if d=="long" else hi
        dist = min([abs(ref-x)/a for x in lv], default=99)
        entry = b.c; sl = lo if d=="long" else hi
        if (entry-sl if d=="long" else sl-entry) <= 0: continue
        sig = dict(direction=d, entry=entry, sl=sl, confirm_time=now, status="open")
        ind = int((r.iloc[i] < 70 if d=="long" else r.iloc[i] > 30)) + int((mh.iloc[i] > 0) == (d=="long"))   # item 5
        fut = m[m.t >= now].iloc[:400]
        out.append(rec("CHK", sym, market, sig, fut, score=ind, sr_dist_atr=dist, pattern=pat,
            in_session=forex.in_major_session(now.to_pydatetime())))
    return out

# ---------- Liquidity sweep -> FVG (15m), from 'Liquidity + FVGs' transcript ----------
def sweep_trades(sym, market, h4, m, t0, lookbacks=(48, 96)):
    ts = trend_series(h4); H, L, Cl = m.h.values, m.l.values, m.c.values; out = []
    for lb in lookbacks:
        lastk = -99
        for i in range(lb+4, len(m)-3):
            if m.t.iloc[i] < t0 or i - lastk < 4: continue
            now = m.ct.iloc[i]; up, dn = trend_at(ts, now)
            if not (up or dn): continue                               # don't fight HTF bias [T]
            lvl = L[i-lb:i-1].min() if up else H[i-lb:i-1].max()        # liquidity = prior range extreme (prev lb bars)
            swept = (L[i] < lvl) if up else (H[i] > lvl)                # wick or close beyond the old low/high [T]
            if not swept: continue
            # first same-direction FVG whose c1 is at/after the sweep candle, within 12 bars [T: drop to LTF, look for FVG]
            for j in range(i+2, min(i+14, len(m))):
                if up and L[j] > H[j-2]: entry, ext = L[j], L[i:j+1].min(); break
                if dn and H[j] < L[j-2]: entry, ext = H[j], H[i:j+1].max(); break
            else: continue
            d = "long" if up else "short"; sl = ext                     # SL beyond the swept extreme [T]
            if (entry-sl if d=="long" else sl-entry) <= 0: continue
            ct = m.ct.iloc[j]; sig = dict(direction=d, entry=entry, sl=sl, confirm_time=ct, status="pending")
            out.append(rec("SWEEP", sym, market, sig, m.iloc[j+1:j+401], lookback=lb, score=0,
                in_session=forex.in_major_session(ct.to_pydatetime())))
            lastk = j
    return out

def run(args):
    sym, market, h4, m, xfn, t0 = args; o = []
    for f in (lambda: fvg_trades(sym, market, h4, m, xfn, t0), lambda: chk_trades(sym, market, h4, m, t0), lambda: sweep_trades(sym, market, h4, m, t0)):
        try: o += f()
        except Exception as e: print(sym, "err", e, flush=True)
    return o

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--workers", type=int, default=6); a = ap.parse_args()
    t0 = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=92)
    syms = sorted({f.name.split("_")[0] for f in DATA.glob(f"*_{C.LTF}_92.pkl")})
    jobs = [(s, "crypto", *load_crypto(s, 92), None, t0) for s in syms]
    import yfinance as yf
    p = forex.YFinanceProvider(); tk = {p.ticker(x): x for x in forex.FOREX_30}
    h1 = yf.download(list(tk), interval="1h", period="730d", group_by="ticker", progress=False, auto_adjust=False)
    mm = yf.download(list(tk), interval=C.LTF, period="60d", group_by="ticker", progress=False, auto_adjust=False)
    h1d = {}; fx = []
    for t, pair in tk.items():
        try:
            A = p._norm(h1[t]); B = p._norm(mm[t])
            h4 = A.resample("4h", origin="epoch").agg({"o":"first","h":"max","l":"min","c":"last","v":"sum"}).dropna()
            h1d[pair] = forex._finish(A, "1h"); fx.append((pair, forex._finish(h4,"4h"), forex._finish(B, C.LTF_FREQ)))
        except Exception as e: print("fx skip", pair, e)
    rk = FxRank(h1d); jobs += [(pr, "forex", h4, b, _FxExtra(rk, pr), t0) for pr, h4, b in fx]
    print("jobs", len(jobs), flush=True); trades = []
    with ProcessPoolExecutor(a.workers) as ex:
        for i, tr in enumerate(ex.map(run, jobs)): trades += tr; print(i+1, jobs[i][0], len(tr), flush=True)
    pd.DataFrame(trades).to_csv(C.BASE/"backtest2_trades.csv", index=False); print("saved", len(trades))
if __name__ == "__main__": main()
