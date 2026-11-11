"""Auto-trade add-on tests (mocked MEXC, temp SQLite). Run: python -m pytest -q tests/test_autotrade.py
Never touches Telegram, Neon or MEXC: env is blanked before the app is imported."""
import os, sys, json, hmac, hashlib, threading, time, base64
os.environ.update(DATABASE_URL="", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="1", MEXC_API_KEY="", MEXC_API_SECRET="", WEEX_API_KEY="", WEEX_API_SECRET="", WEEX_API_PASSPHRASE="", AUTOTRADE_WORKER="0", ENABLE_SCHEDULER="0", OPENMARKET_API_KEY="", OPENMARKET_ENABLED="0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import pytest
import requests
from app import config as C, db, don20, mexc as M, weex as WX, exchanges as X, autotrade as A, telegram

_WX_KEY_PRESENT = WX.key_present   # the real one (the fixture patches it)
CON = {"BTC_USDT": dict(symbol="BTC_USDT", contractSize=0.0001, priceUnit=0.1, priceScale=1, volUnit=1, volScale=0, minVol=1, maxVol=400000, maxLeverage=500, apiAllowed=True, state=0),
       "SOL_USDT": dict(symbol="SOL_USDT", contractSize=0.1, priceUnit=0.01, priceScale=2, volUnit=1, volScale=0, minVol=1, maxVol=100000, maxLeverage=200, apiAllowed=True, state=0),
       "NOAPI_USDT": dict(symbol="NOAPI_USDT", contractSize=1, priceUnit=0.0001, priceScale=4, volUnit=1, volScale=0, minVol=1, maxLeverage=20, apiAllowed=False, state=0)}

class Fake:
    """Mock MEXC client: records every call; private calls fail loudly when `private_ok` is False (dry-run must not call them)."""
    def __init__(self, private_ok=True):
        self.private_ok = private_ok; self.calls = []; self.orders = {}; self.positions = []; self.stops = []; self.fair = {}; self.fail_create = None
    def _p(self, name, *a, **k):
        if not self.private_ok: raise AssertionError(f"private MEXC call in dry-run: {name}")
        self.calls.append((name, a, k))
    def contracts(self): return CON
    def contract(self, sym): return M.Client.contract(self, sym)
    def fair_price(self, sym): return self.fair.get(sym)
    def usdt_available(self): self._p("usdt_available"); return 10000.0
    def position_mode(self): return 1
    def create_order(self, **b):
        self._p("create_order", **b)
        if self.fail_create: e = self.fail_create; self.fail_create = None; raise e
        oid = str(1000 + len(self.orders)); ext = b.get("externalOid")
        if b["side"] in (1, 3): self.orders[ext] = dict(orderId=oid, state=2 if b["type"] == 1 else 3, dealVol=0 if b["type"] == 1 else b["vol"], dealAvgPrice=b["price"], vol=b["vol"])
        return oid
    def order_by_ext(self, sym, ext): self._p("order_by_ext", sym, ext); return self.orders.get(ext)
    def cancel_ext(self, sym, ext):
        self._p("cancel_ext", sym, ext)
        if ext in self.orders: self.orders[ext]["state"] = 4
        return dict(errorCode=0)
    def open_positions(self, sym=None): self._p("open_positions"); return [p for p in self.positions if not sym or p["symbol"] == sym]
    def stop_orders(self, sym): self._p("stop_orders", sym); return [s for s in self.stops if s["symbol"] == sym]
    def place_stop(self, pid, vol, sl=None, tp=None): self._p("place_stop", pid, vol, sl=sl, tp=tp)
    def change_stop(self, sid, sl=None, tp=None):
        self._p("change_stop", sid, sl=sl, tp=tp)
        if getattr(self, "fail_change", None):
            e = self.fail_change; self.fail_change = None; raise e
    def cancel_stops(self, pid): self._p("cancel_stops", pid)
    def n(self, name): return sum(1 for c in self.calls if c[0] == name)

@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DB_PATH", str(tmp_path / "t.db"))
    db.init(); don20.init()
    A._S.update(t=0, v=None); A._TBL["ok"] = False; A._ERRSENT.clear()
    A.STATE.update(last_tick=None, last_result=None, backoff_until=0, idle_until=0); A.STATE["errors"].clear(); A.STATE["skips"].clear(); A.STATE.pop("loss_day", None)
    sent = []; monkeypatch.setattr(telegram, "send", lambda t, chat_id=None, html=False: sent.append(t) or True)
    monkeypatch.setattr(M, "key_present", lambda: False); monkeypatch.setattr(WX, "key_present", lambda: False)
    A.STATE["perm"].clear()
    yield sent

def sig(symbol="BTCUSDT", strategy="BRK", direction="long", entry=100000.0, sl=99000.0, tp=103000.0, status="pending", ct=None):
    s = dict(symbol=symbol, market="crypto", direction=direction, entry=entry, sl=sl, tp=tp, rr=3.0, confidence=50, in_session=1, reasons=["x"],
             htf_top=None, htf_bottom=None, htf_time=None, tap_time=None, confirm_time=ct or datetime.now(timezone.utc).isoformat(), price_now=entry,
             strategy=strategy, tags=[strategy], experimental=0, status=status, filled_at=datetime.now(timezone.utc).isoformat() if status == "open" else None)
    return db.insert(s)
def rows(): return A._q("SELECT * FROM autotrade ORDER BY id")
def enable(**kw):
    """Older tests run in the manual "Limit only" order type with a 15-min max wait; t160u tests pass order_type="auto"."""
    p = dict(enabled=True, strategies=["BRK"], risk_usdt=10, max_open=3, leverage=5, order_type="limit", limit_timeout_min=15); p.update(kw)
    return A.save_settings(p)
PX = lambda v: (lambda syms: {s: v for s in syms})

# ---------- sizing / precision ----------
def test_size_and_precision():
    c = CON["BTC_USDT"]
    z = M.size(c, 100000, 99000, 10)                  # 10 USDT / 1000 stop = 0.01 BTC = 100 contracts of 0.0001
    assert z["vol"] == 100 and abs(z["risk"] - 10) < 1e-9 and z["leverage"] == 5 and abs(z["margin"] - 200) < 1e-9
    assert M.size(c, 100000, 99000, 10, max_notional=500)["vol"] == 50            # 500 / (100000*0.0001)
    assert M.size(c, 100000, 99000, 10.99)["vol"] == 109                           # rounded DOWN: never more risk than asked
    with pytest.raises(M.Skip): M.size(c, 100000, 99000, 0.05)                     # below the 1-contract minimum
    with pytest.raises(M.Skip): M.size(c, 100, 100, 10)
    assert M.round_price(100000.06, c) == 100000.1 and M.round_price(1.23456, CON["SOL_USDT"]) == 1.23
    assert M.floor_vol(12.9, c) == 12 and M.size(c, 100000, 99000, 10, lev_cap=1000)["leverage"] == 500
    assert M.symbol_of("SOLUSDT") == "SOL_USDT" and M.symbol_of("EURUSD") is None

def test_signing_and_headers():
    class S:
        def __init__(s): s.req = None
        def request(s, method, url, headers=None, data=None, timeout=None):
            s.req = (method, url, headers, data)
            class R: status_code = 200; json = staticmethod(lambda: {"success": True, "code": 0, "data": {"orderId": "77", "ts": 1}})
            return R()
    se = S(); cl = M.Client(key="AK", secret="SK", session=se, min_gap_s=0)
    assert "AK" not in repr(cl) and "SK" not in repr(cl)
    assert cl.create_order(symbol="BTC_USDT", price=1.0, vol=1, side=1, type=1, openType=1, externalOid="x", stopLossPrice=None) == "77"
    method, url, h, data = se.req
    assert url.endswith("/api/v1/private/order/create") and "stopLossPrice" not in data   # nulls are not sent/signed
    assert h["Signature"] == hmac.new(b"SK", ("AK" + h["Request-Time"] + data).encode(), hashlib.sha256).hexdigest() and h["ApiKey"] == "AK"
    cl.private("GET", "/api/v1/private/stoporder/list/orders", params={"symbol": "BTC_USDT", "page_size": 50, "is_finished": 0, "page_num": 1})
    method, url, h, data = se.req
    assert url.endswith("?is_finished=0&page_num=1&page_size=50&symbol=BTC_USDT")
    assert h["Signature"] == hmac.new(b"SK", ("AK" + h["Request-Time"] + "is_finished=0&page_num=1&page_size=50&symbol=BTC_USDT").encode(), hashlib.sha256).hexdigest()
    with pytest.raises(M.MexcError): M.Client(key="", secret="").private("GET", "/x")

def test_error_and_rate_limit_parsing():
    class R:
        def __init__(s, code, j): s.status_code = code; s._j = j
        def json(s): return s._j
    cl = M.Client(key="a", secret="b")
    with pytest.raises(M.RateLimited): cl._parse(R(429, {}))
    with pytest.raises(M.RateLimited): cl._parse(R(200, {"success": False, "code": 510, "message": "freq"}))
    with pytest.raises(M.MexcError) as e: cl._parse(R(200, {"success": False, "code": 2005, "message": "Balance insufficient"}))
    assert e.value.code == 2005

# ---------- settings ----------
def test_settings_validation():
    with pytest.raises(ValueError): A.save_settings(dict(dry_run=False))          # no key -> live refused
    with pytest.raises(ValueError): A.save_settings(dict(strategies=["MF-REJ"]))  # forex not allowed
    with pytest.raises(ValueError): A.save_settings(dict(limit_timeout_min=99999))
    with pytest.raises(ValueError): A.save_settings(dict(risk_usdt=-1))
    s = A.settings(max_age=0); assert s["enabled"] is False and s["dry_run"] is True and s["strategies"] == []   # deploy defaults: OFF
    s = enable(); assert s["enabled"] and s["enabled_at"] and s["dry_run"]

# ---------- dry-run ----------
def test_dry_run_limit_lifecycle_no_private_calls(fresh):
    enable(); i = sig()
    fk = Fake(private_ok=False)
    A.tick(cl=fk, px_fn=PX(100500.0))
    r = rows()[0]; assert r["status"] == "open_order" and r["dry"] == 1 and r["vol"] == 100 and r["ext_oid"].startswith("cfx")
    A.tick(cl=fk, px_fn=PX(100500.0)); assert len(rows()) == 1                     # idempotent: one auto trade per signal
    db.update(i, status="open", filled_at=datetime.now(timezone.utc).isoformat())
    A.tick(cl=fk, px_fn=PX(100100.0)); assert rows()[0]["status"] == "filled"
    db.update(i, status="tp", closed_at=datetime.now(timezone.utc).isoformat(), result_r=3.0)
    A.tick(cl=fk, px_fn=PX(103100.0)); r = rows()[0]
    assert r["status"] == "closed" and r["exit_reason"] == "target hit" and 28.9 < r["pnl_usdt"] < 29.1   # 3R of 10 USDT minus est. 0.05%/side fees
    assert fk.calls == [] and any("DRY-RUN" in t and "filled" in t for t in fresh) and any("closed" in t for t in fresh)

def test_only_new_signals_and_enabled_strategies():
    old = sig(symbol="SOLUSDT", entry=150, sl=148, tp=156)            # before auto-trade was switched on -> ignored
    time.sleep(0.01); enable(); sig(strategy="CHK", status="open")    # CHK not enabled -> ignored
    A.tick(cl=Fake(False), px_fn=PX(100000.0)); assert rows() == []
    sig(symbol="SOLUSDT", strategy="BRK", entry=150, sl=148, tp=156)
    A.tick(cl=Fake(False), px_fn=PX(150.2)); assert [r["symbol"] for r in rows()] == ["SOLUSDT"]

def test_skip_unlisted_and_api_disallowed():
    enable(); sig(symbol="NOAPIUSDT", entry=1, sl=0.9, tp=1.3); sig(symbol="ZZZUSDT", entry=1, sl=0.9, tp=1.3)
    A.tick(cl=Fake(False), px_fn=PX(1.0)); rs = rows()
    assert {r["status"] for r in rs} == {"skipped"} and any("API" in json.loads(r["note"])["skip"] for r in rs) and any("not listed" in json.loads(r["note"])["skip"] for r in rs)

def test_max_open_and_one_per_coin():
    enable(max_open=1); sig(); sig(symbol="SOLUSDT", entry=150, sl=148, tp=156)
    A.tick(cl=Fake(False), px_fn=lambda q: {"BTCUSDT": 100500.0, "SOLUSDT": 150.5}); assert len([r for r in rows() if r["status"] != "skipped"]) == 1

def test_market_slippage_guard():
    enable(order_type="market"); sig(status="open")
    A.tick(cl=Fake(False), px_fn=PX(100800.0)); r = rows()[0]               # 0.8R away -> skipped
    assert r["status"] == "skipped" and "moved" in json.loads(r["note"])["skip"]

# ---------- live (mocked MEXC) ----------
def live(monkeypatch, **kw):
    monkeypatch.setattr(M, "key_present", lambda: True); enable(**kw); return A.save_settings(dict(dry_run=False))

def test_live_limit_timeout_cancel(monkeypatch):
    live(monkeypatch, limit_timeout_min=5); sig()
    fk = Fake(); now = datetime.now(timezone.utc)
    A.tick(cl=fk, px_fn=PX(100500.0), now=now)
    (name, _, b), = [c for c in fk.calls if c[0] == "create_order"]
    assert b["side"] == 1 and b["type"] == 1 and b["price"] == 100000.0 and b["vol"] == 100 and b["stopLossPrice"] == 99000.0 and b["takeProfitPrice"] == 103000.0 and b["openType"] == 1 and b["leverage"] == 5
    assert rows()[0]["status"] == "open_order"
    A.tick(cl=fk, px_fn=PX(100500.0), now=now + timedelta(minutes=2)); assert rows()[0]["status"] == "open_order" and fk.n("cancel_ext") == 0
    A.tick(cl=fk, px_fn=PX(100500.0), now=now + timedelta(minutes=6))
    r = rows()[0]; assert r["status"] == "cancelled" and "5 min" in r["exit_reason"] and fk.n("cancel_ext") == 1 and fk.n("create_order") == 1

def test_live_no_timeout_cancels_on_invalidation(monkeypatch):
    live(monkeypatch, limit_timeout_min=0); i = sig(); fk = Fake(); now = datetime.now(timezone.utc)
    A.tick(cl=fk, px_fn=PX(100500.0), now=now)
    A.tick(cl=fk, px_fn=PX(100500.0), now=now + timedelta(hours=3)); assert rows()[0]["status"] == "open_order"
    db.update(i, status="expired"); A.tick(cl=fk, px_fn=PX(100500.0), now=now + timedelta(hours=4))
    assert rows()[0]["status"] == "cancelled" and rows()[0]["exit_reason"] == "signal expired"

def test_live_idempotent_after_network_error(monkeypatch):
    live(monkeypatch); sig(); fk = Fake(); fk.fail_create = ConnectionError("timeout")
    A.tick(cl=fk, px_fn=PX(100500.0)); assert rows()[0]["status"] == "placing"
    ext = rows()[0]["ext_oid"]; fk.orders[ext] = dict(orderId="555", state=2, dealVol=0)   # it did reach MEXC
    A.tick(cl=fk, px_fn=PX(100500.0)); A.tick(cl=fk, px_fn=PX(100500.0))
    assert rows()[0]["status"] == "open_order" and rows()[0]["order_id"] == "555" and fk.n("create_order") == 1

def test_live_rejection_recorded(monkeypatch, fresh):
    live(monkeypatch); sig(); fk = Fake(); fk.fail_create = M.MexcError(2005, "Balance insufficient")
    A.tick(cl=fk, px_fn=PX(100500.0)); r = rows()[0]
    assert r["status"] == "error" and "2005" in json.loads(r["note"])["error"] and any("rejected" in t for t in fresh)
    A.tick(cl=fk, px_fn=PX(100500.0)); assert fk.n("create_order") == 1

def test_live_fill_exit_mirror_and_price_sanity(monkeypatch):
    live(monkeypatch, order_type="auto", strategies=["BRK", "PAT-WEDGE"]); fk = Fake(); fk.fair["BTC_USDT"] = 130000.0
    sig(status="open"); A.tick(cl=fk, px_fn=PX(100100.0))
    assert rows()[0]["status"] == "skipped" and "differs" in json.loads(rows()[0]["note"])["skip"]   # MEXC price far from Binance
    fk.fair.clear(); i = sig(symbol="SOLUSDT", strategy="PAT-WEDGE", entry=150, sl=148, tp=156, status="open")   # market-entry signal
    A.tick(cl=fk, px_fn=PX(150.1)); r = [x for x in rows() if x["symbol"] == "SOLUSDT"][0]
    assert r["status"] == "open_order" and r["order_type"] == "market"
    fk.positions = [dict(symbol="SOL_USDT", positionType=1, holdVol=r["vol"], positionId=9, openType=1, holdAvgPrice=150.1)]
    fk.stops = [dict(id=31, symbol="SOL_USDT", positionId=9, state=1)]
    A.tick(cl=fk, px_fn=PX(150.3)); assert [x for x in rows() if x["id"] == r["id"]][0]["status"] == "filled"
    db.update(i, sl=149.0, tp=153.0)                                   # bot moved stop/target
    A.tick(cl=fk, px_fn=PX(150.3)); ch = [c for c in fk.calls if c[0] == "change_stop"]
    assert ch and ch[-1][2] == dict(sl=149.0, tp=153.0)
    db.update(i, status="sl", closed_at=datetime.now(timezone.utc).isoformat(), result_r=-1.0)
    A.tick(cl=fk, px_fn=PX(148.9))
    close = [c for c in fk.calls if c[0] == "create_order" and c[2]["side"] == 4]
    assert close and close[-1][2]["type"] == 5 and close[-1][2]["positionId"] == 9
    assert [x for x in rows() if x["id"] == r["id"]][0]["status"] == "closed"

def test_live_closed_on_exchange(monkeypatch):
    live(monkeypatch, order_type="market"); sig(status="open"); fk = Fake()
    A.tick(cl=fk, px_fn=PX(100100.0)); fk.positions = [dict(symbol="BTC_USDT", positionType=1, holdVol=10, positionId=1)]
    A.tick(cl=fk, px_fn=PX(100100.0)); assert rows()[0]["status"] == "filled"
    fk.positions = []; A.tick(cl=fk, px_fn=PX(98900.0))
    r = rows()[0]; assert r["status"] == "closed" and "MEXC" in r["exit_reason"] and r["exit_price"] == 99000.0 and r["pnl_usdt"] < 0

def test_don20_trailing_and_ptp(monkeypatch):
    live(monkeypatch, order_type="market", strategies=["DON20", "CHK"]); fk = Fake()
    now = datetime.now(timezone.utc)
    with db.conn() as c:
        c.execute("INSERT INTO don20(symbol,direction,signal_day,opened_at,entry,init_stop,stop,atr,best_close,last_checked) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ("BTCUSDT", "long", now.date().isoformat(), now.isoformat(), 100000.0, 97000.0, 97000.0, 1000.0, 100000.0, now.isoformat()))
    i = sig(symbol="SOLUSDT", strategy="CHK", entry=150, sl=148, tp=156, status="open")
    A.tick(cl=fk, px_fn=lambda s: {"BTCUSDT": 100050.0, "SOLUSDT": 150.05})
    d = [c[2] for c in fk.calls if c[0] == "create_order" and c[2]["symbol"] == "BTC_USDT"][0]
    assert d["stopLossPrice"] == 97000.0 and d.get("takeProfitPrice") is None                  # DON: no target, trailing stop
    fk.positions = [dict(symbol="BTC_USDT", positionType=1, holdVol=d["vol"], positionId=5), dict(symbol="SOL_USDT", positionType=1, holdVol=50, positionId=6)]
    A.tick(cl=fk, px_fn=lambda s: {"BTCUSDT": 100050.0, "SOLUSDT": 150.05})
    with db.conn() as c: c.execute("UPDATE don20 SET stop=98000.0")
    A.tick(cl=fk, px_fn=lambda s: {"BTCUSDT": 101000.0, "SOLUSDT": 150.05})
    assert [r for r in rows() if r["source"] == "DON20"][0]["sl"] == 98000.0 and any(c[0] == "place_stop" and c[2]["sl"] == 98000.0 for c in fk.calls)
    A.tick(cl=fk, px_fn=lambda s: {"BTCUSDT": 101000.0, "SOLUSDT": 153.2})           # CHK TP1 (1.5R = 153) -> half; BE+ then locks 5% of the final TP (156)
    r = [r for r in rows() if r["strategy"] == "CHK"][0]
    fp = float(r["fill_price"]); lock = round(fp + 0.05 * (156.0 - fp), 2)          # SOL tick 0.01
    assert r["half_done"] == 1 and r["pnl_usdt"] > 0 and abs(r["sl"] - lock) < 1e-9 and json.loads(r["note"]).get("be_plus")
    assert any(c[0] == "create_order" and c[2]["side"] == 4 and c[2]["symbol"] == "SOL_USDT" for c in fk.calls)

def test_daily_loss_limit(monkeypatch, fresh):
    enable(daily_loss_usdt=5); A.ensure_table()
    A._insert(source="sig", ref_id=999, strategy="BRK", symbol="X", direction="long", status="closed", dry=1, pnl_usdt=-6.0, closed_at=datetime.now(timezone.utc).isoformat())
    sig(); A.tick(cl=Fake(False), px_fn=PX(100500.0))
    assert [r for r in rows() if r["ref_id"] != 999] == [] and any("daily loss" in t for t in fresh)

def test_flatten(monkeypatch):
    live(monkeypatch, order_type="market", strategies=["BRK"]); fk = Fake(); sig(status="open")
    A.tick(cl=fk, px_fn=PX(100100.0)); fk.positions = [dict(symbol="BTC_USDT", positionType=1, holdVol=10, positionId=1)]
    A.tick(cl=fk, px_fn=PX(100100.0)); sig(symbol="SOLUSDT", entry=150, sl=148, tp=156)
    A.save_settings(dict(order_type="limit")); A.tick(cl=fk, px_fn=PX(150.5))
    o = A.flatten(cl=fk, px_fn=PX(100200.0))
    assert o == dict(cancelled=1, closed=1, errors=[]) and A.settings(max_age=0)["enabled"] is False
    assert {r["status"] for r in rows()} == {"closed", "cancelled"} and fk.n("cancel_ext") == 1

def test_off_stops_new_orders():
    enable(); A.save_settings(dict(enabled=False)); sig()
    assert A.tick(cl=Fake(False), px_fn=PX(100500.0)).get("idle") and rows() == []

# ---------- isolation: signals / alerts unchanged when auto-trade fails ----------
def test_signals_and_alerts_unchanged_when_autotrade_raises(monkeypatch, fresh):
    from app import alerts
    monkeypatch.setattr(alerts, "get_mode", lambda: "primary_secondary")
    monkeypatch.setattr(A, "tick", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("MEXC exploded")))
    monkeypatch.setattr(A, "POLL_S", 0.01)
    th = threading.Thread(target=A.loop, args=(lambda: True,), daemon=True); th.start()     # worker running and failing every tick
    time.sleep(0.1)
    i = sig(status="open", strategy="BRK"); row = db.get(i)
    telegram.post_group([row])                                                             # the normal signal alert path
    assert th.is_alive() and any("BRK" in t for t in fresh) and db.get(i)["posted"] == 1
    assert any("MEXC exploded" in e["msg"] for e in A.STATE["errors"])

def test_autotrade_never_writes_signals(monkeypatch):
    enable(strategies=["BRK"]); i = sig(); before = db.get(i)
    for _ in range(3): A.tick(cl=Fake(False), px_fn=PX(99500.0))   # price under the entry -> dry fill etc.
    assert db.get(i) == before

def test_startup_survives_autotrade_failure(monkeypatch):
    from app import web, scanner, summary
    called = []
    monkeypatch.setattr(web.telegram, "start", lambda: None); monkeypatch.setattr(summary, "start", lambda: None)
    monkeypatch.setattr(web.don20, "start", lambda *a: None); monkeypatch.setattr(C, "ENABLE_SCHEDULER", True)
    monkeypatch.setattr(scanner, "start", lambda: called.append("scanner"))
    monkeypatch.setattr(A, "start", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    web._start(); assert called == ["scanner"]

def test_signal_modules_do_not_import_autotrade():
    root = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app")
    for f in ("scanner.py", "outcomes.py", "don20.py", "alerts.py", "strategy.py", "patterns_live.py", "desk.py", "trades.py", "summary.py", "db.py"):
        src = open(os.path.join(root, f)).read()
        for mod in ("autotrade", "bybit", "weex", "exchanges", "mexc"): assert mod not in src, (f, mod)

def test_telegram_panel_and_callbacks(monkeypatch):
    t, mk = A.tg_command("/autotrade"); assert "OFF" in t and mk["inline_keyboard"]
    A.tg_callback("at:s:BRK"); A.tg_callback("at:s:DON20"); assert A.settings(0)["strategies"] == ["DON20", "BRK"]
    A.tg_callback("at:en"); assert A.settings(0)["enabled"]
    toast, *_ = A.tg_callback("at:dr"); assert "key" in toast.lower() and A.settings(0)["dry_run"]   # no key: stays dry-run
    A.tg_command("/autotrade risk 2.5"); A.tg_command("/autotrade timeout 10"); s = A.settings(0)
    assert s["risk_usdt"] == 2.5 and s["limit_timeout_min"] == 10
    assert "⚠️" in A.tg_command("/autotrade lev 999")[0]
    _, _, _, extra = A.tg_callback("at:fl"); assert "Flatten" in extra[0]
    A.tg_command("/autotrade off"); assert not A.settings(0)["enabled"]


# =================== WEEX fallback exchange / failover (Bybit removed, user 2026-11-09) ===================
WXI = {"BTCUSDT": dict(symbol="BTCUSDT", quoteAsset="USDT", marginAsset="USDT", contractType="PERPETUAL", pricePrecision=1, quantityPrecision=3, contractVal=0.001,
                       minOrderSize=0.001, maxOrderSize=1000, marketOpenLimitSize=100, maxLeverage=100),
       "SOLUSDT": dict(symbol="SOLUSDT", quoteAsset="USDT", marginAsset="USDT", contractType="PERPETUAL", pricePrecision=2, quantityPrecision=1, contractVal=0.1,
                       minOrderSize=0.1, maxOrderSize=1000000, marketOpenLimitSize=80000, maxLeverage=50),
       "ONLYWXUSDT": dict(symbol="ONLYWXUSDT", quoteAsset="USDT", marginAsset="USDT", contractType="PERPETUAL", pricePrecision=4, quantityPrecision=0, contractVal=1,
                          minOrderSize=1, maxOrderSize=1000000, marketOpenLimitSize=1000000, maxLeverage=25),
       "NOAPIUSDT": dict(symbol="NOAPIUSDT", quoteAsset="USDT", marginAsset="USDT", contractType="PERPETUAL", pricePrecision=4, quantityPrecision=0, contractVal=1,
                         minOrderSize=1, maxOrderSize=1000000, marketOpenLimitSize=1000000, maxLeverage=20),
       "WXNOAPIUSDT": dict(symbol="WXNOAPIUSDT", quoteAsset="USDT", marginAsset="USDT", contractType="PERPETUAL", pricePrecision=4, quantityPrecision=0, contractVal=1,
                           minOrderSize=1, maxOrderSize=1000000, marketOpenLimitSize=1000000, maxLeverage=20)}
WXAPI = {"BTCUSDT", "SOLUSDT", "ONLYWXUSDT", "NOAPIUSDT"}

class FakeWeex:
    """Mock raw WEEX client (same methods as app.weex.Client)."""
    def __init__(self, private_ok=True):
        self.private_ok = private_ok; self.calls = []; self.orders = {}; self.pos = []; self.algos = []; self.down = None; self.fail_create = None
    def _p(self, name, *a, **k):
        if not self.private_ok: raise AssertionError(f"private WEEX call in dry-run: {name}")
        if self.down: raise self.down
        self.calls.append((name, a, k))
    def ping(self):
        if self.down: raise self.down
        return True
    def instruments(self): return WXI
    def api_symbols(self): return WXAPI
    def mark_price(self, sym): return None
    def usdt_available(self): self._p("usdt_available"); return 10000.0
    def positions(self): self._p("positions"); return list(self.pos)
    def set_leverage(self, sym, lev): self._p("set_leverage", sym, lev)
    def create_order(self, **b):
        self._p("create_order", **b)
        if self.fail_create: e = self.fail_create; self.fail_create = None; raise e
        oid = "W" + str(len(self.orders) + 1)
        if not b.get("reduceOnly"): self.orders[b["newClientOrderId"]] = dict(orderId=oid, status="FILLED" if b["type"] == "MARKET" else "NEW", executedQty=b["quantity"] if b["type"] == "MARKET" else "0", avgPrice=b.get("price") or "0")
        return oid
    def order_by_client(self, sym, cid): self._p("order_by_client", sym, cid); return self.orders.get(cid)
    def cancel_client(self, sym, cid):
        self._p("cancel_client", sym, cid)
        if cid in self.orders: self.orders[cid]["status"] = "CANCELED"
    def algo_orders(self, sym): self._p("algo_orders", sym); return [a for a in self.algos if a["symbol"] == sym]
    def place_tpsl(self, sym, ps, plan, trigger, cid): self._p("place_tpsl", sym, ps, plan, trigger)
    def modify_tpsl(self, algo_id, trigger):
        self._p("modify_tpsl", algo_id, trigger)
        if getattr(self, "fail_modify", None):
            e = self.fail_modify; self.fail_modify = None; raise e
    def cancel_algo(self, algo_id): self._p("cancel_algo", algo_id)
    def n(self, name): return sum(1 for c in self.calls if c[0] == name)

class DownMexc(Fake):
    """MEXC mock whose health ping fails."""
    def ping(self): raise requests.exceptions.ConnectTimeout("connect timeout")

def both_live(monkeypatch, **kw):
    monkeypatch.setattr(M, "key_present", lambda: True); monkeypatch.setattr(WX, "key_present", lambda: True)
    enable(**kw); return A.save_settings(dict(dry_run=False))
def creates(fk): return [c[2] for c in fk.calls if c[0] == "create_order"]

class Sess:
    """Mock HTTP session: records requests, answers from a {path: json} map (status 200 unless (status, json))."""
    def __init__(s, answers=None): s.reqs = []; s.answers = answers or {}
    def _ans(s, url):
        path = url.split("://", 1)[-1].split("/", 1)[-1].split("?")[0]; a = s.answers.get("/" + path, {})
        st, j = a if isinstance(a, tuple) else (200, a)
        class R: status_code = st; json = staticmethod(lambda: j)
        return R()
    def request(s, method, url, headers=None, data=None, timeout=None): s.reqs.append((method, url, headers, data)); return s._ans(url)
    def get(s, url, params=None, timeout=None): s.reqs.append(("GET", url, None, params)); return s._ans(url)

def _wsign(sk, msg): return base64.b64encode(hmac.new(sk.encode(), msg.encode(), hashlib.sha256).digest()).decode()

def test_weex_signing_headers_and_query():
    se = Sess({"/capi/v3/order": {"orderId": "702", "clientOrderId": "cfx1", "success": True, "errorCode": "", "errorMessage": ""}, "/capi/v3/openOrders": []})
    cl = WX.Client(key="WK", secret="WS", passphrase="WP", session=se, min_gap_s=0); cl._off = 0
    assert "WK" not in repr(cl) and "WS" not in repr(cl) and "WP" not in repr(cl)
    cl.private("GET", "/capi/v3/openOrders", params=dict(symbol="BTCUSDT", limit=100, page=None))
    m, url, h, data = se.reqs[-1]
    assert m == "GET" and url.endswith("/capi/v3/openOrders?symbol=BTCUSDT&limit=100") and data is None
    assert h["ACCESS-SIGN"] == _wsign("WS", h["ACCESS-TIMESTAMP"] + "GET/capi/v3/openOrders?symbol=BTCUSDT&limit=100")
    assert h["ACCESS-KEY"] == "WK" and h["ACCESS-PASSPHRASE"] == "WP" and h["Content-Type"] == "application/json"
    assert cl.create_order(symbol="BTCUSDT", side="BUY", positionSide="LONG", type="LIMIT", quantity="0.01", price="100000", newClientOrderId="cfx1", slTriggerPrice=None) == "702"
    m, url, h, data = se.reqs[-1]
    assert m == "POST" and url.endswith("/capi/v3/order") and "slTriggerPrice" not in data and json.loads(data)["positionSide"] == "LONG"
    assert h["ACCESS-SIGN"] == _wsign("WS", h["ACCESS-TIMESTAMP"] + "POST/capi/v3/order" + data)
    cl.cancel_client("BTCUSDT", "cfx1"); m, url, h, data = se.reqs[-1]
    assert m == "DELETE" and url.endswith("/capi/v3/order?origClientOrderId=cfx1") and data is None
    assert h["ACCESS-SIGN"] == _wsign("WS", h["ACCESS-TIMESTAMP"] + "DELETE/capi/v3/order?origClientOrderId=cfx1")
    # documented example string (GET with query): timestamp + METHOD + path + "?" + query
    assert WX.Client(key="k", secret="WS", passphrase="p").sign("1591089508404", "get", "/api/v3/market/depth", "symbol=BTCUSDT&limit=20") == _wsign("WS", "1591089508404GET/api/v3/market/depth?symbol=BTCUSDT&limit=20")
    with pytest.raises(WX.WeexError): WX.Client(key="a", secret="b", passphrase="").private("GET", "/x")   # passphrase required too

def test_weex_error_parsing():
    class R:
        def __init__(s, code, j): s.status_code = code; s._j = j
        def json(s):
            if s._j is None: raise ValueError("no json")
            return s._j
    cl = WX.Client(key="a", secret="b", passphrase="c")
    with pytest.raises(WX.RateLimited): cl._parse(R(429, {}))
    with pytest.raises(WX.RateLimited): cl._parse(R(400, {"code": -1059, "msg": "too many"}))
    with pytest.raises(WX.WeexError) as e: cl._parse(R(503, None))
    assert X.kind(e.value) == "server"
    with pytest.raises(WX.WeexError) as e: cl._parse(R(500, {"code": -1054, "msg": "System error"}))
    assert X.kind(e.value) == "server"
    with pytest.raises(WX.WeexError) as e: cl._parse(R(400, {"code": -1121, "msg": "Invalid symbol."}))
    assert e.value.code == -1121 and X.kind(e.value) is None
    with pytest.raises(WX.WeexError) as e: cl._parse(R(200, {"orderId": "", "success": False, "errorCode": "-3201", "errorMessage": "qty"}))
    assert e.value.code == -3201 and X.kind(e.value) is None
    with pytest.raises(WX.NoPermission): cl._parse(R(403, {"code": -1052, "msg": "Insufficient permissions"}))
    with pytest.raises(WX.WeexError) as e: cl._parse(R(403, None))
    assert X.kind(e.value) == "server"
    assert cl._parse(R(200, [{"asset": "USDT"}])) == [{"asset": "USDT"}] and cl._parse(R(200, {"serverTime": 1})) == {"serverTime": 1}
    assert X.kind(requests.exceptions.ConnectTimeout("x")) == "not_sent" and X.kind(requests.exceptions.ReadTimeout("x")) == "unknown"
    assert X.kind(M.MexcError(9999, "x")) == "server" and X.kind(M.MexcError(2005, "x")) is None and X.kind(ConnectionError("x")) == "unknown"

def test_weex_precision_and_sizing():
    ad = X.Weex(FakeWeex()); c = ad.instrument("BTCUSDT")
    assert c["volUnit"] == 0.001 and c["volScale"] == 3 and c["priceUnit"] == 0.1 and c["priceScale"] == 1 and c["maxVol"] == 100 and c["contractSize"] == 1
    z = M.size(c, 100000, 99000, 10.5); assert z["vol"] == 0.01 and abs(z["risk"] - 10) < 1e-9   # 0.0105 floored to the 0.001 step
    assert M.round_price(100000.06, c) == 100000.1 and WX.dstr(0.01) == "0.01" and WX.dstr(1e-05) == "0.00001" and WX.dstr(100000.0) == "100000"
    d = X.Weex(FakeWeex()); WXI["DOGEX"] = dict(WXI["BTCUSDT"], symbol="DOGEX", contractVal=100, quantityPrecision=-2, minOrderSize=100, pricePrecision=5, maxOrderSize=6e8, marketOpenLimitSize=6e7)
    try:
        d.cl.api_symbols = lambda: WXAPI | {"DOGEX"}; dc = d.instrument("DOGEX")
        assert dc["volUnit"] == 100 and dc["volScale"] == 0 and M.size(dc, 0.1, 0.09, 25.01)["vol"] == 2500 and M.round_price(0.123456, dc) == 0.12346
    finally: WXI.pop("DOGEX")
    with pytest.raises(M.NotListed): ad.instrument("NOPEUSDT")
    with pytest.raises(M.NotListed) as e: ad.instrument("WXNOAPIUSDT")
    assert "API" in str(e.value)
    with pytest.raises(M.Skip): M.size(ad.instrument("SOLUSDT"), 10, 9, 0.05)   # below the 0.1 minimum

def test_weex_client_order_lookup_and_public_parsing():
    se = Sess({"/capi/v3/openOrders": [dict(clientOrderId="other", orderId=1, status="NEW")],
               "/capi/v3/order/history": [dict(clientOrderId="cfxw1", orderId=9, status="FILLED", executedQty="0.01", avgPrice="100010")],
               "/capi/v3/market/exchangeInfo": {"symbols": [dict(WXI["BTCUSDT"]), dict(WXI["BTCUSDT"], symbol="BTCUSD", quoteAsset="USD")]},
               "/capi/v3/market/apiTradingSymbols": ["BTCUSDT"],
               "/capi/v3/market/riskLimits": [{"symbol": "BTCUSDT", "brackets": [{"bracket": 2, "notionalCap": "3500000", "initialLeverage": 300, "maintMarginRatio": "0.002"},
                                                                                {"bracket": 1, "notionalCap": "2000000", "initialLeverage": 400, "maintMarginRatio": "0.0015"}]}],
               "/capi/v3/market/symbolPrice": {"symbol": "BTCUSDT", "price": "100005.5"}, "/capi/v3/market/time": {"serverTime": int(time.time() * 1000)},
               "/capi/v3/account/balance": [{"asset": "USDT", "availableBalance": "123.5"}]})
    cl = WX.Client(key="k", secret="s", passphrase="p", session=se, min_gap_s=0)
    ad = X.Weex(cl); o = ad.order("BTCUSDT", "cfxw1")
    assert o == dict(order_id="9", state="filled", filled=0.01, avg=100010.0)
    assert [r[1].split("?")[0].rsplit("/capi", 1)[1] for r in se.reqs if r[2]] == ["/v3/openOrders", "/v3/order/history"]
    assert list(cl.instruments()) == ["BTCUSDT"] and cl.api_symbols() == {"BTCUSDT"} and cl.ping() and ad.fair_price("BTCUSDT") == 100005.5
    assert [b["bracket"] for b in cl.risk_limits("BTCUSDT")] == [1, 2] and ad.tier("BTCUSDT", ad.instrument("BTCUSDT"), 1, 2500000) == dict(max_lev=300, mmr=0.002)
    assert ad.usdt_available() == 123.5 and ad.order("BTCUSDT", "missing") is None

def test_weex_adapter_order_bodies():
    fw = FakeWeex(); ad = X.Weex(fw)
    ad.place_open("BTCUSDT", "short", 0.01, 100000.0, False, 7, 101000.0, 97000.0, "cfxABw s1")
    (b,) = creates(fw)
    assert b["side"] == "SELL" and b["positionSide"] == "SHORT" and b["type"] == "LIMIT" and b["timeInForce"] == "GTC" and b["price"] == "100000" and b["quantity"] == "0.01"
    assert b["slTriggerPrice"] == "101000" and b["tpTriggerPrice"] == "97000" and b["reduceOnly"] is False and fw.calls[0] == ("set_leverage", ("BTCUSDT", 7), {})
    ad.place_open("BTCUSDT", "long", 0.01, 100000.0, True, 5, 99000.0, None, "cfxm"); b = creates(fw)[-1]
    assert b["type"] == "MARKET" and "price" not in b and "timeInForce" not in b and "tpTriggerPrice" not in b and b["side"] == "BUY"
    fw.pos = [dict(id=55, symbol="BTCUSDT", side="LONG", size="0.010", openValue="1000.1", marginType="CROSSED")]
    (p,) = ad.positions(); assert p["direction"] == "long" and p["size"] == 0.01 and p["pid"] == "55" and abs(p["avg"] - 100010) < 1e-6
    ad.close(p, 0.01, 100000.0, "cfxmx"); c = creates(fw)[-1]
    assert c["side"] == "SELL" and c["positionSide"] == "LONG" and c["type"] == "MARKET" and c["reduceOnly"] is True
    fw.algos = [dict(algoId=1, symbol="BTCUSDT", positionSide="LONG", orderType="STOP_MARKET", algoStatus="UNTRIGGERED", reduceOnly=True),
                dict(algoId=2, symbol="BTCUSDT", positionSide="SHORT", orderType="STOP_MARKET", algoStatus="UNTRIGGERED", reduceOnly=True)]
    ad.set_tpsl(p, 99500.0, 103000.0)
    assert [c[1] for c in fw.calls if c[0] == "modify_tpsl"] == [(1, 99500.0)] and [c[1][2:] for c in fw.calls if c[0] == "place_tpsl"] == [("TAKE_PROFIT", 103000.0)]
    ad.cancel_tpsl(p); assert [c[1] for c in fw.calls if c[0] == "cancel_algo"] == [(1,)]

def test_failover_when_mexc_health_check_fails(monkeypatch, fresh):
    both_live(monkeypatch); sig(); fk, fw = DownMexc(), FakeWeex()
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "weex" and r["status"] == "open_order" and fk.n("create_order") == 0
    (b,) = creates(fw)
    assert b["side"] == "BUY" and b["positionSide"] == "LONG" and b["type"] == "LIMIT" and b["quantity"] == "0.01" and b["price"] == "100000"
    assert b["slTriggerPrice"] == "99000" and b["tpTriggerPrice"] == "103000" and b["newClientOrderId"] == r["ext_oid"] and len(b["newClientOrderId"]) <= 36
    assert fw.n("set_leverage") == 1 and any("Backup" in t and "health check failed" in t and "WEEX" in t for t in fresh)

def test_failover_when_connection_never_opened(monkeypatch):
    both_live(monkeypatch); sig(); fk, fw = Fake(), FakeWeex(); fk.fail_create = requests.exceptions.ConnectTimeout("connect timed out")
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0))
    assert len(rows()) == 1 and rows()[0]["exchange"] == "weex" and fk.n("create_order") == 1 and fw.n("create_order") == 1
    assert fk.n("order_by_ext") == 1   # MEXC asked by client order id first

