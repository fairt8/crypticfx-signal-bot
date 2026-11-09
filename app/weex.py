"""WEEX USDT-M perpetual futures REST client (auto-trade add-on FALLBACK exchange only; the signal bot never imports this).

Official docs (checked 2026-11-09): https://www.weex.com/api-doc/products/futures/QuickStart/GeneralInformation (Futures V3)
  * Base URL https://api-contract.weex.com, paths /capi/v3/... (V2 is being sunset). Simulation: https://api-sim.weex.com.
  * Auth headers: ACCESS-KEY, ACCESS-PASSPHRASE, ACCESS-TIMESTAMP (ms, within 30 s of server time; GET /capi/v3/market/time),
    ACCESS-SIGN = base64(HMAC_SHA256(secret, timestamp + METHOD + requestPath + ("?" + queryString if any) + body)).
    GET / DELETE send params in the query string (body empty); POST sends the exact JSON body that is signed.
  * Errors: {"code": -1121, "msg": "..."} with an HTTP 4xx/5xx; order endpoints can also answer success=false + errorCode.
    HTTP 429 = rate limit (10 s ban if ignored).
  * Symbols: BTCUSDT style. GET /capi/v3/market/exchangeInfo (contractVal = quantity step in base units, minOrderSize,
    maxOrderSize, marketOpenLimitSize, pricePrecision, maxLeverage); only pairs in GET /capi/v3/market/apiTradingSymbols
    can be traded by API. Quantity is in base units. riskLimits = notional brackets (initialLeverage, maintMarginRatio).
  * Orders: POST /capi/v3/order (side BUY/SELL + positionSide LONG/SHORT, type LIMIT/MARKET, newClientOrderId <= 36,
    slTriggerPrice / tpTriggerPrice attached, reduceOnly). Get order by orderId only, so the client order id is resolved
    via /capi/v3/openOrders + /capi/v3/order/history. Cancel: DELETE /capi/v3/order?origClientOrderId=.
    TP/SL on a position: POST /capi/v3/placeTpSlOrder (closePosition=true), /capi/v3/modifyTpSlOrder, DELETE /capi/v3/algoOrder.
Keys come from the environment only (WEEX_API_KEY / WEEX_API_SECRET / WEEX_API_PASSPHRASE); never logged, returned or stored."""
import base64, hashlib, hmac, json, os, threading, time
from decimal import Decimal
from urllib.parse import urlencode
import requests

BASE = os.getenv("WEEX_BASE", "https://api-contract.weex.com")
ENV = ("WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_API_PASSPHRASE")
RATE_CODES = (429, -1059)
SERVER_CODES = (-1000, -1054)                                 # unknown error / system error, retry later
PERM_CODES = (-1051, -1052, -1053, -3236)                     # permission denied / insufficient / validation failed / API not allowed
NOT_FOUND = (-3200,)                                          # order does not exist

class WeexError(Exception):
    def __init__(self, code, msg, http=None):
        super().__init__(f"WEEX {code}: {msg}"); self.code = code; self.msg = msg; self.http = http
class RateLimited(WeexError): pass
class NoPermission(WeexError): pass

def key_present():
    return all(os.getenv(k, "").strip() for k in ENV)

def dstr(x):
    """Plain decimal string (no exponent) for prices / quantities."""
    return format(Decimal(str(x)).normalize(), "f")

def _int(code):
    try: return int(code)
    except Exception: return code

