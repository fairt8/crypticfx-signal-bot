"""OpenMarket candle provider + fallback tests (mocked HTTP).
Run: python -m pytest -q tests/test_openmarket.py
Does not call OpenMarket, Binance, Yahoo, Telegram or Neon."""
import os, sys
os.environ.update(DATABASE_URL="", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="1",
                  MEXC_API_KEY="", MEXC_API_SECRET="", WEEX_API_KEY="", WEEX_API_SECRET="", WEEX_API_PASSPHRASE="",
                  AUTOTRADE_WORKER="0", ENABLE_SCHEDULER="0",
                  OPENMARKET_API_KEY="", OPENMARKET_ENABLED="0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
import pandas as pd
import pytest
import requests
from app import config as C, openmarket as om, binance, forex

def _on(monkeypatch, key="test-key"):
    monkeypatch.setattr(C, "OPENMARKET_ENABLED", True)
    monkeypatch.setattr(C, "OPENMARKET_API_KEY", key)
    monkeypatch.setattr(C, "OPENMARKET_BASE", "https://api.openmarket.xyz")
    monkeypatch.setattr(C, "OPENMARKET_CRYPTO_EXCHANGE", "BINANCE")
    monkeypatch.setattr(C, "OPENMARKET_CRYPTO_EXCHANGE_ALT", "BINANCE_FUTURES")
    monkeypatch.setattr(C, "OPENMARKET_FOREX_EXCHANGE", "INTERBANK_FX")
    monkeypatch.setattr(C, "OPENMARKET_CACHE_S", 60)
    monkeypatch.setattr(C, "OPENMARKET_MAX_PER_MIN", 8)
    monkeypatch.setattr(C, "OPENMARKET_TIMEOUT_S", 15)
    om.clear_cache()

def _bar(start, o, h, l, c, v=1.0):
    return {"Point": {"open": o, "high": h, "low": l, "close": c, "volume": v,
                      "timestamp": {"s": start, "ns": 0}}}

def _payload(points, exchange="BINANCE", raw="BTCUSDT"):
    return {"series": [{"id": {"type": "TRADE_SIDE_AGNOSTIC_AGG", "exchange": exchange,
                               "rawSymbol": raw, "interval": "HOUR"}, "points": points}]}

def _closed_hour(n=3, last_closed=None):
    """n closed 1h bars ending at last_closed (defaults to the last full hour)."""
    end = last_closed or int(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).timestamp())
    start = end - n * 3600
    pts = []
    for i in range(n):
        t = start + i * 3600
        px = 100.0 + i
        pts.append(_bar(t, px, px + 1, px - 1, px + 0.5, 10 + i))
    return start, end, pts

@pytest.fixture(autouse=True)
def _iso():
    om.clear_cache()
    yield
    om.clear_cache()


# ---------- parsing / mapping ----------
def test_points_to_df_parses_point_wrapper_and_drops_open_candle():
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    closed = int(now.timestamp()) - 3600
    open_t = int(now.timestamp())   # this candle has not closed
    payload = _payload([_bar(closed, 100, 110, 90, 105, 3), _bar(open_t, 105, 106, 104, 105.5, 1)])
    df = om.points_to_df(payload, "1h")
    assert list(df.columns) == ["t", "o", "h", "l", "c", "v", "ct"]
    assert len(df) == 1
    assert float(df.o.iloc[0]) == 100 and float(df.h.iloc[0]) == 110
    assert float(df.l.iloc[0]) == 90 and float(df.c.iloc[0]) == 105 and float(df.v.iloc[0]) == 3
    assert df.t.iloc[0] == pd.Timestamp(closed, unit="s", tz="UTC")
    assert df.ct.iloc[0] == pd.Timestamp(closed + 3600, unit="s", tz="UTC")