def test_failover_on_5xx_only_after_mexc_confirms_no_order(monkeypatch):
    both_live(monkeypatch); sig(); fk, fw = Fake(), FakeWeex(); fk.fail_create = M.MexcError(503, "Service Unavailable", 503)
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0))
    assert rows()[0]["exchange"] == "weex" and fw.n("create_order") == 1

def test_no_failover_when_mexc_state_unknown(monkeypatch, fresh):
    both_live(monkeypatch); sig(); fk, fw = Fake(), FakeWeex(); fk.fail_create = requests.exceptions.ReadTimeout("read timed out")
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "mexc" and r["status"] == "placing" and fw.n("create_order") == 0 and any("state unknown" in t for t in fresh)
    fk.orders[r["ext_oid"]] = dict(orderId="777", state=2, dealVol=0)       # it had reached MEXC after all
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0))
    assert rows()[0]["status"] == "open_order" and rows()[0]["order_id"] == "777" and fw.n("create_order") == 0 and len(rows()) == 1

def test_no_failover_when_5xx_and_lookup_fails(monkeypatch):
    both_live(monkeypatch); sig(); fw = FakeWeex()
    class F(Fake):
        def order_by_ext(self, sym, ext): raise requests.exceptions.ReadTimeout("lookup timed out")
    fk = F(); fk.fail_create = M.MexcError(500, "Internal error", 500)
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0))
    assert rows()[0]["exchange"] == "mexc" and rows()[0]["status"] == "placing" and fw.n("create_order") == 0