class Client:
    """Thin REST client. `session` is injectable (tests use a mock)."""
    def __init__(self, key=None, secret=None, passphrase=None, base=None, session=None, min_gap_s=0.12):
        self._k = (key if key is not None else os.getenv("WEEX_API_KEY", "")).strip()
        self._s = (secret if secret is not None else os.getenv("WEEX_API_SECRET", "")).strip()
        self._p = (passphrase if passphrase is not None else os.getenv("WEEX_API_PASSPHRASE", "")).strip()
        self.base = (base or BASE).rstrip("/"); self.http = session or requests.Session()
        self._gap = min_gap_s; self._last = 0.0; self._lock = threading.Lock(); self._ic = {"t": 0, "v": {}}; self._api = {"t": 0, "v": set()}
        self._lev = {}; self._off = None
    def __repr__(self): return f"<weex.Client base={self.base} key={'set' if self.has_key else 'missing'}>"   # never the key
    @property
    def has_key(self): return bool(self._k and self._s and self._p)
    def sign(self, ts, method, path, query="", body=""):
        msg = str(ts) + method.upper() + path + (("?" + query) if query else "") + (body or "")
        return base64.b64encode(hmac.new(self._s.encode(), msg.encode(), hashlib.sha256).digest()).decode()
    def _throttle(self):
        with self._lock:
            w = self._gap - (time.time() - self._last)
            if w > 0: time.sleep(w)
            self._last = time.time()
    def _parse(self, r):
        if r.status_code == 429: raise RateLimited(429, "rate limited (HTTP 429)", 429)
        try: j = r.json()
        except Exception:
            if r.status_code == 403: raise WeexError(403, "HTTP 403 (access denied / region)", 403)
            raise WeexError(r.status_code, f"non-JSON response (HTTP {r.status_code})", r.status_code)
        if isinstance(j, dict):
            code = j.get("code")
            if code is not None and "msg" in j and _int(code) not in (0, 200):
                code = _int(code); msg = j.get("msg") or "error"
                if code in RATE_CODES: raise RateLimited(code, msg, r.status_code)
                if code in PERM_CODES: raise NoPermission(code, msg, r.status_code)
                raise WeexError(code, msg, r.status_code)
            if j.get("success") is False:
                code = _int(j.get("errorCode") or r.status_code); msg = j.get("errorMessage") or "rejected"
                if code in RATE_CODES: raise RateLimited(code, msg, r.status_code)
                raise WeexError(code, msg, r.status_code)
        if r.status_code >= 500: raise WeexError(r.status_code, f"HTTP {r.status_code}", r.status_code)
        if r.status_code == 403: raise WeexError(403, "HTTP 403 (access denied / region)", 403)
        if r.status_code >= 400: raise WeexError(r.status_code, f"HTTP {r.status_code}", r.status_code)
        return j
    def public(self, path, params=None):
        return self._parse(self.http.get(self.base + path, params=params or None, timeout=15))
    def _now_ms(self):
        if self._off is None:
            try: self._off = int((self.public("/capi/v3/market/time") or {}).get("serverTime") or 0) - int(time.time() * 1000)
            except Exception: self._off = 0
            if abs(self._off) < 1000: self._off = 0
        return int(time.time() * 1000) + self._off
    def private(self, method, path, params=None, body=None):
        if not self.has_key: raise WeexError(401, "WEEX_API_KEY / WEEX_API_SECRET / WEEX_API_PASSPHRASE not set")
        self._throttle(); ts = str(self._now_ms()); method = method.upper()
        q = urlencode([(k, v) for k, v in (params or {}).items() if v is not None])
        data = json.dumps({k: v for k, v in (body or {}).items() if v is not None}, separators=(",", ":")) if method == "POST" else ""
        h = {"ACCESS-KEY": self._k, "ACCESS-PASSPHRASE": self._p, "ACCESS-TIMESTAMP": ts, "ACCESS-SIGN": self.sign(ts, method, path, q, data),
             "Content-Type": "application/json"}
        url = self.base + path + ("?" + q if q else "")
        return self._parse(self.http.request(method, url, headers=h, data=data or None, timeout=15))
    # ---- public ----
    def ping(self):
        return bool((self.public("/capi/v3/market/time") or {}).get("serverTime"))
    def instruments(self, ttl=6*3600):
        if self._ic["v"] and time.time() - self._ic["t"] < ttl: return self._ic["v"]
        d = self.public("/capi/v3/market/exchangeInfo") or {}
        out = {x["symbol"]: x for x in d.get("symbols") or [] if x.get("quoteAsset") == "USDT" and x.get("marginAsset") == "USDT"
               and x.get("contractType") in ("PERPETUAL", "TRADIFI_PERPETUAL")}
        if out: self._ic.update(t=time.time(), v=out)
        return out or self._ic["v"]
    def api_symbols(self, ttl=6*3600):
        if self._api["v"] and time.time() - self._api["t"] < ttl: return self._api["v"]
        v = set(self.public("/capi/v3/market/apiTradingSymbols") or [])
        if v: self._api.update(t=time.time(), v=v)
        return v or self._api["v"]
    def risk_limits(self, sym, ttl=6*3600):
        """Notional brackets (notionalCap, initialLeverage, maintMarginRatio), smallest first."""
        c = self.__dict__.setdefault("_rl", {}); h = c.get(sym)
        if h and time.time() - h[0] < ttl: return h[1]
        d = self.public("/capi/v3/market/riskLimits", dict(symbol=sym)) or []
        l = []
        for x in d if isinstance(d, list) else []:
            if x.get("symbol") == sym: l = sorted(x.get("brackets") or [], key=lambda b: float(b.get("notionalCap") or 0))
        if l: c[sym] = (time.time(), l)
        return l
    def mark_price(self, sym):
        d = self.public("/capi/v3/market/symbolPrice", dict(symbol=sym, priceType="MARK")) or {}
        return float(d.get("price") or 0) or None
    # ---- private ----
    def usdt_available(self):
        d = self.private("GET", "/capi/v3/account/balance") or []
        for a in d if isinstance(d, list) else []:
            if a.get("asset") == "USDT": return float(a.get("availableBalance") or 0)
        return 0.0
    def positions(self):
        d = self.private("GET", "/capi/v3/account/position/allPosition") or []
        return [p for p in (d if isinstance(d, list) else []) if float(p.get("size") or 0) > 0]
    def symbol_config(self, sym):
        d = self.private("GET", "/capi/v3/account/symbolConfig", params=dict(symbol=sym)) or []
        l = d if isinstance(d, list) else [d]
        return next((x for x in l if isinstance(x, dict) and x.get("symbol") == sym), l[0] if l else {})
    def set_leverage(self, sym, lev):
        lev = int(lev)
        if self._lev.get(sym) == lev: return
        mt = (self.symbol_config(sym) or {}).get("marginType") or "CROSSED"
        b = dict(symbol=sym, crossLeverage=str(lev)) if mt == "CROSSED" else dict(symbol=sym, isolatedLongLeverage=str(lev), isolatedShortLeverage=str(lev))
        self.private("POST", "/capi/v3/account/leverage", body=b); self._lev[sym] = lev
    def create_order(self, **body):
        d = self.private("POST", "/capi/v3/order", body=body) or {}
        return str(d.get("orderId") or "")
    def order_by_client(self, sym, cid):
        """No get-by-client-id endpoint: look in open orders, then the last day of order history."""
        for path, p in (("/capi/v3/openOrders", dict(symbol=sym, limit=100)),
                        ("/capi/v3/order/history", dict(symbol=sym, limit=100, startTime=self._now_ms() - 86400000))):
            d = self.private("GET", path, params=p) or []
            for o in d if isinstance(d, list) else []:
                if o.get("clientOrderId") == cid: return o
        return None
    def cancel_client(self, sym, cid):
        try: return self.private("DELETE", "/capi/v3/order", params=dict(origClientOrderId=cid))
        except WeexError as e:
            if e.code in NOT_FOUND: return None   # already filled / cancelled / never existed
            raise
    def algo_orders(self, sym):
        d = self.private("GET", "/capi/v3/openAlgoOrders", params=dict(symbol=sym)) or []
        return d if isinstance(d, list) else []
    def place_tpsl(self, sym, position_side, plan, trigger, cid):
        return self.private("POST", "/capi/v3/placeTpSlOrder", body=dict(symbol=sym, clientAlgoId=cid[:36], planType=plan, triggerPrice=dstr(trigger),
                            positionSide=position_side, closePosition=True))
    def modify_tpsl(self, algo_id, trigger):
        return self.private("POST", "/capi/v3/modifyTpSlOrder", body=dict(orderId=int(algo_id), triggerPrice=dstr(trigger)))
    def cancel_algo(self, algo_id):
        try: return self.private("DELETE", "/capi/v3/algoOrder", params=dict(orderId=int(algo_id)))
        except WeexError as e:
            if e.code in NOT_FOUND: return None
            raise
