"""Exchange adapters for the auto-trade add-on: MEXC and WEEX behind one interface (order chosen by the `exchanges` setting).

All quantities are in the exchange's own order units (`vol`): MEXC = contracts (contractSize base units each),
WEEX = base-coin qty (contractSize 1). instrument() returns a dict that mexc.size / round_price / floor_vol understand
(contractSize, priceUnit, priceScale, volUnit, volScale, minVol, maxVol, maxLeverage, minNotional).
Normalised shapes:
  position: dict(symbol, direction 'long'|'short', size, pid, avg, open_type, idx)
  order:    dict(order_id, state 'open'|'filled'|'cancelled', filled, avg)
Failure classification (kind): 'not_sent' (connection never established), 'server' (exchange answered 5xx / maintenance /
region block: nothing executed), 'unknown' (timeout or drop after the request may have been sent), None (business reply)."""
import time
from decimal import Decimal
import requests
from . import mexc as M, weex as W

NAMES = ("mexc", "weex")            # supported exchanges; the route order comes from settings["exchanges"]
LABEL = {"mexc": "MEXC", "weex": "WEEX"}

class Unavailable(Exception):
    """This exchange can't take the order right now (down / unreachable / symbol not listed). Nothing was executed on it,
    so the next exchange in the route may be tried. row_id: an autotrade row already created for the signal (reused)."""
    def __init__(self, msg, row_id=None): super().__init__(msg); self.row_id = row_id

_NOT_SENT = ("NewConnectionError", "NameResolutionError", "Failed to establish a new connection", "Connection refused", "getaddrinfo", "Name or service not known")
def kind(e):
    if isinstance(e, (M.RateLimited, W.RateLimited)): return None
    if isinstance(e, requests.exceptions.ConnectTimeout): return "not_sent"
    if isinstance(e, requests.exceptions.ConnectionError) and any(x in str(e) for x in _NOT_SENT): return "not_sent"
    if isinstance(e, (requests.exceptions.RequestException, ConnectionError, TimeoutError)): return "unknown"
    if isinstance(e, M.MexcError):
        return "server" if (e.http and int(e.http) >= 500) or e.code in M.SERVER_CODES else None
    if isinstance(e, W.WeexError):
        return "server" if (e.http and int(e.http) >= 500) or e.code in W.SERVER_CODES or e.code == 403 else None
    return None
def short(e): return f"{type(e).__name__}: {str(e)[:120]}"
def key_present(name): return M.key_present() if name == "mexc" else W.key_present() if name == "weex" else False

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

DEFAULT_MMR = 0.005
def liq_price(ref, lev, mmr, direction):
    """Estimated isolated-margin liquidation price (ignores fees / funding)."""
    return ref * (1 - 1 / lev + mmr) if direction == "long" else ref * (1 + 1 / lev - mmr)
def liq_inside(ref, sl, lev, mmr, direction):
    lp = liq_price(ref, lev, mmr, direction)
    return lp >= sl if direction == "long" else lp <= sl
def choose_leverage(ad, sym, c, vol, notional, ref, sl, direction, mode="cap", cap=5):
    """Leverage for an order: 'max' = the exchange's max for this size tier, 'cap' = min(cap, that max). Then the guard:
    while the estimated liquidation price is at or inside the stop, step leverage down by 1. Returns (lev, info)."""
    t = ad.tier(sym, c, vol, notional); mx = max(1, int(t["max_lev"])); mmr = float(t["mmr"])
    lev = mx if mode == "max" else max(1, min(int(cap or 1), mx)); start = lev
    while lev > 1 and liq_inside(ref, sl, lev, mmr, direction): lev -= 1
    info = dict(mode=mode, tier_max=mx, mmr=mmr, chosen=lev, liq=round(liq_price(ref, lev, mmr, direction), 10))
    if lev != start: info["stepped_from"] = start
    return lev, info

class Mexc(Base):
    name, label = "mexc", "MEXC"
    def tier(self, sym, c, vol, notional):
        """MEXC risk tiers BY_VOLUME: level n = ceil((vol - riskBaseVol) / riskIncrVol); imr/mmr grow by riskIncrImr/Mmr per level."""
        mx = float(c.get("maxLeverage") or 1); imr0 = float(c.get("initialMarginRate") or 0); mmr0 = float(c.get("maintenanceMarginRate") or DEFAULT_MMR)
        base, incr = float(c.get("riskBaseVol") or 0), float(c.get("riskIncrVol") or 0); n = 0
        if base and incr and vol > base:
            import math; n = min(int(math.ceil((vol - base) / incr)), max(0, int(c.get("riskLevelLimit") or 1) - 1))
        imr = imr0 + n * float(c.get("riskIncrImr") or 0); mmr = mmr0 + n * float(c.get("riskIncrMmr") or 0)
        if imr > 0: mx = min(mx, int(1 / imr + 1e-9))
        return dict(max_lev=max(1, int(mx)), mmr=mmr)
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

