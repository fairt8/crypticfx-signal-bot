"""Exchange adapters for the auto-trade add-on: MEXC (primary by default) and Bybit (backup) behind one interface.

All quantities are in the exchange's own order units (`vol`): MEXC = contracts (contractSize base units each),
Bybit = base-coin qty (contractSize 1). instrument() returns a dict that mexc.size / round_price / floor_vol understand
(contractSize, priceUnit, priceScale, volUnit, volScale, minVol, maxVol, maxLeverage, minNotional).
Normalised shapes:
  position: dict(symbol, direction 'long'|'short', size, pid, avg, open_type, idx)
  order:    dict(order_id, state 'open'|'filled'|'cancelled', filled, avg)
Failure classification (kind): 'not_sent' (connection never established), 'server' (exchange answered 5xx / maintenance /
region block: nothing executed), 'unknown' (timeout or drop after the request may have been sent), None (business reply)."""
import time
from decimal import Decimal
import requests
from . import mexc as M, bybit as B

NAMES = ("mexc", "bybit")
LABEL = {"mexc": "MEXC", "bybit": "Bybit"}

class Unavailable(Exception):
    """This exchange can't take the order right now (down / unreachable / symbol not listed). Nothing was executed on it,
    so the next exchange in the route may be tried. row_id: an autotrade row already created for the signal (reused)."""
    def __init__(self, msg, row_id=None): super().__init__(msg); self.row_id = row_id

_NOT_SENT = ("NewConnectionError", "NameResolutionError", "Failed to establish a new connection", "Connection refused", "getaddrinfo", "Name or service not known")
def kind(e):
    if isinstance(e, (M.RateLimited, B.RateLimited)): return None
    if isinstance(e, requests.exceptions.ConnectTimeout): return "not_sent"
    if isinstance(e, requests.exceptions.ConnectionError) and any(x in str(e) for x in _NOT_SENT): return "not_sent"
    if isinstance(e, (requests.exceptions.RequestException, ConnectionError, TimeoutError)): return "unknown"
    if isinstance(e, M.MexcError):
        return "server" if (e.http and int(e.http) >= 500) or e.code in M.SERVER_CODES else None
    if isinstance(e, B.BybitError):
        return "server" if (e.http and int(e.http) >= 500) or e.code in B.SERVER_CODES or e.code in (403, 10009) else None
    return None
def short(e): return f"{type(e).__name__}: {str(e)[:120]}"
def key_present(name): return M.key_present() if name == "mexc" else B.key_present()

class Base:
    name = label = ""
    def __init__(self, cl): self.cl = cl; self._h = dict(t=0.0, ok=None, why=None)
    def key_present(self): return key_present(self.name)
    def health(self): return dict(self._h)
    def healthy(self, ttl_ok=60, ttl_bad=20):
        h = self._h
        if h["ok"] is not None and time.time() - h["t"] < (ttl_ok if h["ok"] else ttl_bad): return h["ok"]
        ping = getattr(self.cl, "ping", None)
        if ping is None: h.update(t=time.time(), ok=True, why=None); return True
        try: ok = bool(ping()); h.update(t=time.time(), ok=ok, why=None if ok else "ping returned nothing")
        except Exception as e: h.update(t=time.time(), ok=False, why=short(e))
        return h["ok"]
    def mark_down(self, e): self._h.update(t=time.time(), ok=False, why=short(e) if isinstance(e, BaseException) else str(e))

class Mexc(Base):
    name, label = "mexc", "MEXC"
    def symbol_of(self, s): return M.symbol_of(s)
    def client_id(self, salt, tag, ref): return f"cfx{salt or '0'}{tag}{ref}"[:32]
    def instrument(self, sym): return self.cl.contract(sym)
    def fair_price(self, sym): return self.cl.fair_price(sym)
    def usdt_available(self): return self.cl.usdt_available()
    def positions(self):
        out = []
        for p in self.cl.open_positions() or []:
            if float(p.get("holdVol") or 0) <= 0: continue
            out.append(dict(symbol=p.get("symbol"), direction="long" if int(p.get("positionType") or 0) == 1 else "short", size=float(p.get("holdVol") or 0),
                            pid=p.get("positionId"), avg=float(p.get("holdAvgPrice") or 0) or None, open_type=int(p.get("openType") or 1), idx=None))
        return out
    def place_open(self, sym, direction, vol, price, market, leverage, sl, tp, cid):
        return self.cl.create_order(symbol=sym, price=price, vol=vol, leverage=leverage, side=1 if direction == "long" else 3, type=5 if market else 1,
                                    openType=1, externalOid=cid, stopLossPrice=sl, takeProfitPrice=tp)
    def order(self, sym, cid):
        o = self.cl.order_by_ext(sym, cid)
        if not o: return None
        st = int(o.get("state") or 0)
        return dict(order_id=str(o.get("orderId")), state="filled" if st == 3 else "cancelled" if st in (4, 5) else "open",
                    filled=float(o.get("dealVol") or 0), avg=float(o.get("dealAvgPrice") or 0) or None)
    def cancel(self, sym, cid): return self.cl.cancel_ext(sym, cid)
    def close(self, pos, vol, price, cid):
        body = dict(symbol=pos["symbol"], price=price, vol=vol, side=4 if pos["direction"] == "long" else 2, type=5,
                    openType=pos.get("open_type") or 1, positionId=pos["pid"], externalOid=cid[:32])
        if self.cl.position_mode() == 2: body["reduceOnly"] = True
        return self.cl.create_order(**body)
    def set_tpsl(self, pos, sl, tp):
        st = [o for o in self.cl.stop_orders(pos["symbol"]) if str(o.get("positionId")) == str(pos["pid"]) and int(o.get("state") or 1) == 1]
        if st: return self.cl.change_stop(st[0]["id"], sl=sl, tp=tp)
        return self.cl.place_stop(pos["pid"], pos["size"], sl=sl, tp=tp)
    def cancel_tpsl(self, pos): return self.cl.cancel_stops(pos["pid"])

