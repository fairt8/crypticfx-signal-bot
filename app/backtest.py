"""Walk-forward backtest reusing strategy.analyze (exact live rules + scoring) and outcomes.simulate.
Usage: python -m app.backtest [--crypto N] [--days 92] [--no-forex]"""
import os, sys, time, pickle, argparse
import pandas as pd, numpy as np
from concurrent.futures import ProcessPoolExecutor
from . import config as C, binance, forex, strategy, outcomes
DATA = C.BASE / "bt_data"; DATA.mkdir(exist_ok=True)
COST = {"crypto": 0.001, "forex": 0.0002, "metal": 0.0005}  # round-trip fee+spread as fraction of price (assumption)

def hist_klines(sym, interval, start_ms, end_ms):
    out = []; s = start_ms
    while s < end_ms:
        d = binance.get("/api/v3/klines", symbol=sym, interval=interval, startTime=s, endTime=end_ms, limit=1000)
        if not d: break
        out += d; s = d[-1][0] + 1
        if len(d) < 1000: break
    df = pd.DataFrame(out, columns="t o h l c v ct qv n tb tq i".split())[["t","o","h","l","c","v","ct"]]
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    df["t"] = pd.to_datetime(df.t, unit="ms", utc=True); df["ct"] = pd.to_datetime(df.ct, unit="ms", utc=True) + pd.Timedelta("1ms")
    return df.drop_duplicates("t").reset_index(drop=True)

def load_crypto(sym, days):
    f = DATA / f"{sym}_{C.LTF}_{days}.pkl"
    if f.exists(): return pickle.load(open(f, "rb"))
    end = int(time.time()*1000); st5 = end - days*86400_000; st4 = st5 - 60*86400_000
    d = (hist_klines(sym, "4h", st4, end), hist_klines(sym, C.LTF, st5 - 2*86400_000, end))
    d = tuple(x[x.ct <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True) for x in d)
    pickle.dump(d, open(f, "wb")); return d

def run_symbol(args):
    sym, market, h4, m5, extra_fn, t_start = args
    h, l = m5.h.values, m5.l.values; seen = set(); trades = []
    c4 = h4.ct.values; px = m5.c.values
    for j in range(400, len(m5)):
        if m5.t.iloc[j] < t_start: continue
        if not (l[j] > h[j-2] or h[j] < l[j-2]): continue          # only bars where a 5m FVG completes can confirm
        now = m5.ct.iloc[j]
        k = np.searchsorted(c4, now.to_datetime64(), side="right")
        if k < 60: continue
        extra = extra_fn(now) if extra_fn else None
        try: sig = strategy.analyze(sym, market, h4.iloc[max(0,k-300):k].reset_index(drop=True), m5.iloc[j-399:j+1].reset_index(drop=True), extra)
        except Exception: continue
        if not sig or sig["confirm_time"] in seen: continue
        seen.add(sig["confirm_time"])
        st, filled, closed, r = outcomes.simulate(sig, m5.iloc[j+1:j+1+400])   # 400 LTF bars horizon (100h at 15m)
        risk_pct = abs(sig["entry"]-sig["sl"])/sig["entry"]
        kind = "metal" if sym in ("XAUUSD","XAGUSD") else market
        cost_r = COST[kind]/risk_pct if risk_pct > 0 else 0
        trades.append(dict(symbol=sym, market=market, direction=sig["direction"], confidence=sig["confidence"],
            in_session=sig["in_session"], confirm_time=sig["confirm_time"], status=st, gross_r=r,
            net_r=(r - cost_r) if r is not None else None, risk_pct=risk_pct, hour=now.hour,
            reasons="|".join(sig["reasons"])))
    return trades

class FxRank:
    """Rebuild the live currency-strength ranking at each hour from hourly closes (approximation of the 5m-based live calc)."""
    def __init__(self, h1): self.h1 = h1; self.cache = {}
    def __call__(self, now):
        key = now.floor("h")
        if key not in self.cache:
            d = {p: (None, df[df.t <= key].tail(30)) for p, df in self.h1.items()}
            d = {p: v for p, v in d.items() if len(v[1]) >= 25}
            rows, _, _ = forex.rank_pairs(d, key.to_pydatetime()) if d else ([], 0, 0)
            self.cache[key] = {r["pair"]: r for r in rows}
        return self.cache[key]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--crypto", type=int, default=40); ap.add_argument("--days", type=int, default=92)
    ap.add_argument("--no-forex", action="store_true"); ap.add_argument("--workers", type=int, default=6); a = ap.parse_args()
    t_start = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=a.days)
    syms = binance.top_usdt_symbols(a.crypto)
    for s in ("BTCUSDT","ETHUSDT"):
        if s not in syms: syms.append(s)
    jobs = []
    for s in syms:
        try: h4, m5 = load_crypto(s, a.days); jobs.append((s, "crypto", h4, m5, None, t_start))
        except Exception as e: print("skip", s, e)
    print("crypto symbols:", len(jobs), flush=True)
    fx_start = None
    if not a.no_forex:
        import yfinance as yf
        p = forex.YFinanceProvider(); tk = {p.ticker(x): x for x in forex.FOREX_30}
        h1 = yf.download(list(tk), interval="1h", period="730d", group_by="ticker", progress=False, auto_adjust=False)
        m5 = yf.download(list(tk), interval=C.LTF, period="60d", group_by="ticker", progress=False, auto_adjust=False)
        h1d = {}
        for t, pair in tk.items():
            try:
                A = p._norm(h1[t]); B = p._norm(m5[t])
                h4 = A.resample("4h", origin="epoch").agg({"o":"first","h":"max","l":"min","c":"last","v":"sum"}).dropna()
                h1d[pair] = forex._finish(A, "1h"); jobs.append([pair, "forex", forex._finish(h4,"4h"), forex._finish(B,C.LTF_FREQ), None, t_start])
            except Exception as e: print("fx skip", pair, e)
        rk = FxRank(h1d)
        for j in jobs:
            if j[1] == "forex": j[4] = _FxExtra(rk, j[0]); fx_start = j[3].t.iloc[0]
        print("forex pairs:", sum(j[1]=="forex" for j in jobs), "5m from", fx_start, flush=True)
    trades = []
    with ProcessPoolExecutor(a.workers) as ex:
        for i, tr in enumerate(ex.map(run_symbol, [tuple(j) for j in jobs])):
            trades += tr; print(f"{i+1}/{len(jobs)} {jobs[i][0]}: {len(tr)} signals", flush=True)
    df = pd.DataFrame(trades); df.to_csv(C.BASE / "backtest_trades.csv", index=False)
    print("saved", len(df))

class _FxExtra:
    def __init__(self, rk, pair): self.rk, self.pair = rk, pair
    def __call__(self, now): return self.rk(now).get(self.pair)

if __name__ == "__main__": main()