def test_business_rejection_does_not_fail_over(monkeypatch):
    both_live(monkeypatch); sig(); fk, fw = Fake(), FakeWeex(); fk.fail_create = M.MexcError(2005, "Balance insufficient")
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0))
    assert rows()[0]["status"] == "error" and rows()[0]["exchange"] == "mexc" and fw.n("create_order") == 0

def test_symbol_missing_or_not_api_tradable_on_mexc_routes_to_weex(monkeypatch):
    both_live(monkeypatch); sig(symbol="ONLYWXUSDT", entry=1.0, sl=0.9, tp=1.3); fk, fw = Fake(), FakeWeex()
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(1.01)); r = rows()[0]
    assert r["exchange"] == "weex" and r["contract"] == "ONLYWXUSDT" and fk.n("create_order") == 0 and creates(fw)[0]["quantity"] == "100"
    sig(symbol="NOAPIUSDT", entry=1.0, sl=0.9, tp=1.3)                      # listed on MEXC but apiAllowed=False
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(1.01)); r = rows()[-1]
    assert r["symbol"] == "NOAPIUSDT" and r["exchange"] == "weex" and fk.n("create_order") == 0

def test_weex_is_last_unavailable_everywhere_is_recorded(monkeypatch, fresh):
    both_live(monkeypatch); sig(symbol="WXNOAPIUSDT", entry=1.0, sl=0.9, tp=1.3); fk, fw = Fake(), FakeWeex()
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(1.01)); r = rows()[0]
    assert r["status"] == "skipped" and "not listed on MEXC" in json.loads(r["note"])["skip"] and "not API-tradable on WEEX" in json.loads(r["note"])["skip"]
    assert creates(fk) == [] and creates(fw) == []
    sig(); fk2, fw2 = Fake(), FakeWeex(); fk2.fail_create = M.MexcError(503, "down", 503); fw2.fail_create = WX.WeexError(503, "HTTP 503", 503)
    A.tick(cl={"mexc": fk2, "weex": fw2}, px_fn=PX(100500.0)); r = rows()[-1]
    assert r["status"] == "error" and r["exchange"] == "weex" and fw2.n("order_by_client") == 1 and any("not placed" in t for t in fresh)
    assert len([x for x in rows() if x["ref_id"] == r["ref_id"]]) == 1        # one row per signal

