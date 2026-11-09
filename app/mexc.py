"""MEXC USDT-M perpetual futures REST client (auto-trade add-on only; the signal bot never imports this).

Official docs (checked 2026-11-09): https://www.mexc.com/api-docs/futures/integration-guide
  * Base URL https://api.mexc.com (changed 2026-01-19; contract.mexc.com still serves public data).
  * Futures order placement via API reopened 2026-03-31 after the 2022-07-25 maintenance: any KYC-verified account can
    create a key with the "Order Placing" permission (Innovation Zone pairs excluded; region rules apply).
  * Private auth headers: ApiKey, Request-Time (ms), Signature = hex(HMAC_SHA256(secret, apiKey + reqTime + paramString)),
    Recv-Window (optional, <= 60). paramString: GET = business params sorted by key, joined k=v with '&'; POST = the exact
    JSON body string. Null params are not sent and not signed.
  * Order create: POST /api/v1/private/order/create, 4 req / 2 s, side 1 open long / 2 close short / 3 open short / 4 close long,
    type 1 limit / 5 market, openType 1 isolated, vol = number of contracts (contractSize base units each).
Keys come from the environment only (MEXC_API_KEY / MEXC_API_SECRET); they are never logged, returned or stored."""
import hashlib, hmac, json, os, threading, time
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from urllib.parse import urlencode
import requests

BASE = os.getenv("MEXC_BASE", "https://api.mexc.com")

class MexcError(Exception):
    def __init__(self, code, msg, http=None):
        super().__init__(f"MEXC {code}: {msg}"); self.code = code; self.msg = msg; self.http = http
class RateLimited(MexcError): pass
class Skip(Exception):
    """A signal that can't be traded (reason in str(e)); not an error."""

def key_present():
    return bool(os.getenv("MEXC_API_KEY", "").strip() and os.getenv("MEXC_API_SECRET", "").strip())

def symbol_of(binance_symbol):
    """BTCUSDT -> BTC_USDT (MEXC contract name)."""
    s = str(binance_symbol).upper()
    return s[:-4] + "_USDT" if s.endswith("USDT") else None

def _d(x): return Decimal(str(x))
def round_price(p, c, mode=ROUND_HALF_UP):
    """Round a price to the contract tick (priceUnit) and priceScale."""
    sc = int(c.get("priceScale") if c.get("priceScale") is not None else 8)
    unit = _d(c.get("priceUnit") or 0) or Decimal(1).scaleb(-sc)
    q = (_d(p) / unit).quantize(Decimal(1), rounding=mode) * unit
    return float(q.quantize(Decimal(1).scaleb(-sc), rounding=ROUND_HALF_UP))
def floor_vol(v, c):
    """Round a contract quantity DOWN to the volume step (volUnit / volScale)."""
    unit = _d(c.get("volUnit") or 1)
    q = (_d(v) / unit).quantize(Decimal(1), rounding=ROUND_FLOOR) * unit
    return float(q.quantize(Decimal(1).scaleb(-int(c.get("volScale") or 0)), rounding=ROUND_FLOOR))

def size(c, entry, sl, risk_usdt, max_notional=0.0, lev_cap=5):
    """Position size from the stop distance. Returns dict(vol, qty, notional, leverage, risk, margin) or raises Skip.
    qty (base units) = risk / |entry - sl|; vol (contracts) = qty / contractSize rounded DOWN to the step (never more risk
    than asked); optional max notional caps it further. Leverage = min(cap, contract max); margin = notional / leverage."""
    entry, sl, risk_usdt = float(entry), float(sl), float(risk_usdt)
    dist = abs(entry - sl)
    if dist <= 0 or entry <= 0: raise Skip("stop distance is zero")
    cs = float(c.get("contractSize") or 0)
    if cs <= 0: raise Skip("contract size unknown")
    vol = floor_vol(risk_usdt / dist / cs, c)
    if max_notional and max_notional > 0:
        vol = min(vol, floor_vol(max_notional / (entry * cs), c))
    mn = float(c.get("minVol") or 0)
    if vol <= 0 or vol < mn:
        raise Skip(f"risk ${risk_usdt:g} is below MEXC's minimum size ({mn:g} contract = ${mn*cs*dist:.2f} risk at this stop)")
    mx = float(c.get("maxVol") or 0)
    if mx and vol > mx: vol = floor_vol(mx, c)
    lev = int(max(1, min(int(lev_cap or 1), int(c.get("maxLeverage") or lev_cap or 1))))
    notional = vol * cs * entry
    return dict(vol=vol, qty=vol * cs, notional=round(notional, 4), leverage=lev, risk=round(vol * cs * dist, 4), margin=round(notional / lev, 4))

