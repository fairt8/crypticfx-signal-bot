"""Bybit V5 USDT linear perpetual REST client (auto-trade add-on BACKUP exchange only; the signal bot never imports this).

Official docs (checked 2026-11-09): https://bybit-exchange.github.io/docs/v5/guide
  * Base URL https://api.bybit.com (api.bytick.com is the same mainnet). US / mainland-China IPs get HTTP 403.
  * Auth headers: X-BAPI-API-KEY, X-BAPI-TIMESTAMP (ms), X-BAPI-RECV-WINDOW, X-BAPI-SIGN =
    hex(HMAC_SHA256(secret, timestamp + apiKey + recvWindow + payload)); payload = the exact query string for GET,
    the exact JSON body for POST.
  * category=linear everywhere; one-way mode positionIdx 0 (hedge 1 = Buy side / 2 = Sell side); orderLinkId <= 36 chars
    is our idempotent client order id; tpslMode Full = SL/TP on the whole position; margin mode = account default.
Keys come from the environment only (BYBIT_API_KEY / BYBIT_API_SECRET); they are never logged, returned or stored."""
import hashlib, hmac, json, os, threading, time
from decimal import Decimal
from urllib.parse import urlencode
import requests

BASE = os.getenv("BYBIT_BASE", "https://api.bybit.com")
RATE_CODES = (10006, 10018, 429)
SERVER_CODES = (10000, 10016, 10019, 170007)   # server timeout / server error / service restarting / backend timeout

class BybitError(Exception):
    def __init__(self, code, msg, http=None):
        super().__init__(f"Bybit {code}: {msg}"); self.code = code; self.msg = msg; self.http = http
class RateLimited(BybitError): pass

def key_present():
    return bool(os.getenv("BYBIT_API_KEY", "").strip() and os.getenv("BYBIT_API_SECRET", "").strip())

def dstr(x):
    """Plain decimal string (no exponent) for prices / quantities."""
    d = Decimal(str(x)).normalize(); s = format(d, "f")
    return s