def test_no_failover_back_when_weex_state_unknown(monkeypatch, fresh):
    both_live(monkeypatch); A.save_settings(dict(exchanges="weex,mexc")); sig(); fk, fw = Fake(), FakeWeex()
    fw.fail_create = requests.exceptions.ReadTimeout("read timed out")
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "weex" and r["status"] == "placing" and fk.n("create_order") == 0 and any("WEEX order state unknown" in t for t in fresh)

def test_single_exchange_mode_or_no_weex_key(monkeypatch):
    both_live(monkeypatch); A.save_settings(dict(exchanges="mexc")); sig(); fk, fw = DownMexc(), FakeWeex()
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["status"] == "skipped" and "health check failed" in json.loads(r["note"])["skip"] and fw.calls == []   # MEXC only: never WEEX
    A.save_settings(dict(exchanges="mexc,weex")); monkeypatch.setattr(WX, "key_present", lambda: False)
    assert A.failover_on(A.settings(0)) and A.route(A.settings(0), {"mexc": 1, "weex": 1}) == ["mexc"]   # live: WEEX inert without its keys
    assert A.route(dict(A.settings(0), dry_run=True), {"mexc": 1, "weex": 1}) == ["mexc", "weex"]
    A.save_settings(dict(exchanges="weex")); assert A.route(A.settings(0), {"mexc": 1, "weex": 1}) == []
    sig(symbol="SOLUSDT", entry=150, sl=148, tp=156); A.tick(cl={"mexc": Fake(), "weex": fw}, px_fn=PX(150.2))
    r = [x for x in rows() if x["symbol"] == "SOLUSDT"][0]; assert r["status"] == "skipped" and "API key" in json.loads(r["note"])["skip"]

def test_weex_only_and_weex_first_modes(monkeypatch, fresh):
    both_live(monkeypatch); A.save_settings(dict(exchanges="weex")); sig(); fk, fw = Fake(), FakeWeex()
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "weex" and r["status"] == "open_order" and creates(fk) == [] and creates(fw)[0]["quantity"] == "0.01"
    A.save_settings(dict(exchanges="weex,mexc")); sig(symbol="ONLYMXUSDT", entry=1.0, sl=0.9, tp=1.3)   # not on WEEX -> MEXC fallback
    CON["ONLYMX_USDT"] = dict(symbol="ONLYMX_USDT", contractSize=1, priceUnit=0.0001, priceScale=4, volUnit=1, volScale=0, minVol=1, maxVol=10**7, maxLeverage=50, apiAllowed=True, state=0)
    try:
        A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(1.01)); r = rows()[-1]
        assert r["exchange"] == "mexc" and r["symbol"] == "ONLYMXUSDT" and len(creates(fk)) == 1 and any("not listed on WEEX" in t for t in fresh)
    finally: CON.pop("ONLYMX_USDT")
    fw2 = FakeWeex(); fw2.fail_create = requests.exceptions.ReadTimeout("read timed out"); fk2 = Fake(); sig(symbol="SOLUSDT", entry=150, sl=148, tp=156)
    A.tick(cl={"mexc": fk2, "weex": fw2}, px_fn=PX(150.2)); r = rows()[-1]
    assert r["exchange"] == "weex" and r["status"] == "placing" and creates(fk2) == []   # unknown state on the first: never the second

def test_weex_key_needs_all_three_env_vars(monkeypatch):
    for k in WX.ENV: monkeypatch.setenv(k, "x")
    assert _WX_KEY_PRESENT() and WX.ENV == ("WEEX_API_KEY", "WEEX_API_SECRET", "WEEX_API_PASSPHRASE")
    monkeypatch.setenv("WEEX_API_PASSPHRASE", ""); assert not _WX_KEY_PRESENT()

def test_exits_and_stops_managed_on_the_opening_exchange(monkeypatch):
    both_live(monkeypatch, order_type="auto", strategies=["PAT-WEDGE"]); fk, fw = DownMexc(), FakeWeex()
    i = sig(symbol="SOLUSDT", strategy="PAT-WEDGE", entry=150, sl=148, tp=156, status="open")
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(150.1)); r = rows()[0]
    assert r["exchange"] == "weex" and creates(fw)[0]["type"] == "MARKET"
    fk2 = Fake()                                                                     # MEXC is back: trade must stay on WEEX
    fw.pos = [dict(id=9, symbol="SOLUSDT", side="LONG", size=str(r["vol"]), openValue=str(150.1 * r["vol"]), marginType="CROSSED")]
    fw.algos = [dict(algoId=11, symbol="SOLUSDT", positionSide="LONG", orderType="STOP_MARKET", algoStatus="UNTRIGGERED", reduceOnly=True),
                dict(algoId=12, symbol="SOLUSDT", positionSide="LONG", orderType="TAKE_PROFIT_MARKET", algoStatus="UNTRIGGERED", reduceOnly=True)]
    A.tick(cl={"mexc": fk2, "weex": fw}, px_fn=PX(150.3)); assert rows()[0]["status"] == "filled"
    db.update(i, sl=149.0, tp=153.0); A.tick(cl={"mexc": fk2, "weex": fw}, px_fn=PX(150.3))
    assert [c[1] for c in fw.calls if c[0] == "modify_tpsl"] == [(11, 149.0), (12, 153.0)]
    db.update(i, status="sl", closed_at=datetime.now(timezone.utc).isoformat(), result_r=-1.0)
    A.tick(cl={"mexc": fk2, "weex": fw}, px_fn=PX(148.9))
    close = [b for b in creates(fw) if b.get("reduceOnly")]
    assert close and close[-1]["side"] == "SELL" and close[-1]["positionSide"] == "LONG" and close[-1]["type"] == "MARKET" and float(close[-1]["quantity"]) == r["vol"]
    assert rows()[0]["status"] == "closed" and fk2.calls == [] and fk.calls == []

def test_exit_retries_when_opening_exchange_is_down(monkeypatch, fresh):
    both_live(monkeypatch, order_type="market"); i = sig(status="open"); fk, fw = Fake(), FakeWeex()
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100100.0)); assert rows()[0]["exchange"] == "mexc"
    fk.positions = [dict(symbol="BTC_USDT", positionType=1, holdVol=rows()[0]["vol"], positionId=1)]
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100100.0)); assert rows()[0]["status"] == "filled"
    db.update(i, status="tp", closed_at=datetime.now(timezone.utc).isoformat(), result_r=3.0)
    class Down(Fake):
        def open_positions(self, sym=None): raise requests.exceptions.ConnectionError("Failed to establish a new connection")
    dn = Down(); dn.orders = fk.orders
    A.tick(cl={"mexc": dn, "weex": fw}, px_fn=PX(103100.0))
    assert rows()[0]["status"] == "filled" and fw.calls == [] and any("unreachable" in t and "still protect" in t for t in fresh)
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(103100.0))                     # back up -> closed on MEXC, never on WEEX
    assert rows()[0]["status"] == "closed" and any(b["side"] == 4 for b in creates(fk)) and fw.n("create_order") == 0

def test_mexc_700007_balance_permission_note(monkeypatch, fresh):
    both_live(monkeypatch); sig()
    class NoBal(Fake):
        def usdt_available(self): raise M.NoPermission(700007, "No permission to access the endpoint")
    fk = NoBal(); A.tick(cl={"mexc": fk, "weex": FakeWeex()}, px_fn=PX(100500.0))
    assert rows()[0]["status"] == "open_order" and rows()[0]["exchange"] == "mexc"     # placed; MEXC itself checks margin
    assert any("View Account Details" in t for t in fresh) and "mexc" in A.STATE["perm"]
    monkeypatch.setattr(A, "prices", lambda syms: {s: 100500.0 for s in syms})
    v = A.view(); assert [e for e in v["exchanges"] if e["name"] == "mexc"][0]["perm_note"] and "700007" in A.panel_text()
    class R:
        status_code = 200
        def json(s): return {"success": False, "code": 700007, "message": "No permission"}
    with pytest.raises(M.NoPermission): M.Client(key="a", secret="b")._parse(R())

def test_dry_run_failover_uses_no_private_calls(monkeypatch):
    enable(); A.save_settings(dict(exchanges="mexc,weex")); sig(); fk, fw = DownMexc(private_ok=False), FakeWeex(private_ok=False)
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "weex" and r["dry"] == 1 and r["vol"] == 0.01 and fw.calls == [] and fk.calls == []