class Client:
    """Thin REST client. `session` is injectable (tests use a mock). Private calls need MEXC_API_KEY/MEXC_API_SECRET."""
    def __init__(self, key=None, secret=None, base=None, session=None, recv_window=20, min_gap_s=0.55):
        self._k = (key if key is not None else os.getenv("MEXC_API_KEY", "")).strip()
        self._s = (secret if secret is not None else os.getenv("MEXC_API_SECRET", "")).strip()
        self.base = (base or BASE).rstrip("/"); self.http = session or requests.Session(); self.rw = recv_window
        self._gap = min_gap_s; self._last = 0.0; self._lock = threading.Lock(); self._cc = {"t": 0, "v": {}}; self._pm = None
    def __repr__(self): return f"<mexc.Client base={self.base} key={'set' if self._k else 'missing'}>"   # never the key
    @property
    def has_key(self): return bool(self._k and self._s)
    def sign(self, req_time, param_str):
        return hmac.new(self._s.encode(), (self._k + str(req_time) + param_str).encode(), hashlib.sha256).hexdigest()
    def _throttle(self):
        with self._lock:
            w = self._gap - (time.time() - self._last)
            if w > 0: time.sleep(w)
            self._last = time.time()
    def _parse(self, r):
        if r.status_code == 429: raise RateLimited(510, "rate limited (HTTP 429)", 429)
        try: j = r.json()
        except Exception: raise MexcError(r.status_code, f"non-JSON response (HTTP {r.status_code})", r.status_code)
        if isinstance(j, dict) and j.get("success") is False:
            code = j.get("code"); msg = j.get("message") or j.get("msg") or "error"
            if code in (510, 2037): raise RateLimited(code, msg, r.status_code)
            raise MexcError(code, msg, r.status_code)
        return j.get("data") if isinstance(j, dict) and "data" in j else j
    def public(self, path, params=None):
        r = self.http.get(self.base + path, params=params or None, timeout=15); return self._parse(r)
    def private(self, method, path, params=None, body=None):
        if not self.has_key: raise MexcError(401, "MEXC_API_KEY / MEXC_API_SECRET not set")
        self._throttle(); ts = str(int(time.time() * 1000))
        if method == "GET":
            p = {k: v for k, v in (params or {}).items() if v is not None}
            ps = urlencode(sorted(p.items())); url = self.base + path + ("?" + ps if ps else ""); data = None
        else:
            ps = json.dumps(body if body is not None else {}, separators=(",", ":")); url = self.base + path; data = ps
        h = {"ApiKey": self._k, "Request-Time": ts, "Signature": self.sign(ts, ps), "Content-Type": "application/json", "Recv-Window": str(self.rw)}
        r = self.http.request(method, url, headers=h, data=data, timeout=15); return self._parse(r)
    # ---- public ----
    def contracts(self, ttl=6*3600):
        if self._cc["v"] and time.time() - self._cc["t"] < ttl: return self._cc["v"]
        d = self.public("/api/v1/contract/detail") or []
        v = {x["symbol"]: x for x in d if x.get("settleCoin") == "USDT" and x.get("quoteCoin") == "USDT"}
        if v: self._cc.update(t=time.time(), v=v)
        return v or self._cc["v"]
    def contract(self, sym):
        """Tradable contract detail or raise Skip (not listed / API not allowed / not enabled)."""
        c = self.contracts().get(sym)
        if not c: raise Skip(f"{sym} is not listed on MEXC futures")
        if c.get("apiAllowed") is False: raise Skip(f"{sym} does not allow API trading")
        if int(c.get("state") or 0) != 0: raise Skip(f"{sym} is not enabled (state {c.get('state')})")
        return c
    def fair_price(self, sym):
        d = self.public(f"/api/v1/contract/fair_price/{sym}") or {}; return float(d.get("fairPrice") or 0) or None
    # ---- private ----
    def usdt_available(self):
        d = self.private("GET", "/api/v1/private/account/asset/USDT") or {}; return float(d.get("availableBalance") or 0)
    def position_mode(self):
        if self._pm is None: self._pm = int(self.private("GET", "/api/v1/private/position/position_mode") or 1)
        return self._pm   # 1 hedge, 2 one-way
    def create_order(self, **body):
        body = {k: v for k, v in body.items() if v is not None}
        d = self.private("POST", "/api/v1/private/order/create", body=body)
        return str(d.get("orderId")) if isinstance(d, dict) else str(d)
    def order_by_ext(self, sym, ext):
        try: return self.private("GET", f"/api/v1/private/order/external/{sym}/{ext}")
        except MexcError as e:
            if e.code in (2040, 2009, 404): return None
            raise
    def cancel_ext(self, sym, ext):
        d = self.private("POST", "/api/v1/private/order/cancel_with_external", body=[{"symbol": sym, "externalOid": ext}]) or []
        return d[0] if isinstance(d, list) and d else d
    def open_positions(self, sym=None):
        return self.private("GET", "/api/v1/private/position/open_positions", params={"symbol": sym}) or []
    def stop_orders(self, sym):
        d = self.private("GET", "/api/v1/private/stoporder/list/orders", params={"symbol": sym, "is_finished": 0, "page_num": 1, "page_size": 50})
        return d.get("resultList", []) if isinstance(d, dict) else (d or [])
    def place_stop(self, position_id, vol, sl=None, tp=None):
        return self.private("POST", "/api/v1/private/stoporder/place", body={k: v for k, v in dict(positionId=position_id, vol=vol,
                            stopLossPrice=sl, takeProfitPrice=tp, lossTrend=1, profitTrend=1, volType=2).items() if v is not None})
    def change_stop(self, stop_id, sl=None, tp=None):
        return self.private("POST", "/api/v1/private/stoporder/change_plan_price", body={k: v for k, v in dict(stopPlanOrderId=stop_id,
                            stopLossPrice=sl, takeProfitPrice=tp, lossTrend=1, profitTrend=1).items() if v is not None})
    def cancel_stops(self, position_id):
        return self.private("POST", "/api/v1/private/stoporder/cancel_all", body={"positionId": position_id})