class Client:
    """Thin REST client. `session` is injectable (tests use a mock)."""
    def __init__(self, key=None, secret=None, base=None, session=None, recv_window=5000, min_gap_s=0.12):
        self._k = (key if key is not None else os.getenv("BYBIT_API_KEY", "")).strip()
        self._s = (secret if secret is not None else os.getenv("BYBIT_API_SECRET", "")).strip()
        self.base = (base or BASE).rstrip("/"); self.http = session or requests.Session(); self.rw = int(recv_window)
        self._gap = min_gap_s; self._last = 0.0; self._lock = threading.Lock(); self._ic = {"t": 0, "v": {}}; self._idx = {}; self._lev = {}
    def __repr__(self): return f"<bybit.Client base={self.base} key={'set' if self._k else 'missing'}>"   # never the key
    @property
    def has_key(self): return bool(self._k and self._s)
    def sign(self, ts, payload):
        return hmac.new(self._s.encode(), (str(ts) + self._k + str(self.rw) + payload).encode(), hashlib.sha256).hexdigest()
    def _throttle(self):
        with self._lock:
            w = self._gap - (time.time() - self._last)
            if w > 0: time.sleep(w)
            self._last = time.time()
    def _parse(self, r):
        if r.status_code == 429: raise RateLimited(429, "rate limited (HTTP 429)", 429)
        if r.status_code == 403: raise BybitError(403, "HTTP 403 (IP / region blocked by Bybit)", 403)
        try: j = r.json()
        except Exception: raise BybitError(r.status_code, f"non-JSON response (HTTP {r.status_code})", r.status_code)
        code = j.get("retCode") if isinstance(j, dict) else None
        if code not in (0, None):
            msg = j.get("retMsg") or "error"
            if code in RATE_CODES: raise RateLimited(code, msg, r.status_code)
            raise BybitError(code, msg, r.status_code)
        if r.status_code >= 500: raise BybitError(r.status_code, f"HTTP {r.status_code}", r.status_code)
        return j.get("result") if isinstance(j, dict) else j
    def public(self, path, params=None):
        return self._parse(self.http.get(self.base + path, params=params or None, timeout=15))
    def private(self, method, path, params=None, body=None):
        if not self.has_key: raise BybitError(401, "BYBIT_API_KEY / BYBIT_API_SECRET not set")
        self._throttle(); ts = str(int(time.time() * 1000))
        if method == "GET":
            payload = urlencode(sorted((k, v) for k, v in (params or {}).items() if v is not None))
            url = self.base + path + ("?" + payload if payload else ""); data = None
        else:
            payload = json.dumps({k: v for k, v in (body or {}).items() if v is not None}, separators=(",", ":")); url = self.base + path; data = payload
        h = {"X-BAPI-API-KEY": self._k, "X-BAPI-TIMESTAMP": ts, "X-BAPI-RECV-WINDOW": str(self.rw), "X-BAPI-SIGN": self.sign(ts, payload),
             "X-BAPI-SIGN-TYPE": "2", "Content-Type": "application/json"}
        return self._parse(self.http.request(method, url, headers=h, data=data, timeout=15))
    # ---- public ----
    def ping(self):
        d = self.public("/v5/market/time") or {}; return bool(d.get("timeSecond"))
    def instruments(self, ttl=6*3600):
        if self._ic["v"] and time.time() - self._ic["t"] < ttl: return self._ic["v"]
        out, cur = {}, None
        for _ in range(10):
            d = self.public("/v5/market/instruments-info", dict(category="linear", limit=1000, **({"cursor": cur} if cur else {}))) or {}
            for x in d.get("list") or []:
                if x.get("settleCoin") == "USDT" and x.get("quoteCoin") == "USDT" and x.get("contractType") == "LinearPerpetual": out[x["symbol"]] = x
            cur = d.get("nextPageCursor")
            if not cur: break
        if out: self._ic.update(t=time.time(), v=out)
        return out or self._ic["v"]
    def risk_limits(self, sym, ttl=6*3600):
        """Risk-limit tiers (riskLimitValue = max position value, maintenanceMargin rate, maxLeverage), smallest first."""
        c = self.__dict__.setdefault("_rl", {}); h = c.get(sym)
        if h and time.time() - h[0] < ttl: return h[1]
        d = self.public("/v5/market/risk-limit", dict(category="linear", symbol=sym)) or {}
        l = sorted([x for x in d.get("list") or [] if x.get("symbol") == sym], key=lambda x: float(x.get("riskLimitValue") or 0))
        if l: c[sym] = (time.time(), l)
        return l
    def mark_price(self, sym):
        d = self.public("/v5/market/tickers", dict(category="linear", symbol=sym)) or {}
        l = d.get("list") or []; return float(l[0].get("markPrice") or 0) or None if l else None
    # ---- private ----
    def usdt_available(self):
        d = self.private("GET", "/v5/account/wallet-balance", params=dict(accountType="UNIFIED")) or {}
        a = (d.get("list") or [{}])[0]
        v = a.get("totalAvailableBalance")
        if v not in (None, ""): return float(v)
        for c in a.get("coin") or []:
            if c.get("coin") == "USDT":
                return float(c.get("walletBalance") or 0) - float(c.get("totalPositionIM") or 0) - float(c.get("totalOrderIM") or 0)
        return 0.0
    def positions(self, sym=None):
        d = self.private("GET", "/v5/position/list", params=dict(category="linear", settleCoin=None if sym else "USDT", symbol=sym, limit=200)) or {}
        return [p for p in d.get("list") or [] if float(p.get("size") or 0) > 0]
    def set_leverage(self, sym, lev):
        if self._lev.get(sym) == int(lev): return
        try: self.private("POST", "/v5/position/set-leverage", body=dict(category="linear", symbol=sym, buyLeverage=str(int(lev)), sellLeverage=str(int(lev))))
        except BybitError as e:
            if e.code != 110043: raise   # 110043 = leverage not modified
        self._lev[sym] = int(lev)
    def create_order(self, **body):
        d = self.private("POST", "/v5/order/create", body=dict(category="linear", **body)) or {}
        return str(d.get("orderId") or "")
    def order_by_link(self, sym, link):
        for path in ("/v5/order/realtime", "/v5/order/history"):
            d = self.private("GET", path, params=dict(category="linear", symbol=sym, orderLinkId=link)) or {}
            l = d.get("list") or []
            if l: return l[0]
        return None
    def cancel_link(self, sym, link):
        try: return self.private("POST", "/v5/order/cancel", body=dict(category="linear", symbol=sym, orderLinkId=link))
        except BybitError as e:
            if e.code in (110001, 110008, 110010): return None   # not found / already done / already cancelled
            raise
    def trading_stop(self, sym, idx, sl=None, tp=None):
        try: return self.private("POST", "/v5/position/trading-stop", body=dict(category="linear", symbol=sym, tpslMode="Full", positionIdx=int(idx),
                                 stopLoss=None if sl is None else dstr(sl), takeProfit=None if tp is None else dstr(tp)))
        except BybitError as e:
            if e.code != 34040: raise   # 34040 = not modified