def test_exchange_settings_and_panel(monkeypatch):
    s = A.settings(0); assert s["exchanges"] == ["mexc", "weex"] and s["enabled"] is False and s["dry_run"] is True
    assert X.NAMES == ("mexc", "weex") and not any(k in s for k in A.LEGACY_EX)
    for bad in ("binance", "bybit", "mexc,mexc", "", "mexc,bybit"):
        with pytest.raises(ValueError): A.save_settings(dict(exchanges=bad))
    with pytest.raises(ValueError): A.save_settings(dict(primary_exchange="bybit"))
    with pytest.raises(ValueError): A.save_settings(dict(ex_on={"bybit": True}))
    with pytest.raises(ValueError): A.save_settings(dict(ex_on={"mexc": False, "weex": False}))
    for cmd, want in (("weex", ["weex"]), ("mexc", ["mexc"]), ("weex,mexc", ["weex", "mexc"]), ("mexc,weex", ["mexc", "weex"]), ("both", ["mexc", "weex"]), ("weex mexc", ["weex", "mexc"])):
        t, mk = A.tg_command("/autotrade exchanges " + cmd); assert A.settings(0)["exchanges"] == want, cmd
    assert "⚠️" in A.tg_command("/autotrade exchanges binance")[0] and A.settings(0)["exchanges"] == ["weex", "mexc"]   # unchanged
    for cb, want in (("at:em:weex", ["weex"]), ("at:em:weex,mexc", ["weex", "mexc"]), ("at:em:mexc", ["mexc"]), ("at:em:mexc,weex", ["mexc", "weex"])):
        A.tg_callback(cb); assert A.settings(0)["exchanges"] == want, cb
    # old commands / buttons keep working
    A.tg_callback("at:px"); assert A.settings(0)["exchanges"] == ["weex", "mexc"]
    A.tg_command("/autotrade primary mexc"); assert A.settings(0)["exchanges"] == ["mexc", "weex"]
    A.tg_command("/autotrade failover off"); assert A.settings(0)["exchanges"] == ["mexc"]
    A.tg_command("/autotrade failover on"); assert A.settings(0)["exchanges"] == ["mexc", "weex"]
    A.tg_command("/autotrade weex off"); assert A.settings(0)["exchanges"] == ["mexc"]
    A.tg_callback("at:x:weex"); assert A.settings(0)["exchanges"] == ["mexc", "weex"]
    A.tg_command("/autotrade primary weex"); A.tg_command("/autotrade mexc off"); assert A.settings(0)["exchanges"] == ["weex"]
    A.tg_command("/autotrade primary mexc"); assert A.settings(0)["exchanges"] == ["mexc"]       # single mode: switches the exchange
    A.tg_callback("at:fo"); assert A.settings(0)["exchanges"] == ["mexc", "weex"]
    t, mk = A.tg_command("/autotrade"); assert "WEEX" in t and "Bybit" not in t and "MEXC → WEEX" in t and "exchanges mexc" in t
    cbs = [b["callback_data"] for row in mk["inline_keyboard"] for b in row]
    assert {"at:em:mexc", "at:em:weex", "at:em:mexc,weex", "at:em:weex,mexc", "at:mb"} <= set(cbs) and not any("bybit" in c for c in cbs)
    assert "Usage" in A.tg_command("/autotrade bybit on")[0] and A.settings(0)["exchanges"] == ["mexc", "weex"]
    assert A.settings(0)["enabled"] is False and A.settings(0)["dry_run"] is True   # exchange controls never switch auto-trade on
    monkeypatch.setattr(A, "prices", lambda syms: {}); v = A.view()
    assert [e["name"] for e in v["exchanges"]] == ["mexc", "weex"] and v["route"] == ["MEXC", "WEEX"] and v["exchange"]["name"] == "MEXC → WEEX"
    assert v["exchange_mode"] == "mexc,weex" and [m["value"] for m in v["exchange_modes"]] == ["mexc", "weex", "mexc,weex", "weex,mexc"]
    A.save_settings(dict(exchanges="weex")); v = A.view()
    assert v["exchange_mode_label"] == "WEEX only" and [e["primary"] for e in v["exchanges"]] == [False, True] and v["settings"]["primary_exchange"] == "weex"

def test_saved_legacy_exchange_settings_migrate_without_enabling():
    def load(d): db.kv_set(A.KEY, json.dumps(d)); A._S.update(t=0, v=None); return A.settings(0)
    s = load(dict(enabled=False, dry_run=True, primary_exchange="mexc", failover=None, ex_on={"mexc": True, "weex": True}, risk_usdt=1.0))
    assert s["exchanges"] == ["mexc", "weex"] and s["enabled"] is False and s["dry_run"] is True and s["risk_usdt"] == 1.0   # the live VM's shape
    s = A.save_settings(dict(risk_usdt=2)); saved = json.loads(db.kv_get(A.KEY))
    assert saved["exchanges"] == ["mexc", "weex"] and not any(k in saved for k in A.LEGACY_EX) and saved["enabled"] is False and saved["dry_run"] is True
    assert load(dict(primary_exchange="mexc", failover=False))["exchanges"] == ["mexc"]
    assert load(dict(primary_exchange="weex", failover=True))["exchanges"] == ["weex", "mexc"]
    assert load(dict(primary_exchange="mexc", ex_on={"mexc": True, "weex": False}))["exchanges"] == ["mexc"]
    assert load(dict(primary_exchange="mexc", ex_on={"mexc": False, "weex": True}))["exchanges"] == ["weex"]
    s = load(dict(enabled=False, dry_run=True, primary_exchange="bybit", ex_on={"mexc": True, "bybit": False}, failover=None))
    assert s["exchanges"] == ["mexc"] and "bybit" not in json.dumps(s) and s["enabled"] is False and s["dry_run"] is True
    assert load(dict(primary_exchange="mexc", ex_on={"mexc": True, "bybit": True}))["exchanges"] == ["mexc", "weex"]
    assert load({})["exchanges"] == ["mexc", "weex"] and load(dict(exchanges=["bogus"]))["exchanges"] == ["mexc", "weex"]
    assert load(dict(exchanges=["weex"], primary_exchange="mexc"))["exchanges"] == ["weex"]   # new key wins

def test_bybit_fully_removed():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    assert not os.path.exists(os.path.join(root, "app", "bybit.py"))
    with pytest.raises(ImportError): __import__("app.bybit")
    for f in ("exchanges.py", "telegram.py", "desk.html", "sizing.py"):
        assert "bybit" not in open(os.path.join(root, "app", f)).read().lower(), f
    src = open(os.path.join(root, "app", "autotrade.py")).read().lower()
    assert not any(l.strip().startswith(("from", "import")) and "bybit" in l for l in src.splitlines())
    assert set(A.adapters({"mexc": Fake(), "weex": FakeWeex()})) == {"mexc", "weex"}

def test_old_rows_without_exchange_are_mexc(monkeypatch):
    A.ensure_table(); A._insert(source="sig", ref_id=5, strategy="BRK", symbol="BTCUSDT", direction="long", status="closed", dry=1, pnl_usdt=1.0, closed_at=datetime.now(timezone.utc).isoformat())
    assert A.exof(rows()[0]) == "mexc"
    A._TBL["ok"] = False; A.ensure_table(); A.ensure_table()   # migration is idempotent

# =================== t142u: leverage MAX + liquidation guard, max position size, Limit → Market ===================
def test_leverage_max_tier_and_liquidation_guard():
    c = dict(CON["BTC_USDT"], initialMarginRate=0.002, maintenanceMarginRate=0.001)
    ad = X.Mexc(Fake())
    lev, info = X.choose_leverage(ad, "BTC_USDT", c, 100, 1000, 100000, 99000, "long", "max", 5)   # 1% stop: 500x would liquidate first
    assert info["tier_max"] == 500 and info["stepped_from"] == 500 and lev == 90
    assert not X.liq_inside(100000, 99000, lev, 0.001, "long") and X.liq_inside(100000, 99000, lev + 1, 0.001, "long")
    lev, info = X.choose_leverage(ad, "BTC_USDT", c, 100, 1000, 100000, 101000, "short", "max", 5); assert lev == 90   # same for shorts
    assert X.choose_leverage(ad, "BTC_USDT", c, 100, 1000, 100000, 99000, "long", "cap", 5)[0] == 5          # cap mode, no step needed
    assert X.choose_leverage(ad, "BTC_USDT", c, 100, 1000, 100000, 80000, "long", "cap", 10)[0] == 4         # 20% stop: 10x liq inside -> 4x
    t = dict(c, riskBaseVol=100, riskIncrVol=100, riskIncrImr=0.01, riskIncrMmr=0.005, riskLevelLimit=5)
    assert ad.tier("BTC_USDT", t, 250, 0) == dict(max_lev=45, mmr=0.011)                                   # level 2 tier by volume
    fw = FakeWeex(); fw.risk_limits = lambda sym: [dict(bracket=1, notionalCap="300000", maintMarginRatio="0.0033", initialLeverage=150), dict(bracket=2, notionalCap="2000000", maintMarginRatio="0.005", initialLeverage=100)]
    w = X.Weex(fw); wc = w.instrument("BTCUSDT")
    assert w.tier("BTCUSDT", wc, 1, 100000) == dict(max_lev=150, mmr=0.0033) and w.tier("BTCUSDT", wc, 1, 500000)["max_lev"] == 100
    assert w.tier("BTCUSDT", wc, 1, 9e9)["max_lev"] == 100 and X.Weex(FakeWeex()).tier("BTCUSDT", wc, 1, 1) == dict(max_lev=100, mmr=X.DEFAULT_MMR)
    lev, info = X.choose_leverage(w, "BTCUSDT", wc, 0.01, 1000, 100000, 99000, "long", "max", 5); assert lev < 150 and not X.liq_inside(100000, 99000, lev, 0.0033, "long")

def test_live_order_uses_max_leverage_with_guard(monkeypatch, capsys):
    live(monkeypatch, leverage="max"); assert A.settings(0)["lev_mode"] == "max"
    sig(); fk = Fake(); A.tick(cl=fk, px_fn=PX(100500.0))
    (b,) = [c[2] for c in fk.calls if c[0] == "create_order"]
    assert not X.liq_inside(100000, 99000, b["leverage"], X.DEFAULT_MMR, "long") and X.liq_inside(100000, 99000, b["leverage"] + 1, X.DEFAULT_MMR, "long")
    assert b["vol"] == 100 and "leverage 500x ->" in capsys.readouterr().out                         # size unchanged: risk ÷ stop
    assert json.loads(rows()[0]["note"])["lev"]["stepped_from"] == 500

def test_leverage_and_size_commands():
    A.tg_command("/autotrade lev max"); assert A.settings(0)["lev_mode"] == "max"
    A.tg_command("/autotrade lev 7"); s = A.settings(0); assert s["lev_mode"] == "cap" and s["leverage"] == 7
    A.tg_command("/autotrade size 250"); assert A.settings(0)["max_notional_usdt"] == 250
    A.tg_callback("at:lv:max"); assert A.settings(0)["lev_mode"] == "max"
    t, mk = A.tg_command("/autotrade"); assert "Max position size" in t and "MAX" in t and "notional" not in t.lower().replace("lev", "")
    cbs = [b["callback_data"] for row in mk["inline_keyboard"] for b in row]
    assert "at:ot:auto" in cbs and "at:ot:limit" in cbs and "at:ot:limit_market" not in cbs and "at:ot:market" not in cbs

# =================== t144u: 📐 Size line on crypto signal alerts (additive) ===================
def _sz_reset():
    from app import sizing; sizing._C.update(t=0, v=None); return sizing
def test_size_line_math_and_settings():
    sizing = _sz_reset(); A.save_settings(dict(risk_usdt=10, leverage=5)); _sz_reset()
    l = sizing.line("BTCUSDT", 100000, 99000); assert l == "📐 <b>Size</b>  0.01 BTC · $1,000.00 position · risk $10.00 · ≤5x → margin ~$200.00"
    A.save_settings(dict(max_notional_usdt=500)); _sz_reset()
    assert "0.005 BTC · $500.00 position · risk $5.00" in sizing.line("BTCUSDT", 100000, 99000)          # max position size caps it
    A.save_settings(dict(leverage="max")); _sz_reset(); assert "MAX lev" in sizing.line("SOLUSDT", 150, 148)
    assert sizing.line("EURUSD", 1.1, 1.09, market="forex") is None and sizing.line("BTCUSDT", 100, 100) is None
    A.save_settings(dict(size_line=False)); _sz_reset(); assert sizing.line("BTCUSDT", 100000, 99000) is None
    assert A.settings(0)["enabled"] is False                                                             # works with auto-trade OFF

def test_size_line_is_additive_on_signal_alerts(monkeypatch, fresh):
    from app import alerts; sizing = _sz_reset()
    monkeypatch.setattr(alerts, "get_mode", lambda: "primary_secondary")
    A.save_settings(dict(risk_usdt=10)); _sz_reset()
    i = sig(status="open", strategy="BRK"); row = db.get(i); base = telegram.fmt(row)
    telegram.post_group([row]); sent = fresh[-1]
    assert "📐 <b>Size</b>" in sent and db.get(i)["posted"] == 1
    assert "\n".join(x for x in sent.split("\n") if not x.startswith("📐")) == base                   # nothing else changed
    j = sig(status="open", strategy="BRK", symbol="SOLUSDT", entry=150, sl=148, tp=156); r2 = db.get(j)
    monkeypatch.setattr(sizing, "calc", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    telegram.post_group([r2]); assert fresh[-1] == telegram.fmt(r2) and db.get(j)["posted"] == 1        # sizing fails -> line omitted
    A.save_settings(dict(size_line=False)); _sz_reset(); monkeypatch.undo()
    monkeypatch.setattr(alerts, "get_mode", lambda: "primary_secondary"); monkeypatch.setattr(telegram, "send", lambda t, chat_id=None, html=False: fresh.append(t) or True)
    k = sig(status="open", strategy="BRK", symbol="ETHUSDT", entry=3000, sl=2950, tp=3150); r3 = db.get(k)
    telegram.post_group([r3]); assert fresh[-1] == telegram.fmt(r3)

def test_size_line_on_don_entry(monkeypatch, fresh):
    from app import alerts; _sz_reset(); A.save_settings(dict(risk_usdt=10)); _sz_reset()
    monkeypatch.setattr(alerts, "should_push", lambda k: True)
    txt = "⭐ <b>PRIMARY · DON20</b>\nbody\n\n<i>Not financial advice.</i>"
    don20._dispatch([dict(k="DON20", kind="entry", symbol="BTCUSDT", direction="long", day="d", id=1, extra=[], entry=100000.0, stop=97000.0, line="", text=txt)], True)
    assert fresh[-1].startswith("⭐ <b>PRIMARY · DON20</b>\nbody\n📐 <b>Size</b>") and fresh[-1].endswith("<i>Not financial advice.</i>")
    don20._dispatch([dict(k="DON20", kind="exit", symbol="BTCUSDT", direction="long", day="d", id=1, extra=[], line="", text="exit text")], True)
    assert fresh[-1] == "exit text"                                                                      # exits untouched

def test_sizing_module_is_pure():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "sizing.py")).read()
    for mod in ("import requests", "autotrade import", "from . import autotrade", "mexc", "bybit", "weex", "telegram"): assert mod not in src, mod
    imports = [l for l in src.splitlines() if l.strip().startswith(("import ", "from "))]          # the `exchanges` SETTING is read, the module never
    assert not any("exchanges" in l or "mexc" in l or "weex" in l or "autotrade" in l for l in imports), imports