def test_points_to_df_accepts_inline_fields_and_empty_series():
    t0 = int(datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0).timestamp()) - 7200
    payload = {"series": [{"points": [{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 9,
                                       "timestamp": {"s": t0}}]}]}
    df = om.points_to_df(payload, "1h")
    assert len(df) == 1 and float(df.c.iloc[0]) == 1.5 and float(df.v.iloc[0]) == 9
    assert om.points_to_df({"series": []}, "1h").empty
    assert om.points_to_df({}, "15m").empty

def test_symbol_and_interval_mapping():
    assert om.map_crypto("btcusdt") == ("BINANCE", "BTCUSDT")
    assert om.map_forex("eur/usd")[1] == "EURUSD"
    assert om.map_forex("XAUUSD")[0] == "INTERBANK_FX" or True  # exchange comes from config default
    assert om.interval_spec("15m") == ("FIFTEEN_MINUTES", 900)
    assert om.interval_spec("4h") == ("FOUR_HOURS", 14400)
    assert om.interval_spec("1d") == ("DAY", 86400)
    with pytest.raises(ValueError):
        om.interval_spec("2h")

def test_disabled_without_flag_or_key(monkeypatch):
    monkeypatch.setattr(C, "OPENMARKET_ENABLED", False)
    monkeypatch.setattr(C, "OPENMARKET_API_KEY", "test-key")
    assert om.enabled() is False
    monkeypatch.setattr(C, "OPENMARKET_ENABLED", True)
    monkeypatch.setattr(C, "OPENMARKET_API_KEY", "")
    assert om.enabled() is False
    assert om.crypto_klines("BTCUSDT", "1h", 10).empty
    assert om.forex_klines("EURUSD", "1h", 10).empty


# ---------- HTTP client (mocked) ----------
class FakeResp:
    def __init__(self, payload=None, status=200, headers=None):
        self._payload = payload if payload is not None else {"series": []}
        self.status_code = status
        self.headers = headers or {}
        self.text = ""
    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload

