"""Download 15m Binance spot klines from data.binance.vision bulk files (public, no keys), Oct 2022 -> now, for today's
top-N USDT coins by volume (stock tokens and stablecoin-like tickers removed). Saves data/c15_<SYM>.pkl (git-ignored).
4H / 1H / 30m / 1D are resampled from 15m in the backtest (UTC, epoch-aligned = Binance's own bars)."""
import sys, os, io, zipfile, json, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from app import binance, don20
N = int(os.environ.get("NCOINS", "50")); START = pd.Timestamp("2022-10-01", tz="UTC")
SKIP = {"UUSDT", "RWUSDUSDT", "USDEUSDT", "USD1USDT", "FDUSDUSDT", "USDCUSDT", "TUSDUSDT", "EURUSDT", "XUSDUSDT", "BFUSDUSDT", "PAXGUSDT"}
B = "https://data.binance.vision/data/spot"
def get(url):
    for k in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as r: return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404: return None
        except Exception: time.sleep(1 + k)
    return None
def parse(b):
    z = zipfile.ZipFile(io.BytesIO(b)); raw = z.read(z.namelist()[0]).decode()
    rows = [l.split(",") for l in raw.splitlines() if l and l[0].isdigit()]
    d = pd.DataFrame([r[:6] for r in rows], columns="t o h l c v".split()).astype(float)
    d["t"] = d.t.where(d.t < 1e14, d.t // 1000)          # 2025+ files use microseconds
    d["t"] = pd.to_datetime(d.t, unit="ms", utc=True); return d
def one(sym):
    f = f"{HERE}/data/c15_{sym}.pkl"
    if os.path.exists(f): return sym, "cached"
    now = pd.Timestamp.now(tz="UTC"); urls = []
    for m in pd.period_range(START.tz_convert(None), now.tz_convert(None) - pd.offsets.MonthBegin(1), freq="M"):
        urls.append(f"{B}/monthly/klines/{sym}/15m/{sym}-15m-{m}.zip")
    for d in pd.date_range(now.normalize().replace(day=1).tz_convert(None), (now - pd.Timedelta("1D")).tz_convert(None), freq="D"):
        urls.append(f"{B}/daily/klines/{sym}/15m/{sym}-15m-{d:%Y-%m-%d}.zip")
    parts = [parse(b) for b in map(get, urls) if b]
    if not parts: return sym, "no data"
    m = pd.concat(parts).drop_duplicates("t").sort_values("t").reset_index(drop=True); m["ct"] = m.t + pd.Timedelta("15min")
    m = m[m.ct <= now].reset_index(drop=True); m.to_pickle(f); return sym, f"{len(m)} bars from {m.t.iloc[0]:%Y-%m-%d}"
if __name__ == "__main__":
    os.makedirs(f"{HERE}/data", exist_ok=True)
    syms = [s for s in binance.top_usdt_symbols(N + 30) if not don20.is_stock(s) and s not in SKIP][:N]
    for s in ("BTCUSDT", "ETHUSDT"):
        if s not in syms: syms.append(s)
    json.dump(syms, open(f"{HERE}/data/syms50.json", "w"))
    with ThreadPoolExecutor(6) as ex:
        for s, msg in ex.map(one, syms): print(s, msg, flush=True)