class Weex(Base):
    """WEEX V3 USDT-M perpetuals. vol = base-coin quantity (step contractVal), positionSide LONG/SHORT on every order
    (works in combined and separated position mode), account-default margin mode, leverage set per symbol,
    SL/TP attached to the opening order (slTriggerPrice / tpTriggerPrice), amended via the TP/SL conditional orders."""
    name, label = "weex", "WEEX"
    def symbol_of(self, s):
        s = str(s).upper(); return s if s.endswith("USDT") else None
    def client_id(self, salt, tag, ref): return f"cfx{salt or '0'}w{tag}{ref}"[:36]
    def instrument(self, sym):
        x = (self.cl.instruments() or {}).get(sym)
        if not x: raise M.NotListed(f"{sym} is not listed on WEEX USDT perpetuals")
        api = self.cl.api_symbols() if hasattr(self.cl, "api_symbols") else None
        if api is not None and sym not in api: raise M.NotListed(f"{sym} is not API-tradable on WEEX")
        step = Decimal(str(x.get("contractVal") or 0)) or Decimal(1).scaleb(-max(0, int(x.get("quantityPrecision") or 0)))
        pp = int(x.get("pricePrecision") if x.get("pricePrecision") is not None else 4)
        mx = [float(v) for v in (x.get("maxOrderSize"), x.get("marketOpenLimitSize")) if v not in (None, "", 0, "0")]
        return dict(symbol=sym, _ex="WEEX", contractSize=1, priceUnit=float(Decimal(1).scaleb(-pp)), priceScale=pp,
                    volUnit=float(step), volScale=_decimals(step), minVol=float(x.get("minOrderSize") or step),
                    maxVol=min(mx) if mx else 0.0, maxLeverage=float(x.get("maxLeverage") or 1), minNotional=0.0)
    def tier(self, sym, c, vol, notional):
        """WEEX notional bracket for this position value (notionalCap >= notional), else the instrument max."""
        rl = getattr(self.cl, "risk_limits", None); tiers = []
        try: tiers = rl(sym) if rl else []
        except Exception: tiers = []
        def t2(t): return dict(max_lev=max(1, int(float(t.get("initialLeverage") or 1))), mmr=float(t.get("maintMarginRatio") or DEFAULT_MMR))
        for t in tiers:
            if float(t.get("notionalCap") or 0) >= float(notional): return t2(t)
        if tiers: return t2(tiers[-1])
        return dict(max_lev=max(1, int(float(c.get("maxLeverage") or 1))), mmr=DEFAULT_MMR)
    def fair_price(self, sym): return self.cl.mark_price(sym)
    def usdt_available(self): return self.cl.usdt_available()
    def positions(self):
        out = []
        for p in self.cl.positions() or []:
            sd = str(p.get("side") or "").upper(); sz = float(p.get("size") or 0)
            if sd not in ("LONG", "SHORT") or sz <= 0: continue
            ov = float(p.get("openValue") or 0)
            out.append(dict(symbol=p.get("symbol"), direction="long" if sd == "LONG" else "short", size=sz, pid=str(p.get("id") or f"{p.get('symbol')}:{sd}"),
                            avg=(ov / sz) if ov and sz else None, open_type=p.get("marginType"), idx=sd))
        return out
    def place_open(self, sym, direction, vol, price, market, leverage, sl, tp, cid):
        self.cl.set_leverage(sym, leverage); ps = "LONG" if direction == "long" else "SHORT"
        b = dict(symbol=sym, side="BUY" if direction == "long" else "SELL", positionSide=ps, type="MARKET" if market else "LIMIT",
                 quantity=W.dstr(vol), newClientOrderId=cid[:36], reduceOnly=False)
        if not market: b.update(price=W.dstr(price), timeInForce="GTC")
        if sl: b.update(slTriggerPrice=W.dstr(sl), SlWorkingType="MARK_PRICE")
        if tp: b.update(tpTriggerPrice=W.dstr(tp), TpWorkingType="CONTRACT_PRICE")
        return self.cl.create_order(**b)
    def order(self, sym, cid):
        o = self.cl.order_by_client(sym, cid[:36])
        if not o: return None
        st = str(o.get("status") or "").upper()
        return dict(order_id=str(o.get("orderId")), state="filled" if st == "FILLED" else "cancelled" if st in ("CANCELED", "CANCELLED", "REJECTED", "EXPIRED") else "open",
                    filled=float(o.get("executedQty") or 0), avg=float(o.get("avgPrice") or 0) or None)
    def cancel(self, sym, cid): return self.cl.cancel_client(sym, cid[:36])
    def close(self, pos, vol, price, cid):
        ps = "LONG" if pos["direction"] == "long" else "SHORT"
        return self.cl.create_order(symbol=pos["symbol"], side="SELL" if ps == "LONG" else "BUY", positionSide=ps, type="MARKET",
                                    quantity=W.dstr(vol), newClientOrderId=cid[:36], reduceOnly=True)
    def _algos(self, pos):
        ps = "LONG" if pos["direction"] == "long" else "SHORT"; out = {"sl": [], "tp": []}
        for o in self.cl.algo_orders(pos["symbol"]) or []:
            if str(o.get("positionSide") or "").upper() != ps or str(o.get("algoStatus") or "NEW").upper() not in ("NEW", "UNTRIGGERED", "PENDING"): continue
            ot = str(o.get("orderType") or "").upper()
            if not (o.get("reduceOnly") or o.get("closePosition")) or "TRAILING" in ot: continue
            k = "tp" if ot.startswith("TAKE_PROFIT") else "sl" if ot.startswith("STOP") else None
            if k: out[k].append(o)
        return ps, out
    def set_tpsl(self, pos, sl, tp):
        ps, al = self._algos(pos)
        for k, px, plan in (("sl", sl, "STOP_LOSS"), ("tp", tp, "TAKE_PROFIT")):
            if not px: continue
            if al.get(k): self.cl.modify_tpsl(al[k][0]["algoId"], px)
            else: self.cl.place_tpsl(pos["symbol"], ps, plan, px, f"cfx{k}{str(pos.get('pid'))[-20:]}{int(time.time()) % 100000}")
    def cancel_tpsl(self, pos):
        ps, al = self._algos(pos)
        for o in al.get("sl", []) + al.get("tp", []): self.cl.cancel_algo(o["algoId"])

CLS = {"mexc": Mexc, "weex": Weex}
def wrap(name, x):
    return x if isinstance(x, Base) else CLS[name](x)
