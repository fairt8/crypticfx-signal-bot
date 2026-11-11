"""OpenMarket.xyz Data API client used as a candle fallback (optional forex primary).

Official docs (https://openmarket.xyz/docs/introduction): crypto market data
through GET https://api.openmarket.xyz/v1/points, authenticated with the
X-OpenMarket-Key header. Candles are type=TRADE_SIDE_AGNOSTIC_AGG. There is no
separate quotes endpoint; /v1/markets returns lastPrice, and the latest candle
close is used as a last price.

Documented exchanges are crypto spot/derivatives plus Polymarket — not MEXC or
WEEX, and not a forex venue. Crypto fallback therefore uses Binance spot
(BINANCE, matching this bot's primary klines) and, if that series is empty,
BINANCE_FUTURES. Forex mapping (OPENMARKET_FOREX_EXCHANGE, default INTERBANK_FX)
is best-effort and off as a primary unless FOREX_PROVIDER=openmarket.

History depth follows the OpenMarket plan (Free 7 days, Basic 30, Standard 90,
Advanced 1 year), so this is a live-scan fallback, not a 3-year backtest source.
Rate limits are weight-based (Free: 10/min, burst 20, 1000/day). This module
caps calls per minute, retries 429/5xx/timeouts, and never logs the API key.

Enabled only when OPENMARKET_ENABLED=1 and OPENMARKET_API_KEY is set.
"""
import time
import logging
import requests
import pandas as pd
from . import config as C

log = logging.getLogger(__name__)
S = requests.Session()
POINTS = "/v1/points"
MARKETS = "/v1/markets"
CANDLE_TYPE = "TRADE_SIDE_AGNOSTIC_AGG"
INTERVALS = {
    "1m": ("MINUTE", 60),
    "5m": ("FIVE_MINUTES", 300),
    "15m": ("FIFTEEN_MINUTES", 900),
    "30m": ("THIRTY_MINUTES", 1800),
    "1h": ("HOUR", 3600),
    "4h": ("FOUR_HOURS", 14400),
    "1d": ("DAY", 86400),
    "1w": ("WEEK", 604800),
}
_CACHE = {}          # key -> (fetched_at, df)
_RATE = {"t": 0.0, "n": 0}
_COLS = ["t", "o", "h", "l", "c", "v", "ct"]


def enabled():
    return bool(getattr(C, "OPENMARKET_ENABLED", False) and getattr(C, "OPENMARKET_API_KEY", ""))


def clear_cache():
    _CACHE.clear(); _RATE.update(t=0.0, n=0)


def map_crypto(symbol):
    """Return (exchange, rawSymbol) for a Binance-style USDT pair such as BTCUSDT."""
    return (getattr(C, "OPENMARKET_CRYPTO_EXCHANGE", "BINANCE") or "BINANCE"), str(symbol or "").strip().upper()


def map_forex(pair):
    """Return (exchange, rawSymbol) for a compact pair such as EURUSD or XAUUSD."""
    ex = (getattr(C, "OPENMARKET_FOREX_EXCHANGE", "") or "").strip()
    return ex, str(pair or "").strip().upper().replace("/", "").replace("-", "")


def interval_spec(interval):
    spec = INTERVALS.get(interval)
    if not spec:
        raise ValueError(f"unsupported interval: {interval}")
    return spec


def _headers():
    return {"X-OpenMarket-Key": C.OPENMARKET_API_KEY}


def _rate_allow():
    now = time.time(); cap = int(getattr(C, "OPENMARKET_MAX_PER_MIN", 8) or 8)
    if now - _RATE["t"] >= 60:
        _RATE.update(t=now, n=0)
    return _RATE["n"] < max(1, cap)


def _rate_hit():
    now = time.time()
    if now - _RATE["t"] >= 60:
        _RATE.update(t=now, n=0)
    _RATE["n"] += 1


def _request(path, params, retries=3):
    """GET a JSON body. Never includes the API key in raised messages."""
    if not enabled():
        raise RuntimeError("OpenMarket disabled")
    if not _rate_allow():
        raise RuntimeError("OpenMarket per-minute cap reached")
    url = getattr(C, "OPENMARKET_BASE", "https://api.openmarket.xyz").rstrip("/") + path
    timeout = (5, float(getattr(C, "OPENMARKET_TIMEOUT_S", 15) or 15))
    last = None
    for attempt in range(max(1, retries)):
        try:
            r = S.get(url, params=params, headers=_headers(), timeout=timeout)
        except (requests.Timeout, requests.ConnectionError) as e:
            last = e
            time.sleep(min(8, 0.5 * (2 ** attempt)))
            continue
        if r.status_code == 429:
            wait = r.headers.get("Retry-After")
            try: wait = min(15, max(1, int(float(wait))))
            except (TypeError, ValueError): wait = min(15, 1 + attempt)
            time.sleep(wait); last = requests.HTTPError("OpenMarket HTTP 429"); continue
        if r.status_code >= 500:
            last = requests.HTTPError(f"OpenMarket HTTP {r.status_code}")
            time.sleep(min(8, 0.5 * (2 ** attempt))); continue
        if r.status_code >= 400:
            raise requests.HTTPError(f"OpenMarket HTTP {r.status_code}")
        _rate_hit()
        try:
            return r.json()
        except ValueError as e:
            raise RuntimeError("OpenMarket returned non-JSON") from e
    raise last or RuntimeError("OpenMarket request failed")