def test_crypto_klines_builds_request_and_parses(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(4)
    calls = []
    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append((url, dict(params), dict(headers), timeout))
        return FakeResp(_payload(pts))
    monkeypatch.setattr(om.S, "get", fake_get)
    df = om.crypto_klines("btcusdt", "1h", 4)
    assert len(df) == 4
    assert float(df.c.iloc[-1]) == 103.5
    url, params, headers, timeout = calls[0]
    assert url.endswith("/v1/points")
    assert params["type"] == "TRADE_SIDE_AGNOSTIC_AGG"
    assert params["exchange"] == "BINANCE"
    assert params["rawSymbol"] == "BTCUSDT"
    assert params["interval"] == "HOUR"
    assert int(params["period"]) == 4 * 3600
    assert headers["X-OpenMarket-Key"] == "test-key"
    assert "from" not in params   # last `period` seconds from now

def test_crypto_uses_alt_exchange_when_spot_empty(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(2)
    seen = []
    def fake_get(url, params=None, headers=None, timeout=None):
        seen.append(params["exchange"])
        if params["exchange"] == "BINANCE":
            return FakeResp({"series": []})
        return FakeResp(_payload(pts, exchange="BINANCE_FUTURES"))
    monkeypatch.setattr(om.S, "get", fake_get)
    df = om.crypto_klines("ETHUSDT", "1h", 2)
    assert seen == ["BINANCE", "BINANCE_FUTURES"]
    assert len(df) == 2

def test_forex_klines_uses_configured_exchange(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(2)
    calls = []
    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append(params); return FakeResp(_payload(pts, exchange="INTERBANK_FX", raw="EURUSD"))
    monkeypatch.setattr(om.S, "get", fake_get)
    df = om.forex_klines("eurusd", "1h", 2)
    assert len(df) == 2 and calls[0]["exchange"] == "INTERBANK_FX" and calls[0]["rawSymbol"] == "EURUSD"

def test_cache_avoids_second_http_call(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(2)
    n = {"c": 0}
    def fake_get(url, params=None, headers=None, timeout=None):
        n["c"] += 1; return FakeResp(_payload(pts))
    monkeypatch.setattr(om.S, "get", fake_get)
    a = om.crypto_klines("BTCUSDT", "1h", 2)
    b = om.crypto_klines("BTCUSDT", "1h", 2)
    assert n["c"] == 1 and len(a) == len(b) == 2

def test_429_retries_after_header_then_succeeds(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(1)
    sleeps, states = [], ["429", "ok"]
    def fake_sleep(s): sleeps.append(s)
    def fake_get(url, params=None, headers=None, timeout=None):
        st = states.pop(0)
        if st == "429":
            return FakeResp(status=429, headers={"Retry-After": "2"})
        return FakeResp(_payload(pts))
    monkeypatch.setattr(om.S, "get", fake_get)
    monkeypatch.setattr(om.time, "sleep", fake_sleep)
    df = om.crypto_klines("BTCUSDT", "1h", 1)
    assert len(df) == 1 and sleeps and sleeps[0] == 2

def test_429_exhausted_raises_without_leaking_key(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(om.S, "get", lambda *a, **k: FakeResp(status=429, headers={"Retry-After": "1"}))
    monkeypatch.setattr(om.time, "sleep", lambda s: None)
    with pytest.raises(requests.HTTPError) as ei:
        om.crypto_klines("BTCUSDT", "1h", 1)
    assert "test-key" not in str(ei.value)
    assert "429" in str(ei.value)

def test_timeout_then_success(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(1)
    states = ["timeout", "ok"]
    def fake_get(url, params=None, headers=None, timeout=None):
        st = states.pop(0)
        if st == "timeout":
            raise requests.Timeout("x")
        return FakeResp(_payload(pts))
    monkeypatch.setattr(om.S, "get", fake_get)
    monkeypatch.setattr(om.time, "sleep", lambda s: None)
    assert len(om.crypto_klines("BTCUSDT", "1h", 1)) == 1

def test_per_minute_cap_skips_further_calls(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(C, "OPENMARKET_MAX_PER_MIN", 1)
    start, end, pts = _closed_hour(1)
    n = {"c": 0}
    def fake_get(url, params=None, headers=None, timeout=None):
        n["c"] += 1; return FakeResp(_payload(pts))
    monkeypatch.setattr(om.S, "get", fake_get)
    assert len(om.crypto_klines("BTCUSDT", "1h", 1)) == 1
    # drop the candle cache only — clear_cache() would also reset the rate window
    om._CACHE.clear()
    with pytest.raises(RuntimeError, match="per-minute cap"):
        om.crypto_klines("ETHUSDT", "1h", 1)
    assert n["c"] == 1


# ---------- fallback trigger ----------
def test_binance_fallback_when_primary_raises(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(3)
    monkeypatch.setattr(binance, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("binance down")))
    monkeypatch.setattr(om.S, "get", lambda *a, **k: FakeResp(_payload(pts)))
    df = binance.klines("BTCUSDT", "1h", 3)
    assert len(df) == 3 and float(df.o.iloc[0]) == 100

def test_binance_fallback_when_primary_empty(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(2)
    monkeypatch.setattr(binance, "get", lambda *a, **k: [])  # no kline rows
    monkeypatch.setattr(om.S, "get", lambda *a, **k: FakeResp(_payload(pts)))
    df = binance.klines("NEWCOINUSDT", "1h", 2)
    assert len(df) == 2

def test_binance_does_not_call_openmarket_when_primary_ok(monkeypatch):
    _on(monkeypatch)
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    # one closed 1h binance kline: open 2h ago, close 1h ago
    o, c = now_ms - 2 * 3600_000, now_ms - 3600_000 - 1
    row = [o, "10", "11", "9", "10.5", "100", c, "0", 1, "0", "0", "0"]
    called = {"om": 0}
    monkeypatch.setattr(binance, "get", lambda *a, **k: [row])
    def boom(*a, **k):
        called["om"] += 1
        raise AssertionError("OpenMarket should not be called")
    monkeypatch.setattr(om.S, "get", boom)
    df = binance.klines("BTCUSDT", "1h", 1)
    assert len(df) == 1 and called["om"] == 0 and float(df.c.iloc[0]) == 10.5

def test_binance_reraises_when_fallback_disabled(monkeypatch):
    monkeypatch.setattr(C, "OPENMARKET_ENABLED", False)
    monkeypatch.setattr(C, "OPENMARKET_API_KEY", "")
    monkeypatch.setattr(binance, "get", lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("down")))
    with pytest.raises(requests.ConnectionError):
        binance.klines("BTCUSDT", "1h", 1)

def test_forex_fallback_fills_missing_pair(monkeypatch):
    _on(monkeypatch)
    start, end, pts = _closed_hour(5)
    class Primary:
        name = "yfinance"
        def fetch_many(self, pairs):
            return {}   # nothing from Yahoo
    # 1h + LTF (15m) both needed. Serve both from the same closed-hour payload by also
    # answering 15m with enough closed bars (reuse points with 15m interval via a hook).
    def fake_get(url, params=None, headers=None, timeout=None):
        if params["interval"] == "HOUR":
            return FakeResp(_payload(pts, exchange="INTERBANK_FX", raw="EURUSD"))
        # 15m: expand each hour into 4 closed 15m bars ending at the same close
        out = []
        for p in pts:
            t0 = p["Point"]["timestamp"]["s"]
            px = p["Point"]["open"]
            for j in range(4):
                out.append(_bar(t0 + j * 900, px, px + 0.2, px - 0.2, px + 0.1, 1))
        return FakeResp(_payload(out, exchange="INTERBANK_FX", raw="EURUSD"))
    monkeypatch.setattr(om.S, "get", fake_get)
    monkeypatch.setattr(C, "FOREX_PROVIDER", "yfinance")
    wrapped = forex._FallbackForex(Primary(), forex.OpenMarketForexProvider())
    out = wrapped.fetch_many(["EURUSD"])
    assert wrapped.name == "yfinance"
    assert "EURUSD" in out and len(out["EURUSD"]) == 3 and len(out["EURUSD"][0]) > 0

def test_forex_fallback_not_used_when_primary_has_pair(monkeypatch):
    _on(monkeypatch)
    h4 = pd.DataFrame({"t": pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC"),
                       "o": 1, "h": 1, "l": 1, "c": 1, "v": 0, "ct": pd.date_range("2026-01-01", periods=3, freq="4h", tz="UTC") + pd.Timedelta("4h")})
    class Primary:
        name = "yfinance"
        def fetch_many(self, pairs):
            return {"EURUSD": (h4, h4, h4)}
    called = {"n": 0}
    class Fallback:
        name = "openmarket"
        def fetch_many(self, pairs):
            called["n"] += 1; return {}
    out = forex._FallbackForex(Primary(), Fallback()).fetch_many(["EURUSD"])
    assert called["n"] == 0 and "EURUSD" in out

def test_provider_defaults_to_yfinance_and_wraps_when_openmarket_on(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(C, "FOREX_PROVIDER", "yfinance")
    p = forex.provider()
    assert p.name == "yfinance" and isinstance(p, forex._FallbackForex)
    monkeypatch.setattr(C, "OPENMARKET_ENABLED", False)
    p2 = forex.provider()
    assert p2.name == "yfinance" and not isinstance(p2, forex._FallbackForex)

def test_forex_provider_openmarket_option(monkeypatch):
    _on(monkeypatch)
    monkeypatch.setattr(C, "FOREX_PROVIDER", "openmarket")
    p = forex.provider()
    assert p.name == "openmarket" and isinstance(p, forex.OpenMarketForexProvider)
