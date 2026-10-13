import requests, pandas as pd
from concurrent.futures import ThreadPoolExecutor
from . import config as C
S = requests.Session()
if C.BINANCE_API_KEY: S.headers["X-MBX-APIKEY"] = C.BINANCE_API_KEY
STABLE = {"USDC","FDUSD","TUSD","BUSD","DAI","USDP","EUR","AEUR","PAX","USDS","EURI","XUSD","USD1","BFUSD","RLUSD","PAXG","WBTC","WBETH","BNSOL"}
def get(path, **p):
    r = S.get(C.BINANCE_BASE + path, params=p, timeout=20); r.raise_for_status(); return r.json()

def top_usdt_symbols(n=C.CRYPTO_TOP_N):
    """Top n USDT spot pairs by quote volume over the last 48h (rolling 2d window)."""
    info = get("/api/v3/exchangeInfo", permissions="SPOT")
    syms = [s["symbol"] for s in info["symbols"] if s["quoteAsset"]=="USDT" and s["symbol"].isascii() and s["symbol"].isalnum() and s["status"]=="TRADING"
            and s["baseAsset"] not in STABLE and not any(s["baseAsset"].endswith(x) for x in ("UP","DOWN","BULL","BEAR"))]
    # prefilter by 24h volume, then rank by true 48h rolling volume
    t24 = {t["symbol"]: float(t["quoteVolume"]) for t in get("/api/v3/ticker/24hr")}
    pre = sorted(syms, key=lambda s: -t24.get(s,0))[:min(len(syms), n+80)]
    vol = {}
    import json
    for i in range(0, len(pre), 100):
        chunk = pre[i:i+100]
        for t in get("/api/v3/ticker", symbols=json.dumps(chunk, separators=(",",":")), windowSize="2d", type="MINI"):
            vol[t["symbol"]] = float(t["quoteVolume"])
    return sorted(vol, key=lambda s: -vol[s])[:n]

def klines(symbol, interval, limit=300):
    d = get("/api/v3/klines", symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(d, columns="t o h l c v ct qv n tb tq i".split())[["t","o","h","l","c","v","ct"]]
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    df["t"] = pd.to_datetime(df.t, unit="ms", utc=True); df["ct"] = pd.to_datetime(df.ct, unit="ms", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    return df[df.ct < now].reset_index(drop=True)  # closed candles only

def fetch_pair(symbol):
    return klines(symbol, "4h", 300), klines(symbol, C.LTF, 400), (klines(symbol, "1h", 300) if C.ENABLE_CHK else None)

def fetch_many(symbols, workers=None):
    workers = workers or C.SCAN_WORKERS
    out = {}
    def f(s):
        try: return s, fetch_pair(s)
        except Exception as e: return s, None
    with ThreadPoolExecutor(workers) as ex:
        for s, r in ex.map(f, symbols):
            if r: out[s] = r
    return out