def _ts_s(ts):
    if isinstance(ts, dict):
        return int(ts.get("s") or 0)
    if ts is None:
        return 0
    return int(ts)


def _body(pt):
    if not isinstance(pt, dict):
        return {}
    b = pt.get("Point")
    return b if isinstance(b, dict) else pt


def _num(d, *names):
    for n in names:
        if n in d and d[n] is not None:
            try: return float(d[n])
            except (TypeError, ValueError): return None
    return None


def points_to_df(payload, interval):
    """Parse a /v1/points JSON payload into the bot's closed-candle frame (t,o,h,l,c,v,ct)."""
    _, secs = interval_spec(interval)
    rows = []
    for series in (payload or {}).get("series") or []:
        for pt in series.get("points") or []:
            b = _body(pt)
            o = _num(b, "open", "o"); h = _num(b, "high", "h")
            lo = _num(b, "low", "l"); c = _num(b, "close", "c")
            if None in (o, h, lo, c):
                continue
            t = _ts_s(b.get("timestamp"))
            if t <= 0:
                continue
            v = _num(b, "volume", "v") or 0.0
            rows.append((t, o, h, lo, c, v, t + secs))
    if not rows:
        return pd.DataFrame(columns=_COLS)
    df = pd.DataFrame(rows, columns="ts o h l c v cts".split()).drop_duplicates("ts").sort_values("ts")
    df["t"] = pd.to_datetime(df.ts, unit="s", utc=True)
    df["ct"] = pd.to_datetime(df.cts, unit="s", utc=True)
    now = pd.Timestamp.now(tz="UTC")
    return df.loc[df.ct < now, _COLS].reset_index(drop=True)


def _cache_get(key):
    hit = _CACHE.get(key)
    ttl = int(getattr(C, "OPENMARKET_CACHE_S", 60) or 0)
    if hit and ttl > 0 and time.time() - hit[0] < ttl:
        return hit[1]
    return None


def _cache_put(key, df):
    _CACHE[key] = (time.time(), df)
    # bound the cache
    max_n = int(getattr(C, "CACHE_MAX_SYMBOLS", 600) or 600)
    if len(_CACHE) > max_n:
        for k, _ in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:len(_CACHE) - max_n]:
            _CACHE.pop(k, None)


def _candles(exchange, raw, interval, limit):
    if not exchange or not raw:
        return pd.DataFrame(columns=_COLS)
    _, secs = interval_spec(interval)
    limit = int(limit or 300)
    key = (exchange, raw, interval, limit)
    hit = _cache_get(key)
    if hit is not None:
        return hit.copy()
    period = max(secs, limit * secs)
    params = dict(type=CANDLE_TYPE, exchange=exchange, rawSymbol=raw, interval=INTERVALS[interval][0], period=period)
    payload = _request(POINTS, params)
    df = points_to_df(payload, interval)
    if len(df) > limit:
        df = df.iloc[-limit:].reset_index(drop=True)
    _cache_put(key, df)
    return df.copy()


def crypto_klines(symbol, interval, limit=300):
    """OHLCV for a crypto symbol. Tries the configured spot exchange, then the alt (futures)."""
    if not enabled():
        return pd.DataFrame(columns=_COLS)
    ex, raw = map_crypto(symbol)
    df = _candles(ex, raw, interval, limit)
    if len(df):
        return df
    alt = (getattr(C, "OPENMARKET_CRYPTO_EXCHANGE_ALT", "") or "").strip()
    if alt and alt != ex:
        df = _candles(alt, raw, interval, limit)
    return df


def forex_klines(pair, interval, limit=300):
    """Best-effort FX/metal OHLCV. Empty if no forex exchange is configured or the API has no such market."""
    if not enabled():
        return pd.DataFrame(columns=_COLS)
    ex, raw = map_forex(pair)
    if not ex or not raw:
        return pd.DataFrame(columns=_COLS)
    return _candles(ex, raw, interval, limit)


def last_price(exchange, raw):
    """Optional quote helper: lastPrice from /v1/markets (zero-weight discovery)."""
    if not enabled() or not exchange or not raw:
        return None
    data = _request(MARKETS, dict(exchange=exchange, symbolFilter=raw, pageSize=5))
    for m in data.get("symbols") or data.get("markets") or []:
        if str(m.get("rawSymbol") or "").upper() == raw.upper():
            return _num(m, "lastPrice", "price")
    return None