# =================== t156u: minimum-order bump (cap) + exchange mode ===================
SMALL = dict(symbol="SMALL_USDT", contractSize=1, priceUnit=0.0001, priceScale=4, volUnit=1, volScale=0, minVol=10, maxVol=10**7, maxLeverage=50, apiAllowed=True, state=0)
def test_size_min_order_bump_math():
    c = CON["BTC_USDT"]                                               # min 1 contract = 0.0001 BTC; at a 1000 stop that is $0.10 risk
    with pytest.raises(M.MinSize): M.size(c, 100000, 99000, 0.05)                          # bump off (default in M.size)
    z = M.size(c, 100000, 99000, 0.05, bump=True)                                          # $0.10 <= auto cap 2 x 0.05
    assert z["vol"] == 1 and abs(z["risk"] - 0.1) < 1e-9 and z["bump"]["from_vol"] == 0.5 and z["bump"]["to_vol"] == 1 and z["bump"]["auto"] and z["bump"]["cap_risk"] == 0.1
    with pytest.raises(M.MinSize) as e: M.size(c, 100000, 99000, 0.04, bump=True)          # $0.10 > 2 x 0.04
    assert "bump cap $0.08" in str(e.value) and "2× risk" in str(e.value)
    assert M.size(c, 100000, 99000, 0.04, bump=True, bump_max_risk=0.5)["vol"] == 1        # explicit cap
    with pytest.raises(M.MinSize) as e: M.size(c, 100000, 99000, 0.04, max_notional=5, bump=True, bump_max_risk=1)
    assert "max position size" in str(e.value)                                              # 1 contract = $10 > $5 cap
    z = M.size(c, 100000, 99000, 10, bump=True); assert z["vol"] == 100 and z["bump"] is None   # above the minimum: untouched
    mn = dict(c, minNotional=20.0)                                                          # min notional: 2 contracts ($20)
    z = M.size(mn, 100000, 99000, 0.15, bump=True); assert z["vol"] == 2 and abs(z["risk"] - 0.2) < 1e-9 and z["bump"]["to_risk"] == 0.2
    assert M.min_vol(SMALL, 1.0) == 10 and M.ceil_vol(10.01, SMALL) == 11
    w = X.Weex(FakeWeex()).instrument("SOLUSDT"); z = M.size(w, 10, 9, 0.05, bump=True)     # WEEX min 0.1 SOL = $0.10 risk
    assert z["vol"] == 0.1 and z["bump"]["unit"] == "qty"

@pytest.fixture
def small():
    """SMALLUSDT: MEXC min 10 contracts of 1 coin, WEEX min 5 coins. Entry 1.0 / stop 0.9 -> MEXC min = $1.00 risk, WEEX min = $0.50."""
    CON["SMALL_USDT"] = SMALL; WXI["SMALLUSDT"] = dict(WXI["ONLYWXUSDT"], symbol="SMALLUSDT", minOrderSize=5); WXAPI.add("SMALLUSDT")
    yield
    CON.pop("SMALL_USDT", None); WXI.pop("SMALLUSDT", None); WXAPI.discard("SMALLUSDT")
def ssig(**kw): return sig(symbol="SMALLUSDT", entry=1.0, sl=0.9, tp=1.3, **kw)
def srow(): return [x for x in rows() if x["symbol"] == "SMALLUSDT"][-1]

def test_dry_run_bump_alert_shows_original_and_bumped(fresh, small):
    enable(risk_usdt=0.5); ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01)); r = srow()
    assert r["status"] == "open_order" and r["vol"] == 10 and abs(r["risk_usdt"] - 1.0) < 1e-9 and json.loads(r["note"])["bump"]["from_risk"] == 0.5
    t = [x for x in fresh if "Min-order bump" in x][-1]
    assert "5 → 10 ct" in t and "$0.50 → <b>$1.00</b>" in t and "cap $1 = 2× risk" in t and "limit placed" in t
    monkeypatch_prices = A.prices; A.prices = lambda syms: {}
    try: v = A.view(); assert v["recent"] == [] and v["active"][0]["bump"]["to_vol"] == 10
    finally: A.prices = monkeypatch_prices

def test_bump_over_cap_is_skipped_with_alert_and_tries_next_exchange(fresh, small):
    enable(risk_usdt=0.4, exchanges="mexc"); ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01)); r = srow()     # MEXC min $1.00 > auto cap $0.80
    assert r["status"] == "skipped" and "bump cap $0.8" in json.loads(r["note"])["skip"] and any("skipped (minimum order)" in t and "bump cap $0.8" in t for t in fresh)
    A.save_settings(dict(exchanges="mexc,weex")); fw = FakeWeex(private_ok=False); ssig()                   # WEEX min $0.50 fits -> WEEX takes it
    A.tick(cl={"mexc": Fake(False), "weex": fw}, px_fn=PX(1.01)); r = srow()
    assert r["exchange"] == "weex" and r["status"] == "open_order" and r["vol"] == 5 and fw.calls == []
    assert any("Backup exchange" in t and "bump cap" in t and "Min-order bump</b> on WEEX" in t and "4 → 5 qty" in t for t in fresh)
    with db.conn() as c: c.execute("UPDATE autotrade SET status='cancelled'")                               # free the coin (one auto trade per coin)
    A.save_settings(dict(bump_max_risk_usdt=0.45)); ssig()                                                  # neither fits
    A.tick(cl={"mexc": Fake(False), "weex": fw}, px_fn=PX(1.01)); r = srow(); n = json.loads(r["note"])["skip"]
    assert r["status"] == "skipped" and "MEXC" in n and "WEEX" in n and "$0.45" in n

def test_bump_off_skips_below_minimum(fresh, small):
    enable(risk_usdt=0.5, exchanges="mexc"); A.tg_command("/autotrade minbump off"); assert A.settings(0)["min_bump"] is False
    ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01)); r = srow()
    assert r["status"] == "skipped" and "bump is off" in json.loads(r["note"])["skip"] and any("skipped (minimum order)" in t for t in fresh)

def test_bump_margin_cap_and_balance(monkeypatch, small):
    enable(risk_usdt=0.5, leverage=1, bump_max_margin_usdt=5, exchanges="mexc"); ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01))
    r = srow(); assert r["status"] == "skipped" and "margin cap $5" in json.loads(r["note"])["skip"]       # 10 ct = $10 at 1x
    A.save_settings(dict(leverage=5)); ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01))                       # $2 margin at 5x
    r = srow(); assert r["status"] == "open_order" and r["vol"] == 10
    class Poor(Fake):
        def usdt_available(self): self._p("usdt_available"); return 1.0
    monkeypatch.setattr(M, "key_present", lambda: True); A.save_settings(dict(dry_run=False, max_open=5))
    with db.conn() as c: c.execute("UPDATE autotrade SET status='cancelled'")
    ssig(); fk = Poor(); A.tick(cl={"mexc": fk}, px_fn=PX(1.01)); r = srow()
    assert r["status"] == "skipped" and "bumped minimum order" in json.loads(r["note"])["skip"] and fk.n("create_order") == 0

def test_live_bumped_order_and_fill_alert(monkeypatch, fresh, small):
    live(monkeypatch, risk_usdt=0.5, order_type="market", bump_max_risk_usdt=1.5); ssig(status="open"); fk = Fake()
    A.tick(cl=fk, px_fn=PX(1.01)); (b,) = creates(fk)
    assert b["vol"] == 10 and b["symbol"] == "SMALL_USDT" and any("Min-order bump" in t and "order placed" in t for t in fresh)
    fk.positions = [dict(symbol="SMALL_USDT", positionType=1, holdVol=10, positionId=1)]
    A.tick(cl=fk, px_fn=PX(1.01)); assert srow()["status"] == "filled" and any("filled" in t and "Min-order bump" in t for t in fresh)

def test_bump_commands_panel_and_validation():
    A.tg_command("/autotrade bumprisk 2"); A.tg_command("/autotrade bumpmargin 5"); s = A.settings(0)
    assert s["bump_max_risk_usdt"] == 2 and s["bump_max_margin_usdt"] == 5 and s["min_bump"] is True
    t, mk = A.tg_command("/autotrade"); assert "Min-order bump: <b>ON</b>" in t and "risk ≤ $2" in t and "margin ≤ $5" in t
    A.tg_callback("at:mb"); assert A.settings(0)["min_bump"] is False; A.tg_callback("at:mb"); assert A.settings(0)["min_bump"] is True
    A.tg_command("/autotrade bumprisk 0"); assert A.bump_cap(A.settings(0)) == 2 * A.settings(0)["risk_usdt"] and "auto 2× risk" in A.panel_text()
    assert "⚠️" in A.tg_command("/autotrade bumprisk -1")[0]
    with pytest.raises(ValueError): A.save_settings(dict(bump_max_margin_usdt="x"))
    s = A.settings(0); assert s["enabled"] is False and s["dry_run"] is True
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "desk.html")).read()
    assert "min_bump" in src and "bump_max_risk_usdt" in src and "exchange_modes" in src and "atSet({exchanges:" in src


# =================== t158u: sizing modes – $ risk (default) · fixed margin · % of balance ===================
def test_sizing_defaults_migration_and_commands():
    db.kv_set(A.KEY, json.dumps(dict(enabled=False, dry_run=True, primary_exchange="mexc", failover=None, ex_on={"mexc": True, "weex": True}, risk_usdt=0.5)))
    A._S.update(t=0, v=None); s = A.settings(0)
    assert s["sizing_mode"] == "risk" and s["margin_usdt"] == 1.0 and s["risk_pct"] == 1.0 and s["risk_usdt"] == 0.5 and s["exchanges"] == ["mexc", "weex"]
    A.tg_command("/autotrade margin 5"); A.tg_command("/autotrade pct 2"); s = A.settings(0)
    assert s["margin_usdt"] == 5 and s["risk_pct"] == 2 and s["sizing_mode"] == "risk"          # numbers never switch the mode
    for w, want in (("margin", "margin"), ("pct", "pct"), ("%", "pct"), ("risk", "risk")):
        A.tg_command("/autotrade sizing " + w); assert A.settings(0)["sizing_mode"] == want
    assert "⚠️" in A.tg_command("/autotrade sizing kelly")[0] and "⚠️" in A.tg_command("/autotrade pct 50")[0] and "⚠️" in A.tg_command("/autotrade margin 0")[0]
    for cb in ("margin", "pct", "risk"): A.tg_callback("at:sm:" + cb); assert A.settings(0)["sizing_mode"] == cb
    t, mk = A.tg_command("/autotrade"); cbs = [b["callback_data"] for row in mk["inline_keyboard"] for b in row]
    assert {"at:sm:risk", "at:sm:margin", "at:sm:pct"} <= set(cbs) and "$ risk 0.5 USDT" in t and "sizing risk|margin|pct" in t
    A.tg_command("/autotrade sizing margin"); assert "fixed margin 5 USDT × leverage" in A.panel_text() and "2× the trade's risk" in A.panel_text()
    A.tg_command("/autotrade sizing pct"); assert "2% of the exchange's available USDT" in A.panel_text()
    s = A.settings(0); assert s["enabled"] is False and s["dry_run"] is True and s["risk_usdt"] == 0.5
    v = (lambda: (setattr(A, "prices", lambda q: {}), A.view())[1])(); assert [m["value"] for m in v["sizing_modes"]] == ["risk", "margin", "pct"] and v["sizing_desc"]
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "desk.html")).read()
    assert "sizing_mode:" in src and "margin_usdt:+$('atmg').value" in src and "risk_pct:+$('atpc').value" in src

def test_fixed_margin_mode_size_and_alert(fresh):
    enable(sizing_mode="margin", margin_usdt=20, leverage=5); sig(); A.tick(cl=Fake(False), px_fn=PX(100500.0)); r = rows()[0]
    assert r["status"] == "open_order" and r["vol"] == 10 and abs(r["notional"] - 100) < 1e-9 and abs(r["risk_usdt"] - 1.0) < 1e-9 and r["leverage"] == 5
    assert json.loads(r["note"])["sizing"] == dict(mode="margin", margin_target=20.0, lev=5)
    t = [x for x in fresh if "Fixed margin" in x][-1]
    assert "Fixed margin $20 × 5x → $100.00 position" in t and "risk $1.00 at the stop" in t and "$100.00 position · risk 1.00 USDT" in t

def test_fixed_margin_max_leverage_guard_and_caps(monkeypatch):
    c = dict(CON["BTC_USDT"]); ad = X.Mexc(Fake())
    z = A._sized(ad, "BTC_USDT", c, 100000, 99000, "long", dict(A.settings(0), sizing_mode="margin", margin_usdt=10, lev_mode="max"))
    assert z["leverage"] == 66 and not X.liq_inside(100000, 99000, 66, X.DEFAULT_MMR, "long") and X.liq_inside(100000, 99000, 67, X.DEFAULT_MMR, "long")
    assert z["vol"] == 66 and abs(z["margin"] - 10) < 1e-9 and abs(z["risk"] - 6.6) < 1e-9      # $10 x 66 = $660 -> 66 ct of $10; risk $6.60 at the 1% stop
    z = A._sized(ad, "BTC_USDT", c, 100000, 99000, "long", dict(A.settings(0), sizing_mode="margin", margin_usdt=20, leverage=5, max_notional_usdt=50))
    assert z["vol"] == 5 and abs(z["notional"] - 50) < 1e-9                                    # max position size still caps
    tiered = dict(c, riskBaseVol=100, riskIncrVol=100, riskIncrImr=0.01, riskIncrMmr=0.0, riskLevelLimit=5, initialMarginRate=0.002)
    z = A._sized(ad, "BTC_USDT", tiered, 100000, 50000, "long", dict(A.settings(0), sizing_mode="margin", margin_usdt=10, lev_mode="max"))
    assert z["leverage"] == 1 and z["vol"] == 1 and abs(z["risk"] - 5) < 1e-9                   # 50% stop: guard -> 1x, $10 position

