"""Download Binance spot history for the FVG-PLAN v2 research (public market-data mirror, no keys).
Universe = today's top-30 USDT coins by 48h volume (same ranking the live bot / backtest_all use), stock tokens and
stablecoin-like tickers removed. 15m + 4h + 1d candles, ~450 days of 15m (+120d of 4h warm-up). Saved to data/ (git-ignored)."""
import sys, os, time, json, pickle
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from app import binance, don20
from app.backtest import hist_klines
DAYS = int(os.environ.get("DAYS", "450")); N = int(os.environ.get("NCOINS", "30"))
SKIP = {"UUSDT", "RWUSDUSDT", "USDEUSDT"}   # stablecoin-like (stop < 0.3% anyway)
def one(sym):
    f = f"data/{sym}.pkl"
    if os.path.exists(f): return sym, "cached"
    end = int(time.time()*1000); st = end - DAYS*86400_000
    try:
        m15 = hist_klines(sym, "15m", st, end); h4 = hist_klines(sym, "4h", st - 120*86400_000, end); d1 = hist_klines(sym, "1d", st - 300*86400_000, end)
    except Exception as e: return sym, f"err {type(e).__name__}"
    now = pd.Timestamp.now(tz="UTC"); d = tuple(x[x.ct <= now].reset_index(drop=True) for x in (h4, m15, d1))
    pickle.dump(d, open(f, "wb")); return sym, f"{len(m15)} x15m from {m15.t.iloc[0]:%Y-%m-%d}"
if __name__ == "__main__":
    syms = [s for s in binance.top_usdt_symbols(N + 20) if not don20.is_stock(s) and s not in SKIP][:N]
    for s in ("BTCUSDT", "ETHUSDT"):
        if s not in syms: syms.append(s)
    json.dump(syms, open("data/syms.json", "w"))
    with ThreadPoolExecutor(4) as ex:
        for s, msg in ex.map(one, syms): print(s, msg, flush=True)