def _decimals(x):
    e = Decimal(str(x)).normalize().as_tuple().exponent
    return max(0, -int(e))

class Bybit(Base):
    name, label = "bybit", "Bybit"
    def symbol_of(self, s):
        s = str(s).upper(); return s if s.endswith("USDT") else None
    def client_id(self, salt, tag, ref): return f"cfx{salt or '0'}b{tag}{ref}"[:36]
    def instrument(self, sym):
        x = (self.cl.instruments() or {}).get(sym)
        if not x: raise M.NotListed(f"{sym} is not listed on Bybit USDT perpetuals")
        if x.get("status") != "Trading": raise M.NotListed(f"{sym} is not trading on Bybit (status {x.get('status')})")
        pf, lf, lv = x.get("priceFilter") or {}, x.get("lotSizeFilter") or {}, x.get("leverageFilter") or {}
        step = lf.get("qtyStep") or "1"; tick = pf.get("tickSize") or "0.0001"
        return dict(symbol=sym, _ex="Bybit", contractSize=1, priceUnit=float(tick), priceScale=int(x.get("priceScale") or _decimals(tick)),
                    volUnit=float(step), volScale=_decimals(step), minVol=float(lf.get("minOrderQty") or 0),
                    maxVol=float(lf.get("maxMktOrderQty") or lf.get("maxOrderQty") or 0), maxLeverage=float(lv.get("maxLeverage") or 1),
                    minNotional=float(lf.get("minNotionalValue") or 0))
    def fair_price(self, sym): return self.cl.mark_price(sym)
    def usdt_available(self): return self.cl.usdt_available()
    def positions(self):
        out = []
        for p in self.cl.positions() or []:
            sd = p.get("side")
            if sd not in ("Buy", "Sell") or float(p.get("size") or 0) <= 0: continue
            idx = int(p.get("positionIdx") or 0)
            out.append(dict(symbol=p.get("symbol"), direction="long" if sd == "Buy" else "short", size=float(p["size"]), pid=f"{p.get('symbol')}:{idx}",
                            avg=float(p.get("avgPrice") or 0) or None, open_type=int(p.get("tradeMode") or 0), idx=idx))
        return out
    def _idx(self, direction):
        hedge = self.cl._idx.get("hedge") if hasattr(self.cl, "_idx") else False
        return (1 if direction == "long" else 2) if hedge else 0
    def place_open(self, sym, direction, vol, price, market, leverage, sl, tp, cid):
        self.cl.set_leverage(sym, leverage)
        def body():
            b = dict(symbol=sym, side="Buy" if direction == "long" else "Sell", orderType="Market" if market else "Limit", qty=B.dstr(vol),
                     timeInForce="IOC" if market else "GTC", positionIdx=self._idx(direction), orderLinkId=cid[:36], reduceOnly=False)
            if not market: b["price"] = B.dstr(price)
            if sl or tp: b.update(tpslMode="Full", stopLoss=B.dstr(sl) if sl else None, takeProfit=B.dstr(tp) if tp else None)
            return b
        try: return self.cl.create_order(**body())
        except B.BybitError as e:   # account in hedge mode: a definitive rejection, so retrying with the hedge index is safe
            if e.code == 10001 and "position idx" in str(e.msg).lower() and hasattr(self.cl, "_idx") and not self.cl._idx.get("hedge"):
                self.cl._idx["hedge"] = True; return self.cl.create_order(**body())
            raise
    def order(self, sym, cid):
        o = self.cl.order_by_link(sym, cid[:36])
        if not o: return None
        st = o.get("orderStatus")
        state = "filled" if st == "Filled" else "cancelled" if st in ("Cancelled", "Rejected", "Deactivated", "PartiallyFilledCanceled") else "open"
        return dict(order_id=str(o.get("orderId")), state=state, filled=float(o.get("cumExecQty") or 0), avg=float(o.get("avgPrice") or 0) or None)
    def cancel(self, sym, cid): return self.cl.cancel_link(sym, cid[:36])
    def close(self, pos, vol, price, cid):
        return self.cl.create_order(symbol=pos["symbol"], side="Sell" if pos["direction"] == "long" else "Buy", orderType="Market", qty=B.dstr(vol),
                                    timeInForce="IOC", positionIdx=int(pos.get("idx") or 0), orderLinkId=cid[:36], reduceOnly=True)
    def set_tpsl(self, pos, sl, tp): return self.cl.trading_stop(pos["symbol"], pos.get("idx") or 0, sl=sl, tp=tp)
    def cancel_tpsl(self, pos): return self.cl.trading_stop(pos["symbol"], pos.get("idx") or 0, sl=0, tp=0)

CLS = {"mexc": Mexc, "bybit": Bybit}
def wrap(name, x):
    return x if isinstance(x, Base) else CLS[name](x)