def test_fixed_margin_bump_and_caps(fresh, small):
    enable(sizing_mode="margin", margin_usdt=0.1, leverage=5, exchanges="mexc"); ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01))
    r = srow(); assert r["status"] == "skipped" and "bump cap" in json.loads(r["note"])["skip"]        # $0.5 position -> 10-ct min risks $1 > 2 x $0.05
    A.save_settings(dict(bump_max_risk_usdt=2, bump_max_margin_usdt=1)); ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01))
    r = srow(); assert r["status"] == "skipped" and "margin cap $1" in json.loads(r["note"])["skip"]   # bumped margin $2 > $1
    A.save_settings(dict(bump_max_margin_usdt=0)); ssig(); A.tick(cl=Fake(False), px_fn=PX(1.01)); r = srow()
    assert r["status"] == "open_order" and r["vol"] == 10 and any("Min-order bump" in t and "Fixed margin" in t for t in fresh)

def test_pct_mode_dry_run_needs_readable_balance(monkeypatch, fresh):
    enable(sizing_mode="pct", risk_pct=1, exchanges="mexc"); sig(); A.tick(cl=Fake(False), px_fn=PX(100500.0)); r = rows()[0]
    assert r["status"] == "skipped" and "no MEXC API key" in json.loads(r["note"])["skip"] and any("skipped (balance)" in t for t in fresh)
    monkeypatch.setattr(M, "key_present", lambda: True); fk = Fake()                          # key present: read-only balance call only
    sig(symbol="SOLUSDT", entry=150, sl=148, tp=156); A.tick(cl=fk, px_fn=PX(150.2)); r = [x for x in rows() if x["symbol"] == "SOLUSDT"][0]
    assert r["dry"] == 1 and r["status"] == "open_order" and abs(r["risk_usdt"] - 100) < 1e-6 and r["vol"] == 500   # 1% of 10,000 / $2 stop = 50 SOL = 500 ct
    assert [c[0] for c in fk.calls] == ["usdt_available"] and json.loads(r["note"])["sizing"]["balance"] == 10000.0
    assert any("1% of MEXC balance $10,000.00 = $100.00 risk" in t for t in fresh)
    assert json.loads(db.kv_get(A.BAL_KEY))["mexc"]["v"] == 10000.0
    class NoBal(Fake):
        def usdt_available(self): raise M.NoPermission(700007, "No permission")
    with db.conn() as c: c.execute("UPDATE autotrade SET status='cancelled'")
    sig(symbol="SOLUSDT", entry=150, sl=148, tp=156); A.tick(cl=NoBal(), px_fn=PX(150.2)); r = rows()[-1]
    assert r["status"] == "skipped" and "can't read the balance" in json.loads(r["note"])["skip"]

def test_pct_mode_next_exchange_and_live_balance_check(monkeypatch, fresh):
    both_live(monkeypatch, sizing_mode="pct", risk_pct=1)
    class NoBal(Fake):
        def usdt_available(self): raise M.NoPermission(700007, "No permission")
    sig(); fk, fw = NoBal(), FakeWeex(); A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "weex" and r["status"] == "open_order" and creates(fk) == [] and creates(fw)[0]["quantity"] == "0.1"   # 1% of WEEX 10,000 / 1000
    assert fw.n("usdt_available") == 1                                                          # read once, reused for the margin check
    A.save_settings(dict(risk_pct=20, exchanges="mexc", leverage=5)); A.STATE["perm"].clear()
    class Poor(Fake):
        def usdt_available(self): self._p("usdt_available"); return 100.0
    sig(symbol="SOLUSDT", entry=150, sl=148, tp=156); fp = Poor(); A.tick(cl={"mexc": fp}, px_fn=PX(150.2)); r = rows()[-1]
    assert r["status"] == "skipped" and "not enough USDT margin" in json.loads(r["note"])["skip"] and creates(fp) == []   # $20 risk -> $1,500 / 5x > $100

def test_size_line_in_margin_and_pct_modes():
    sizing = _sz_reset(); A.save_settings(dict(sizing_mode="margin", margin_usdt=20, leverage=5)); _sz_reset()
    assert sizing.line("BTCUSDT", 100000, 99000) == "📐 <b>Size</b>  0.001 BTC · $100.00 position · risk $1.00 · ≤5x → margin ~$20.00"
    A.save_settings(dict(leverage="max")); _sz_reset(); assert "margin $20 × ~66x est." in sizing.line("BTCUSDT", 100000, 99000)
    A.save_settings(dict(sizing_mode="pct", risk_pct=1, leverage=5)); _sz_reset()
    assert sizing.line("BTCUSDT", 100000, 99000) == "📐 <b>Size</b>  risk 1% of balance (balance not read yet)"
    db.kv_set(A.BAL_KEY, json.dumps({"mexc": {"v": 1000.0, "t": "x"}})); _sz_reset()
    assert sizing.line("BTCUSDT", 100000, 99000) == "📐 <b>Size</b>  0.01 BTC · $1,000.00 position · risk $10.00 (1% of MEXC $1,000.00) · ≤5x → margin ~$200.00"
    A.save_settings(dict(sizing_mode="risk", risk_usdt=10)); _sz_reset()
    assert sizing.line("BTCUSDT", 100000, 99000) == "📐 <b>Size</b>  0.01 BTC · $1,000.00 position · risk $10.00 · ≤5x → margin ~$200.00"


# =================== t160u: follow the signal's entry type, never limit -> market; 70%-to-target cancel rule ===================
def test_entry_type_mapping():
    assert {k: A.entry_type(k) for k in A.STRATS} == {"DON20": "market", "DON28": "market", "BRK": "market", "PAT-WEDGE": "market", "CHK": "market",
                                                      "FVG-D1": "limit", "FVG-PLAN": "limit", "PAT-TRIPLE-C": "market", "FVG+TREND": "limit"}
    assert A.entry_type("SOMETHING-NEW") == "limit"

def test_limit_signal_gets_limit_and_market_signal_gets_market(monkeypatch):
    live(monkeypatch, order_type="auto", limit_timeout_min=1440, strategies=["FVG-D1", "BRK"]); fk = Fake()
    sig(strategy="FVG-D1", entry=100000.0, sl=99000.0, tp=103000.0); sig(symbol="SOLUSDT", strategy="BRK", entry=150, sl=148, tp=156, status="open")
    A.tick(cl=fk, px_fn=lambda q: {"BTCUSDT": 100500.0, "SOLUSDT": 150.2})
    b = {c["symbol"]: c for c in creates(fk)}
    assert b["BTC_USDT"]["type"] == 1 and b["BTC_USDT"]["price"] == 100000.0 and b["SOL_USDT"]["type"] == 5
    r = {x["symbol"]: x for x in rows()}; assert r["BTCUSDT"]["order_type"] == "limit" and r["SOLUSDT"]["order_type"] == "market"
    assert json.loads(r["BTCUSDT"]["note"])["entry_type"] == "limit" and json.loads(r["BTCUSDT"]["note"])["timeout"] == 1440
    sig(symbol="ETHUSDT", strategy="BRK", entry=150, sl=148, tp=156, status="open"); CON["ETH_USDT"] = dict(CON["SOL_USDT"], symbol="ETH_USDT")
    try:
        A.tick(cl=fk, px_fn=lambda q: {"BTCUSDT": 100500.0, "SOLUSDT": 150.2, "ETHUSDT": 151.2})   # 0.6R drift on a market signal -> skipped
        e = [x for x in rows() if x["symbol"] == "ETHUSDT"][0]; assert e["status"] == "skipped" and "moved 0.60R" in json.loads(e["note"])["skip"]
    finally: CON.pop("ETH_USDT")
    A.save_settings(dict(order_type="limit")); sig(symbol="XRPUSDT", strategy="BRK", entry=1.0, sl=0.9, tp=1.3, status="open")
    CON["XRP_USDT"] = dict(CON["NOAPI_USDT"], symbol="XRP_USDT", apiAllowed=True)
    try:
        A.tick(cl=fk, px_fn=lambda q: {"BTCUSDT": 100500.0, "SOLUSDT": 150.2, "XRPUSDT": 1.01}); x = creates(fk)[-1]
        assert x["symbol"] == "XRP_USDT" and x["type"] == 1                                            # "Limit only": market signal as limit
    finally: CON.pop("XRP_USDT")

def test_unfilled_limit_never_goes_market_and_waits_past_15_min(monkeypatch, fresh):
    live(monkeypatch, order_type="auto", limit_timeout_min=1440, strategies=["FVG-D1"]); sig(strategy="FVG-D1"); fk = Fake(); now = datetime.now(timezone.utc)
    A.tick(cl=fk, px_fn=PX(100500.0), now=now)
    A.tick(cl=fk, px_fn=PX(100500.0), now=now + timedelta(minutes=20)); assert rows()[0]["status"] == "open_order" and fk.n("cancel_ext") == 0
    A.tick(cl=fk, px_fn=PX(100500.0), now=now + timedelta(hours=25)); r = rows()[0]          # 24 h max wait (safety net)
    assert r["status"] == "cancelled" and "max wait (24 h)" in r["exit_reason"] and fk.n("cancel_ext") == 1
    assert [c["type"] for c in creates(fk)] == [1] and any("limit not filled, cancelled" in t and "never sent at market" in t for t in fresh)

def test_limit_cancelled_at_70pct_of_target(monkeypatch, fresh):
    live(monkeypatch, order_type="auto", limit_timeout_min=1440, strategies=["FVG+TREND"]); sig(strategy="FVG+TREND"); fk = Fake()         # entry 100000, TP 103000 -> 70% = 102100
    A.tick(cl=fk, px_fn=PX(100500.0)); A.tick(cl=fk, px_fn=PX(102000.0)); assert rows()[0]["status"] == "open_order"   # 67%: still open
    A.tick(cl=fk, px_fn=PX(102100.0)); r = rows()[0]
    assert r["status"] == "cancelled" and "reached 70% of target without fill" in r["exit_reason"] and fk.n("cancel_ext") == 1
    assert any("limit cancelled, price reached 70% of target without fill" in t for t in fresh) and [c["type"] for c in creates(fk)] == [1]

def test_cancel_pct_setting_tp1_for_ptp_and_short_side(monkeypatch, fresh):
    A.tg_command("/autotrade cancelpct 50"); assert A.settings(0)["cancel_pct"] == 50
    assert "⚠️" in A.tg_command("/autotrade cancelpct 5")[0] and "⚠️" in A.tg_command("/autotrade cancelpct 150")[0]
    enable(order_type="auto", limit_timeout_min=1440, strategies=["FVG-D1"]); sig(strategy="FVG-D1", direction="short", entry=100000.0, sl=101000.0, tp=97000.0)   # TP1 = 1.5R = 98500
    A.tick(cl=Fake(False), px_fn=PX(99400.0)); assert rows()[0]["status"] == "open_order"      # 40% of the way to TP1
    A.tick(cl=Fake(False), px_fn=PX(99250.0)); r = rows()[0]                                    # 50% to TP1 (98500), only 25% to TP
    assert r["status"] == "cancelled" and "50% of target" in r["exit_reason"] and "98,500" in r["exit_reason"].replace("98500", "98,500")
    assert A.target_of("FVG-D1", 100000, 101000, 97000) == 98500 and A.target_of("FVG+TREND", 100000, 99000, 103000) == 103000 and A.target_of("DON20", 1, 0.9, None) is None

def test_no_limit_placed_when_price_already_past_the_cancel_threshold(fresh):
    enable(order_type="auto", limit_timeout_min=1440, strategies=["FVG-PLAN"]); sig(strategy="FVG-PLAN", entry=100000.0, sl=99000.0, tp=103000.0)
    A.tick(cl=Fake(False), px_fn=PX(100500.0)); assert rows()[0]["status"] == "open_order"
    A.tick(cl=Fake(False), px_fn=PX(101000.0)); assert rows()[0]["status"] == "open_order"            # 33% of the way: still open
    sig(symbol="SOLUSDT", strategy="FVG-PLAN", entry=150, sl=148, tp=156); A.tick(cl=Fake(False), px_fn=lambda q: {"BTCUSDT": 101000.0, "SOLUSDT": 154.5})
    s2 = [x for x in rows() if x["symbol"] == "SOLUSDT"][0]
    assert s2["status"] == "skipped" and "already 75% of the way to the target" in json.loads(s2["note"])["skip"]

def test_live_stop_hit_before_fill_cancels(monkeypatch, fresh):
    live(monkeypatch, order_type="auto", limit_timeout_min=1440, strategies=["FVG-D1"]); sig(strategy="FVG-D1", direction="short", entry=100000.0, sl=101000.0, tp=97000.0); fk = Fake()
    A.tick(cl=fk, px_fn=PX(99800.0)); assert rows()[0]["status"] == "open_order"
    A.tick(cl=fk, px_fn=PX(101100.0)); r = rows()[0]                                              # gap through the entry to the stop, limit never filled
    assert r["status"] == "cancelled" and "hit the stop before fill" in r["exit_reason"] and fk.n("cancel_ext") == 1 and len(creates(fk)) == 1

def test_partial_fill_kept_rest_cancelled_at_70pct(monkeypatch, fresh):
    live(monkeypatch, order_type="auto", limit_timeout_min=1440, strategies=["FVG+TREND"]); sig(strategy="FVG+TREND"); fk = Fake()
    A.tick(cl=fk, px_fn=PX(100500.0)); r = rows()[0]; fk.orders[r["ext_oid"]].update(dealVol=40, dealAvgPrice=100000.0)   # 40 of 100 filled
    A.tick(cl=fk, px_fn=PX(102500.0)); r = rows()[0]
    assert r["status"] == "filled" and r["vol"] == 40 and abs(r["risk_usdt"] - 4.0) < 1e-9 and fk.n("cancel_ext") == 1
    assert any("limit partly filled, rest cancelled" in t and "40 of 100 filled" in t and "never sent at market" in t for t in fresh)
    assert [c["type"] for c in creates(fk)] == [1]

