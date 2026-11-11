import requests, pandas as pd
from concurrent.futures import ThreadPoolExecutor
from . import config as C
S = requests.Session()
if C.BINANCE_API_KEY: S.headers["X-MBX-APIKEY"] = C.BINANCE_API_KEY
STABLE = {"USDC","FDUSD","TUSD","BUSD","DAI","USDP","EUR","AEUR","PAX","USDS","EURI","XUSD","USD1","BFUSD","RLUSD","PAXG","WBTC","WBETH","BNSOL"}
def get(path, **p):
    r = S.get(C.BINANCE_BASE + path, params=p, timeout=(5, 15)); r.raise_for_status(); return r.json()

_V24 = {"t": 0, "v": {}}
def vol24(ttl=600):
    """24h quote volume (USDT) for every symbol from ONE /ticker/24hr call, cached 10 min."""
    import time
    if time.time() - _V24["t"] > ttl or not _V24["v"]:
        try: _V24["v"] = {t["symbol"]: float(t["quoteVolume"]) for t in get("/api/v3/ticker/24hr")}; _V24["t"] = time.time()
        except Exception: pass
    return _V24["v"]
def liquid(sigs, key=lambda s: (s.get("market"), s.get("symbol"))):
    """Split new signals into (kept, skipped) by the crypto liquidity floor. Forex and unknown volumes are kept (fail-open)."""
    if not C.MIN_CRYPTO_VOL_USD: return list(sigs), []
    keep, skip = [], []; v = None
    for s in sigs:
        mk, sym = key(s)
        if mk != "crypto": keep.append(s); continue
        v = v if v is not None else vol24()
        q = v.get(sym)
        (skip if q is not None and q < C.MIN_CRYPTO_VOL_USD else keep).append(s)
    return keep, [f"{key(s)[1]} {(s.get('strategy') or 'DON20') if isinstance(s, dict) else ''}".strip() for s in skip]
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

def _klines_binance(symbol, interval, limit=300):
    d = get("/api/v3/klines", symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(d, columns="t o h l c v ct qv n tb tq i".split())[["t","o","h","l","c","v","ct"]]
    df[["o","h","l","c","v"]] = df[["o","h","l","c","v"]].astype(float)
    df["t"] = pd.to_datetime(df.t, unit="ms", utc=True); df["ct"] = pd.to_datetime(df.ct, unit="ms", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    return df[df.ct < now].reset_index(drop=True)  # closed candles only

def klines(symbol, interval, limit=300):
    """Closed candles from Binance, falling back to OpenMarket when enabled and the primary fails or is empty."""
    err = None
    try:
        df = _klines_binance(symbol, interval, limit)
        if df is not None and len(df):
            return df
    except Exception as e:
        err, df = e, None
    try:
        from . import openmarket as om
        if om.enabled():
            alt = om.crypto_klines(symbol, interval, limit)
            if alt is not None and len(alt):
                print(f"[binance] {symbol} {interval}: OpenMarket fallback ({len(alt)} bars)", flush=True)
                return alt
    except Exception as e:
        print(f"[binance] {symbol} {interval}: OpenMarket fallback failed: {type(e).__name__}", flush=True)
    if err is not None:
        raise err
    return df if df is not None else _klines_binance(symbol, interval, limit)

_DAILY = {}   # symbol -> (fetched_at, df); daily candles change slowly, refresh every DAILY_REFRESH_HOURS
def daily(symbol):
    import time as _t
    hit = _DAILY.get(symbol)
    if hit and _t.time() - hit[0] < C.DAILY_REFRESH_HOURS*3600: return hit[1]
    df = klines(symbol, "1d", 200)[["t","h","l","c","ct"]]
    _DAILY[symbol] = (_t.time(), df); _trim(_DAILY, C.DAILY_REFRESH_HOURS*3600*2, C.CACHE_MAX_SYMBOLS); return df
def _trim(cache, max_age_s, max_n):
    """Bound a {key: (fetched_at, value)} cache: drop entries older than max_age_s, then the oldest beyond max_n.
    (The crypto universe churns every few hours, so without this delisted/rotated symbols stayed in RAM forever.)"""
    import time as _t
    now = _t.time()
    for k in [k for k, v in list(cache.items()) if not v or now - v[0] > max_age_s]: cache.pop(k, None)
    if len(cache) > max_n:
        for k, _ in sorted(cache.items(), key=lambda kv: kv[1][0])[:len(cache) - max_n]: cache.pop(k, None)

def fetch_pair(symbol):
    return klines(symbol, "4h", 300), klines(symbol, C.LTF, 400), (klines(symbol, "1h", 300) if C.ENABLE_CHK else None)

def fetch_many(symbols, workers=None):
    workers = workers or C.SCAN_WORKERS
    out = {}
    def f(s):
        try: return s, fetch_pair(s)
        except Exception as e: return s, None
    # bounded: no single symbol (or the whole batch) can block the scan; stragglers are abandoned
    import time as _t
    from concurrent.futures import wait
    ex = ThreadPoolExecutor(workers); futs = [ex.submit(f, s) for s in symbols]
    done, pending = wait(futs, timeout=C.FETCH_BUDGET_S)
    for fu in done:
        try:
            s, r = fu.result()
            if r: out[s] = r
        except Exception: pass
    ex.shutdown(wait=False, cancel_futures=True)
    if pending: print(f"[binance] fetch budget hit: {len(pending)} symbols skipped", flush=True)
    return out
