"""FVG 'plan' variants (creator's PDF): swing stop, and 'quick' reaction. Same data/split/costs as backtest2."""
import numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
from . import config as C, strategy, outcomes, forex
from .backtest import load_crypto, FxRank, _FxExtra, DATA
from .backtest2 import outcome
def run(args):
    sym, market, h4, m, xfn, t0 = args
    C.MIN_STOP_PCT_CRYPTO = 0; C.MIN_STOP_PCT_FOREX = 0; C.FVG_STOP = "fvg"
    h, l = m.h.values, m.l.values; c4 = h4.ct.values; seen = set(); out = []
    for j in range(400, len(m)):
        if m.t.iloc[j] < t0 or not (l[j] > h[j-2] or h[j] < l[j-2]): continue
        now = m.ct.iloc[j]; k = np.searchsorted(c4, now.to_datetime64(), side="right")
        if k < 60: continue
        try: sig = strategy.analyze(sym, market, h4.iloc[max(0,k-300):k].reset_index(drop=True), m.iloc[j-399:j+1].reset_index(drop=True), xfn(now) if xfn else None)
        except Exception: continue
        if not sig or sig["confirm_time"] in seen: continue
        seen.add(sig["confirm_time"]); fut = m.iloc[j+1:j+401]; row = dict(symbol=sym, market=market, t=sig["confirm_time"], direction=sig["direction"],
            entry=sig["entry"], score=sig["setup_score"], ttc=sig["tap_to_confirm_bars"], trend_ok=any("EMA50/EMA200 trend aligned" in w for w in sig["reasons"]))
        for tag, sl in (("fvg", sig["fvg3_sl"]), ("swing", sig["swing_sl"])):
            s = dict(sig, sl=sl); row[f"risk_{tag}"] = abs(sig["entry"]-sl)/sig["entry"]
            if row[f"risk_{tag}"] <= 0: row[f"st3_{tag}"] = "invalid"; continue
            for rr in (3, 2):
                st, r = outcome(s, fut, float(rr)); row[f"st{rr}_{tag}"] = st; row[f"r{rr}_{tag}"] = r
        out.append(row)
    return out
def main():
    from .backtest2 import main as _m
    import yfinance as yf
    t0 = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=92)
    syms = sorted({f.name.split("_")[0] for f in DATA.glob(f"*_{C.LTF}_92.pkl")})
    jobs = [(s, "crypto", *load_crypto(s, 92), None, t0) for s in syms]
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
    rows = []
    with ProcessPoolExecutor(6) as ex:
        for i, r in enumerate(ex.map(run, jobs)): rows += r; print(i+1, jobs[i][0], len(r), flush=True)
    pd.DataFrame(rows).to_csv(C.BASE/"backtest3_trades.csv", index=False); print("saved", len(rows))
if __name__ == "__main__": main()