def test_order_type_and_wait_migration_and_commands(fresh):
    db.kv_set(A.KEY, json.dumps(dict(enabled=False, dry_run=True, order_type="limit_market", limit_timeout_min=15, risk_usdt=0.5, lev_mode="max", max_open=50)))
    A._S.update(t=0, v=None); s = A.settings(0)
    assert s["order_type"] == "auto" and s["limit_timeout_min"] == 1440 and s["cancel_pct"] == 70 and s["enabled"] is False and s["dry_run"] is True
    assert s["risk_usdt"] == 0.5 and s["lev_mode"] == "max" and s["max_open"] == 50
    for ot, want in (("market", "auto"), ("limit", "limit"), ("auto", "auto")):
        db.kv_set(A.KEY, json.dumps(dict(order_type=ot))); A._S.update(t=0, v=None); assert A.settings(0)["order_type"] == want
    A.save_settings(dict(limit_timeout_min=15)); A._S.update(t=0, v=None); assert A.settings(0)["limit_timeout_min"] == 15   # explicit choice kept
    t, _ = A.tg_command("/autotrade limit_market"); assert "removed" in t and A.settings(0)["order_type"] == "auto"
    A.tg_command("/autotrade limit"); assert A.settings(0)["order_type"] == "limit"
    A.tg_command("/autotrade market"); assert A.settings(0)["order_type"] == "auto"
    A.tg_callback("at:ot:limit"); assert A.settings(0)["order_type"] == "limit"; A.tg_callback("at:ot:limit_market"); assert A.settings(0)["order_type"] == "auto"
    A.tg_command("/autotrade maxwait 48"); assert A.settings(0)["limit_timeout_min"] == 2880
    A.tg_command("/autotrade maxwait 0"); assert A.settings(0)["limit_timeout_min"] == 0
    assert "⚠️" in A.tg_command("/autotrade maxwait 500")[0]
    A.tg_callback("at:to:1440"); t, mk = A.tg_command("/autotrade")
    assert "follow the signal" in t and "70% of the way to the target" in t and "max wait 24 h" in t and "Limit → Market" not in t
    with pytest.raises(ValueError): A.save_settings(dict(order_type="limit_market_x"))
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "desk.html")).read()
    assert "limit_market" not in src and "cancel_pct:+$('atcp').value" in src and "Follow the signal" in src

# ---------- breakeven+ stop (t163u) ----------
def test_be_plus_levels_use_final_tp_not_tp1():
    """Trigger and lock are measured to the furthest/final TP (the signal TP), not TP1."""
    assert A.final_tp({"tp": 103000}, {"tp": 104000}) == 104000          # src (live signal) wins: furthest current TP
    assert A.final_tp({"tp": 103000}, {"sl": 99000}) == 103000
    assert A.final_tp({"tp": None, "strategy": "DON20"}) is None
    long = A.be_prices("long", 100000, 103000, 30, 5)
    assert abs(long["trigger"] - 100900) < 1e-9 and abs(long["sl"] - 100150) < 1e-9
    short = A.be_prices("short", 100000, 97000, 30, 5)
    assert abs(short["trigger"] - 99100) < 1e-9 and abs(short["sl"] - 99850) < 1e-9
    assert A.be_prices("long", 100000, 99000, 30, 5) is None              # TP on the wrong side
    assert A.sl_better("long", 100150, 99000) and not A.sl_better("long", 98000, 99000)
    assert A.sl_better("short", 99850, 101000) and not A.sl_better("short", 101500, 101000)
    # CHK: TP1 is 1.5R = 103000 if sl=98000 entry=100000, but final TP is 106000 — trigger uses 106000
    lv = A.be_prices("long", 100000, 106000, 30, 5)
    assert abs(lv["trigger"] - 101800) < 1e-9 and abs(lv["sl"] - 100300) < 1e-9
    assert A.target_of("CHK", 100000, 98000, 106000) == 103000            # cancel rule still uses TP1; BE+ does not

def _fill_dry(symbol="BTCUSDT", direction="long", entry=100000.0, sl=99000.0, tp=103000.0, px_fill=100100.0, **kw):
    enable(strategies=["BRK"], **kw); i = sig(symbol=symbol, direction=direction, entry=entry, sl=sl, tp=tp, status="pending")
    fk = Fake(private_ok=False)
    A.tick(cl=fk, px_fn=PX(px_fill if direction == "long" else (entry + (entry - px_fill))))
    db.update(i, status="open", filled_at=datetime.now(timezone.utc).isoformat())
    A.tick(cl=fk, px_fn=PX(px_fill)); r = rows()[-1]
    assert r["status"] == "filled" and r["dry"] == 1
    return i, fk, r

def test_be_plus_dry_run_long(fresh):
    i, fk, r = _fill_dry()
    A.tick(cl=fk, px_fn=PX(100800.0)); r = rows()[0]                      # 26.7% of the way: not yet
    assert r["sl"] == 99000.0 and not json.loads(r["note"] or "{}").get("be_plus") and fk.calls == []
    A.tick(cl=fk, px_fn=PX(100900.0)); r = rows()[0]                      # 30% exactly
    assert r["sl"] == 100150.0 and json.loads(r["note"])["be_plus"] and fk.calls == []
    assert any("would move SL to" in t and "100,150" in t.replace("100150", "100,150") and "Profit locked in" in t and "DRY-RUN" in t for t in fresh)
    A.tick(cl=fk, px_fn=PX(101500.0)); assert rows()[0]["sl"] == 100150.0  # already moved: no second move
    # signal row unchanged (isolation)
    assert db.get(i)["sl"] == 99000.0 and db.get(i)["status"] == "open"

def test_be_plus_dry_run_short(fresh):
    i, fk, r = _fill_dry(direction="short", sl=101000.0, tp=97000.0, px_fill=99900.0)
    A.tick(cl=fk, px_fn=PX(99100.0)); r = rows()[0]
    assert r["sl"] == 99850.0 and json.loads(r["note"])["be_plus"] and fk.calls == []
    assert any("would move SL to" in t and "99,850" in t.replace("99850", "99,850") for t in fresh)

def test_be_plus_trigger_not_reached_and_off(fresh):
    _fill_dry(); A.tick(cl=Fake(False), px_fn=PX(100899.0)); r = rows()[0]  # just under 30%
    assert r["sl"] == 99000.0 and not json.loads(r["note"] or "{}").get("be_plus")
    A.save_settings(dict(be_plus=False)); _fill_dry(symbol="SOLUSDT", entry=150, sl=148, tp=156, px_fill=150.1)
    A.tick(cl=Fake(False), px_fn=PX(155.0)); r = [x for x in rows() if x["symbol"] == "SOLUSDT"][0]
    assert r["sl"] == 148.0 and not json.loads(r["note"] or "{}").get("be_plus")

def test_be_plus_stop_already_better(fresh):
    enable(strategies=["BRK"]); i = sig(status="pending")
    A.tick(cl=Fake(False), px_fn=PX(100100.0)); db.update(i, status="open", filled_at=datetime.now(timezone.utc).isoformat())
    A.tick(cl=Fake(False), px_fn=PX(100100.0)); r = rows()[0]
    A._upd(r["id"], sl=100200.0)                                          # current stop already past the 5% lock (100150)
    A.tick(cl=Fake(False), px_fn=PX(101000.0)); r = rows()[0]
    assert r["sl"] == 100200.0 and json.loads(r["note"]).get("be_skip") == "stop already better"
    assert not any("would move SL to" in t for t in fresh)

def test_be_plus_live_mexc_amends_stop(monkeypatch, fresh):
    live(monkeypatch, order_type="auto", strategies=["BRK"]); i = sig(status="open"); fk = Fake()
    A.tick(cl=fk, px_fn=PX(100100.0)); r = rows()[0]
    fk.positions = [dict(symbol="BTC_USDT", positionType=1, holdVol=r["vol"], positionId=9, openType=1, holdAvgPrice=100100.0)]
    fk.stops = [dict(id=31, symbol="BTC_USDT", positionId=9, state=1)]
    A.tick(cl=fk, px_fn=PX(100100.0)); assert rows()[0]["status"] == "filled"
    A.tick(cl=fk, px_fn=PX(101000.0)); r = rows()[0]                      # fill 100100 → trigger 100970, lock 100245
    ch = [c for c in fk.calls if c[0] == "change_stop"]
    assert ch and ch[-1][2]["sl"] == 100245.0 and r["sl"] == 100245.0 and json.loads(r["note"])["be_plus"]
    assert any("breakeven+" in t and "stop moved" in t and "Profit locked in" in t and "MEXC" in t for t in fresh)
    n_ch = fk.n("change_stop")
    A.tick(cl=fk, px_fn=PX(101200.0)); assert fk.n("change_stop") == n_ch and rows()[0]["sl"] == 100245.0  # once only
    assert db.get(i)["sl"] == 99000.0                                     # signal tracker untouched

def test_be_plus_live_weex_amends_stop(monkeypatch, fresh):
    both_live(monkeypatch, order_type="auto", strategies=["BRK"]); A.save_settings(dict(exchanges="weex"))
    i = sig(status="open"); fw = FakeWeex(); fk = Fake()
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100100.0)); r = rows()[0]
    assert r["exchange"] == "weex"
    fw.pos = [dict(id=9, symbol="BTCUSDT", side="LONG", size=str(r["vol"]), openValue=str(100100.0 * r["vol"]), marginType="CROSSED")]
    fw.algos = [dict(algoId=11, symbol="BTCUSDT", positionSide="LONG", orderType="STOP_MARKET", algoStatus="UNTRIGGERED", reduceOnly=True),
                dict(algoId=12, symbol="BTCUSDT", positionSide="LONG", orderType="TAKE_PROFIT_MARKET", algoStatus="UNTRIGGERED", reduceOnly=True)]
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(100100.0)); assert rows()[0]["status"] == "filled"
    A.tick(cl={"mexc": fk, "weex": fw}, px_fn=PX(101000.0)); r = rows()[0]  # fill 100100 → trigger 100970, lock 100245
    mods = [c for c in fw.calls if c[0] == "modify_tpsl"]
    assert any(c[1] == (11, 100245.0) for c in mods) and r["sl"] == 100245.0 and json.loads(r["note"])["be_plus"]
    assert any("would move SL to" not in t and "breakeven+" in t and "WEEX" in t and "Profit locked in" in t for t in fresh)
    assert creates(fk) == []                                              # stayed on WEEX

def test_be_plus_amend_failure_keeps_old_stop(monkeypatch, fresh):
    live(monkeypatch, order_type="auto", strategies=["BRK"]); i = sig(status="open"); fk = Fake()
    A.tick(cl=fk, px_fn=PX(100100.0)); r = rows()[0]
    fk.positions = [dict(symbol="BTC_USDT", positionType=1, holdVol=r["vol"], positionId=9, openType=1, holdAvgPrice=100100.0)]
    fk.stops = [dict(id=31, symbol="BTC_USDT", positionId=9, state=1)]
    A.tick(cl=fk, px_fn=PX(100100.0)); fk.fail_change = M.MexcError(500, "plan amend failed", 500)
    A.tick(cl=fk, px_fn=PX(101000.0)); r = rows()[0]
    assert r["sl"] == 99000.0 and not json.loads(r["note"] or "{}").get("be_plus")   # old stop kept, not marked done
    assert any("breakeven+ stop not moved" in t and "kept" in t and "99000" in t.replace(",", "") for t in fresh)
    A.tick(cl=fk, px_fn=PX(101000.0)); r = rows()[0]                       # retry succeeds
    assert r["sl"] == 100245.0 and json.loads(r["note"])["be_plus"]
    ch = [c for c in fk.calls if c[0] == "change_stop"]
    assert len(ch) >= 2 and ch[-1][2]["sl"] == 100245.0

def test_be_plus_commands_defaults_miniapp_and_migration(fresh):
    s = A.settings(0)
    assert s["be_plus"] is True and s["be_trigger_pct"] == 30 and s["be_lock_pct"] == 5 and s["enabled"] is False and s["dry_run"] is True
    db.kv_set(A.KEY, json.dumps(dict(enabled=False, dry_run=True, risk_usdt=0.5, exchanges=["mexc", "weex"])))
    A._S.update(t=0, v=None); s = A.settings(0)
    assert s["be_plus"] is True and s["be_trigger_pct"] == 30 and s["be_lock_pct"] == 5 and s["enabled"] is False and s["dry_run"] is True
    A.tg_command("/autotrade be off"); assert A.settings(0)["be_plus"] is False
    A.tg_command("/autotrade be on"); A.tg_command("/autotrade betrigger 40"); A.tg_command("/autotrade belock 10")
    s = A.settings(0); assert s["be_plus"] is True and s["be_trigger_pct"] == 40 and s["be_lock_pct"] == 10
    assert "⚠️" in A.tg_command("/autotrade betrigger 5")[0] and "⚠️" in A.tg_command("/autotrade belock 40")[0]  # lock must be < trigger (still 40)
    A.tg_command("/autotrade belock 8"); A.tg_command("/autotrade betrigger 7")
    assert "⚠️" in A.tg_command("/autotrade betrigger 7")[0] and A.settings(0)["be_trigger_pct"] == 40
    A.tg_callback("at:be"); assert A.settings(0)["be_plus"] is False; A.tg_callback("at:be"); assert A.settings(0)["be_plus"] is True
    A.tg_command("/autotrade betrigger 30"); A.tg_command("/autotrade belock 5")
    t, mk = A.tg_command("/autotrade")
    assert "Breakeven+: <b>ON</b>" in t and "lock 5% of the final-TP distance" in t and "30%" in t and "be on|off" in t
    cbs = [b["callback_data"] for row in mk["inline_keyboard"] for b in row]
    assert "at:be" in cbs
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app", "desk.html")).read()
    assert "be_trigger_pct:+$('atbt').value" in src and "be_lock_pct:+$('atbl').value" in src and "atSet({be_plus:true})" in src
