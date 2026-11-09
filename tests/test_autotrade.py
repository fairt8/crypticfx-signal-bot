"""Auto-trade add-on tests (mocked MEXC, temp SQLite). Run: python -m pytest -q tests/test_autotrade.py
Never touches Telegram, Neon or MEXC: env is blanked before the app is imported."""
import os, sys, json, hmac, hashlib, threading, time
os.environ.update(DATABASE_URL="", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="1", MEXC_API_KEY="", MEXC_API_SECRET="", BYBIT_API_KEY="", BYBIT_API_SECRET="", AUTOTRADE_WORKER="0", ENABLE_SCHEDULER="0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import pytest
import requests
from app import config as C, db, don20, mexc as M, bybit as BY, exchanges as X, autotrade as A, telegram

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
    def change_stop(self, sid, sl=None, tp=None): self._p("change_stop", sid, sl=sl, tp=tp)
    def cancel_stops(self, pid): self._p("cancel_stops", pid)
    def n(self, name): return sum(1 for c in self.calls if c[0] == name)

@pytest.fixture(autouse=True)
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DB_PATH", str(tmp_path / "t.db"))
    db.init(); don20.init()
    A._S.update(t=0, v=None); A._TBL["ok"] = False; A._ERRSENT.clear()
    A.STATE.update(last_tick=None, last_result=None, backoff_until=0, idle_until=0); A.STATE["errors"].clear(); A.STATE["skips"].clear(); A.STATE.pop("loss_day", None)
    sent = []; monkeypatch.setattr(telegram, "send", lambda t, chat_id=None, html=False: sent.append(t) or True)
    monkeypatch.setattr(M, "key_present", lambda: False); monkeypatch.setattr(BY, "key_present", lambda: False)
    A.STATE["perm"].clear()
    yield sent

def sig(symbol="BTCUSDT", strategy="BRK", direction="long", entry=100000.0, sl=99000.0, tp=103000.0, status="pending", ct=None):
    s = dict(symbol=symbol, market="crypto", direction=direction, entry=entry, sl=sl, tp=tp, rr=3.0, confidence=50, in_session=1, reasons=["x"],
             htf_top=None, htf_bottom=None, htf_time=None, tap_time=None, confirm_time=ct or datetime.now(timezone.utc).isoformat(), price_now=entry,
             strategy=strategy, tags=[strategy], experimental=0, status=status, filled_at=datetime.now(timezone.utc).isoformat() if status == "open" else None)
    return db.insert(s)
def rows(): return A._q("SELECT * FROM autotrade ORDER BY id")
def enable(**kw):
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
    with pytest.raises(ValueError): A.save_settings(dict(limit_timeout_min=7))
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
    live(monkeypatch, order_type="market", strategies=["BRK", "FVG+TREND"]); fk = Fake(); fk.fair["BTC_USDT"] = 130000.0
    sig(status="open"); A.tick(cl=fk, px_fn=PX(100100.0))
    assert rows()[0]["status"] == "skipped" and "differs" in json.loads(rows()[0]["note"])["skip"]   # MEXC price far from Binance
    fk.fair.clear(); i = sig(symbol="SOLUSDT", strategy="FVG+TREND", entry=150, sl=148, tp=156, status="open")
    A.tick(cl=fk, px_fn=PX(150.1)); r = [x for x in rows() if x["symbol"] == "SOLUSDT"][0]
    assert r["status"] == "open_order" and r["order_type"] == "market"
    fk.positions = [dict(symbol="SOL_USDT", positionType=1, holdVol=r["vol"], positionId=9, openType=1, holdAvgPrice=150.1)]
    fk.stops = [dict(id=31, symbol="SOL_USDT", positionId=9, state=1)]
    A.tick(cl=fk, px_fn=PX(150.3)); assert [x for x in rows() if x["id"] == r["id"]][0]["status"] == "filled"
    db.update(i, sl=149.0, tp=153.0)                                   # bot moved stop/target (e.g. FVG+TREND final levels)
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
    A.tick(cl=fk, px_fn=lambda s: {"BTCUSDT": 101000.0, "SOLUSDT": 153.2})           # CHK TP1 (1.5R = 153) -> half + stop to entry
    r = [r for r in rows() if r["strategy"] == "CHK"][0]
    assert r["half_done"] == 1 and r["sl"] == r["fill_price"] and r["pnl_usdt"] > 0
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
        for mod in ("autotrade", "bybit", "exchanges", "mexc"): assert mod not in src, (f, mod)

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


# =================== Bybit backup exchange / failover ===================
BYI = {"BTCUSDT": dict(symbol="BTCUSDT", status="Trading", priceScale="2", priceFilter=dict(tickSize="0.10"), lotSizeFilter=dict(qtyStep="0.001", minOrderQty="0.001", maxMktOrderQty="100", minNotionalValue="5"), leverageFilter=dict(maxLeverage="100")),
       "SOLUSDT": dict(symbol="SOLUSDT", status="Trading", priceScale="3", priceFilter=dict(tickSize="0.010"), lotSizeFilter=dict(qtyStep="0.1", minOrderQty="0.1", maxMktOrderQty="10000", minNotionalValue="5"), leverageFilter=dict(maxLeverage="50")),
       "ONLYBYUSDT": dict(symbol="ONLYBYUSDT", status="Trading", priceScale="4", priceFilter=dict(tickSize="0.0001"), lotSizeFilter=dict(qtyStep="1", minOrderQty="1", maxMktOrderQty="1000000", minNotionalValue="5"), leverageFilter=dict(maxLeverage="25"))}

class FakeBybit:
    """Mock raw Bybit client (same methods as app.bybit.Client)."""
    def __init__(self, private_ok=True):
        self.private_ok = private_ok; self.calls = []; self.orders = {}; self.pos = []; self._idx = {}; self.down = None
    def _p(self, name, *a, **k):
        if not self.private_ok: raise AssertionError(f"private Bybit call in dry-run: {name}")
        if self.down: raise self.down
        self.calls.append((name, a, k))
    def ping(self):
        if self.down: raise self.down
        return True
    def instruments(self): return BYI
    def mark_price(self, sym): return None
    def usdt_available(self): self._p("usdt_available"); return 10000.0
    def positions(self): self._p("positions"); return list(self.pos)
    def set_leverage(self, sym, lev): self._p("set_leverage", sym, lev)
    def create_order(self, **b):
        self._p("create_order", **b); oid = "B" + str(len(self.orders) + 1)
        if not b.get("reduceOnly"): self.orders[b["orderLinkId"]] = dict(orderId=oid, orderStatus="Filled" if b["orderType"] == "Market" else "New", cumExecQty=b["qty"] if b["orderType"] == "Market" else "0", avgPrice=b.get("price") or "0")
        return oid
    def order_by_link(self, sym, link): self._p("order_by_link", sym, link); return self.orders.get(link)
    def cancel_link(self, sym, link):
        self._p("cancel_link", sym, link)
        if link in self.orders: self.orders[link]["orderStatus"] = "Cancelled"
    def trading_stop(self, sym, idx, sl=None, tp=None): self._p("trading_stop", sym, idx, sl=sl, tp=tp)
    def n(self, name): return sum(1 for c in self.calls if c[0] == name)

class DownMexc(Fake):
    """MEXC mock whose health ping fails."""
    def ping(self): raise requests.exceptions.ConnectTimeout("connect timeout")

def both_live(monkeypatch, **kw):
    monkeypatch.setattr(M, "key_present", lambda: True); monkeypatch.setattr(BY, "key_present", lambda: True)
    enable(**kw); return A.save_settings(dict(dry_run=False))
def creates(fk): return [c[2] for c in fk.calls if c[0] == "create_order"]

def test_bybit_signing_headers_and_query():
    class S:
        def __init__(s): s.req = None
        def request(s, method, url, headers=None, data=None, timeout=None):
            s.req = (method, url, headers, data)
            class R: status_code = 200; json = staticmethod(lambda: {"retCode": 0, "retMsg": "OK", "result": {"orderId": "o1", "list": []}})
            return R()
    se = S(); cl = BY.Client(key="BK", secret="BS", session=se, min_gap_s=0, recv_window=5000)
    assert "BK" not in repr(cl) and "BS" not in repr(cl)
    cl.private("GET", "/v5/order/realtime", params=dict(symbol="BTCUSDT", category="linear", orderLinkId="cfx1", cursor=None))
    m, url, h, data = se.req
    assert url.endswith("/v5/order/realtime?category=linear&orderLinkId=cfx1&symbol=BTCUSDT") and data is None
    assert h["X-BAPI-SIGN"] == hmac.new(b"BS", (h["X-BAPI-TIMESTAMP"] + "BK" + "5000" + "category=linear&orderLinkId=cfx1&symbol=BTCUSDT").encode(), hashlib.sha256).hexdigest()
    assert h["X-BAPI-API-KEY"] == "BK" and h["X-BAPI-RECV-WINDOW"] == "5000"
    assert cl.create_order(symbol="BTCUSDT", side="Buy", orderType="Limit", qty="0.01", price="100000", stopLoss=None) == "o1"
    m, url, h, data = se.req
    assert json.loads(data)["category"] == "linear" and "stopLoss" not in data
    assert h["X-BAPI-SIGN"] == hmac.new(b"BS", (h["X-BAPI-TIMESTAMP"] + "BK" + "5000" + data).encode(), hashlib.sha256).hexdigest()

def test_bybit_error_parsing():
    class R:
        def __init__(s, code, j): s.status_code = code; s._j = j
        def json(s): return s._j
    cl = BY.Client(key="a", secret="b")
    with pytest.raises(BY.RateLimited): cl._parse(R(200, {"retCode": 10006, "retMsg": "too many"}))
    with pytest.raises(BY.BybitError) as e: cl._parse(R(403, {}))
    assert X.kind(e.value) == "server"
    with pytest.raises(BY.BybitError) as e: cl._parse(R(200, {"retCode": 110007, "retMsg": "Available balance is insufficient"}))
    assert X.kind(e.value) is None
    assert X.kind(requests.exceptions.ConnectTimeout("x")) == "not_sent" and X.kind(requests.exceptions.ReadTimeout("x")) == "unknown"
    assert X.kind(M.MexcError(9999, "x")) == "server" and X.kind(M.MexcError(2005, "x")) is None and X.kind(ConnectionError("x")) == "unknown"

def test_bybit_precision_and_sizing():
    ad = X.Bybit(FakeBybit()); c = ad.instrument("BTCUSDT")
    assert c["volUnit"] == 0.001 and c["volScale"] == 3 and c["priceUnit"] == 0.1 and c["minNotional"] == 5
    z = M.size(c, 100000, 99000, 10.5); assert z["vol"] == 0.01 and abs(z["risk"] - 10) < 1e-9   # 0.0105 floored to the 0.001 step
    assert M.round_price(100000.06, c) == 100000.1 and BY.dstr(0.01) == "0.01" and BY.dstr(1e-05) == "0.00001" and BY.dstr(100000.0) == "100000"
    with pytest.raises(M.Skip): M.size(ad.instrument("SOLUSDT"), 10, 9, 0.2)   # 0.2 qty * $10 = $2 < $5 minimum order value
    with pytest.raises(M.NotListed): ad.instrument("NOPEUSDT")

def test_mexc_get_signing_includes_query_params():
    class S:
        def __init__(s): s.req = None
        def request(s, method, url, headers=None, data=None, timeout=None):
            s.req = (method, url, headers, data)
            class R: status_code = 200; json = staticmethod(lambda: {"success": True, "code": 0, "data": []})
            return R()
    se = S(); cl = M.Client(key="AK", secret="SK", session=se, min_gap_s=0)
    cl.open_orders("BTC_USDT")
    m, url, h, data = se.req
    assert url.endswith("/api/v1/private/order/list/open_orders/BTC_USDT?page_num=1&page_size=50")
    assert h["Signature"] == hmac.new(b"SK", ("AK" + h["Request-Time"] + "page_num=1&page_size=50").encode(), hashlib.sha256).hexdigest()
    assert h["Signature"] != hmac.new(b"SK", ("AK" + h["Request-Time"]).encode(), hashlib.sha256).hexdigest()   # params are signed (else 602)

def test_failover_when_mexc_health_check_fails(monkeypatch, fresh):
    both_live(monkeypatch); sig(); fk, fb = DownMexc(), FakeBybit()
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "bybit" and r["status"] == "open_order" and fk.n("create_order") == 0
    (b,) = creates(fb)
    assert b["side"] == "Buy" and b["orderType"] == "Limit" and b["qty"] == "0.01" and b["price"] == "100000" and b["positionIdx"] == 0
    assert b["tpslMode"] == "Full" and b["stopLoss"] == "99000" and b["takeProfit"] == "103000" and b["orderLinkId"] == r["ext_oid"] and len(b["orderLinkId"]) <= 36
    assert fb.n("set_leverage") == 1 and any("Backup" in t and "health check failed" in t for t in fresh)

def test_failover_when_connection_never_opened(monkeypatch):
    both_live(monkeypatch); sig(); fk, fb = Fake(), FakeBybit(); fk.fail_create = requests.exceptions.ConnectTimeout("connect timed out")
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0))
    assert len(rows()) == 1 and rows()[0]["exchange"] == "bybit" and fk.n("create_order") == 1 and fb.n("create_order") == 1
    assert fk.n("order_by_ext") == 1   # MEXC asked by client order id first

def test_failover_on_5xx_only_after_mexc_confirms_no_order(monkeypatch):
    both_live(monkeypatch); sig(); fk, fb = Fake(), FakeBybit(); fk.fail_create = M.MexcError(503, "Service Unavailable", 503)
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0))
    assert rows()[0]["exchange"] == "bybit" and fb.n("create_order") == 1

def test_no_failover_when_mexc_state_unknown(monkeypatch, fresh):
    both_live(monkeypatch); sig(); fk, fb = Fake(), FakeBybit(); fk.fail_create = requests.exceptions.ReadTimeout("read timed out")
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "mexc" and r["status"] == "placing" and fb.n("create_order") == 0 and any("state unknown" in t for t in fresh)
    fk.orders[r["ext_oid"]] = dict(orderId="777", state=2, dealVol=0)       # it had reached MEXC after all
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0))
    assert rows()[0]["status"] == "open_order" and rows()[0]["order_id"] == "777" and fb.n("create_order") == 0

def test_no_failover_when_5xx_and_lookup_fails(monkeypatch):
    both_live(monkeypatch); sig(); fb = FakeBybit()
    class F(Fake):
        def order_by_ext(self, sym, ext): raise requests.exceptions.ReadTimeout("lookup timed out")
    fk = F(); fk.fail_create = M.MexcError(500, "Internal error", 500)
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0))
    assert rows()[0]["exchange"] == "mexc" and rows()[0]["status"] == "placing" and fb.n("create_order") == 0

def test_business_rejection_does_not_fail_over(monkeypatch):
    both_live(monkeypatch); sig(); fk, fb = Fake(), FakeBybit(); fk.fail_create = M.MexcError(2005, "Balance insufficient")
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0))
    assert rows()[0]["status"] == "error" and rows()[0]["exchange"] == "mexc" and fb.n("create_order") == 0

def test_symbol_missing_on_mexc_routes_to_bybit(monkeypatch):
    both_live(monkeypatch); sig(symbol="ONLYBYUSDT", entry=1.0, sl=0.9, tp=1.3); fk, fb = Fake(), FakeBybit()
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(1.01)); r = rows()[0]
    assert r["exchange"] == "bybit" and r["contract"] == "ONLYBYUSDT" and fk.n("create_order") == 0 and creates(fb)[0]["qty"] == "100"

def test_failover_off_or_no_bybit_key(monkeypatch):
    both_live(monkeypatch); A.save_settings(dict(failover=False)); sig(); fk, fb = DownMexc(), FakeBybit()
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["status"] == "skipped" and "health check failed" in json.loads(r["note"])["skip"] and fb.calls == []
    A.save_settings(dict(failover=None)); monkeypatch.setattr(BY, "key_present", lambda: False)   # auto = on only with Bybit keys
    assert A.failover_on(A.settings(0)) is False and A.route(A.settings(0), {"mexc": 1, "bybit": 1}) == ["mexc"]

def test_exits_and_stops_managed_on_the_opening_exchange(monkeypatch):
    both_live(monkeypatch, order_type="market", strategies=["FVG+TREND"]); fk, fb = DownMexc(), FakeBybit()
    i = sig(symbol="SOLUSDT", strategy="FVG+TREND", entry=150, sl=148, tp=156, status="open")
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(150.1)); r = rows()[0]
    assert r["exchange"] == "bybit" and creates(fb)[0]["orderType"] == "Market" and creates(fb)[0]["timeInForce"] == "IOC"
    fk2 = Fake()                                                                     # MEXC is back: trade must stay on Bybit
    fb.pos = [dict(symbol="SOLUSDT", side="Buy", size=str(r["vol"]), positionIdx=0, avgPrice="150.1", tradeMode=1)]
    A.tick(cl={"mexc": fk2, "bybit": fb}, px_fn=PX(150.3)); assert rows()[0]["status"] == "filled"
    db.update(i, sl=149.0, tp=153.0); A.tick(cl={"mexc": fk2, "bybit": fb}, px_fn=PX(150.3))
    ts = [c for c in fb.calls if c[0] == "trading_stop"]; assert ts and ts[-1][2] == dict(sl=149.0, tp=153.0)
    db.update(i, status="sl", closed_at=datetime.now(timezone.utc).isoformat(), result_r=-1.0)
    A.tick(cl={"mexc": fk2, "bybit": fb}, px_fn=PX(148.9))
    close = [b for b in creates(fb) if b.get("reduceOnly")]
    assert close and close[-1]["side"] == "Sell" and close[-1]["orderType"] == "Market" and float(close[-1]["qty"]) == r["vol"]
    assert rows()[0]["status"] == "closed" and fk2.calls == [] and fk.calls == []

def test_exit_retries_when_opening_exchange_is_down(monkeypatch, fresh):
    both_live(monkeypatch, order_type="market"); i = sig(status="open"); fk, fb = Fake(), FakeBybit()
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100100.0)); assert rows()[0]["exchange"] == "mexc"
    fk.positions = [dict(symbol="BTC_USDT", positionType=1, holdVol=rows()[0]["vol"], positionId=1)]
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100100.0)); assert rows()[0]["status"] == "filled"
    db.update(i, status="tp", closed_at=datetime.now(timezone.utc).isoformat(), result_r=3.0)
    class Down(Fake):
        def open_positions(self, sym=None): raise requests.exceptions.ConnectionError("Failed to establish a new connection")
    dn = Down(); dn.orders = fk.orders
    A.tick(cl={"mexc": dn, "bybit": fb}, px_fn=PX(103100.0))
    assert rows()[0]["status"] == "filled" and fb.calls == [] and any("unreachable" in t and "still protect" in t for t in fresh)
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(103100.0))                     # back up -> closed on MEXC, never on Bybit
    assert rows()[0]["status"] == "closed" and any(b["side"] == 4 for b in creates(fk)) and fb.n("create_order") == 0

def test_mexc_700007_balance_permission_note(monkeypatch, fresh):
    both_live(monkeypatch); sig()
    class NoBal(Fake):
        def usdt_available(self): raise M.NoPermission(700007, "No permission to access the endpoint")
    fk = NoBal(); A.tick(cl={"mexc": fk, "bybit": FakeBybit()}, px_fn=PX(100500.0))
    assert rows()[0]["status"] == "open_order" and rows()[0]["exchange"] == "mexc"     # placed; MEXC itself checks margin
    assert any("View Account Details" in t for t in fresh) and "mexc" in A.STATE["perm"]
    monkeypatch.setattr(A, "prices", lambda syms: {s: 100500.0 for s in syms})
    v = A.view(); assert [e for e in v["exchanges"] if e["name"] == "mexc"][0]["perm_note"] and "700007" in A.panel_text()
    class R:
        status_code = 200
        def json(s): return {"success": False, "code": 700007, "message": "No permission"}
    with pytest.raises(M.NoPermission): M.Client(key="a", secret="b")._parse(R())

def test_dry_run_failover_uses_no_private_calls(monkeypatch):
    enable(); A.save_settings(dict(failover=True)); sig(); fk, fb = DownMexc(private_ok=False), FakeBybit(private_ok=False)
    A.tick(cl={"mexc": fk, "bybit": fb}, px_fn=PX(100500.0)); r = rows()[0]
    assert r["exchange"] == "bybit" and r["dry"] == 1 and r["vol"] == 0.01 and fb.calls == [] and fk.calls == []

def test_exchange_settings_and_panel(monkeypatch):
    s = A.settings(0); assert s["primary_exchange"] == "mexc" and s["failover"] is None and s["enabled"] is False and s["dry_run"] is True
    with pytest.raises(ValueError): A.save_settings(dict(primary_exchange="binance"))
    with pytest.raises(ValueError): A.save_settings(dict(ex_on={"mexc": False, "bybit": False}))
    A.tg_callback("at:px"); assert A.settings(0)["primary_exchange"] == "bybit"
    A.tg_command("/autotrade primary mexc"); A.tg_command("/autotrade failover off"); A.tg_command("/autotrade bybit off")
    s = A.settings(0); assert s["primary_exchange"] == "mexc" and s["failover"] is False and s["ex_on"] == {"mexc": True, "bybit": False}
    A.tg_callback("at:x:bybit"); A.tg_callback("at:fo"); s = A.settings(0); assert s["ex_on"]["bybit"] and s["failover"] is True
    t, mk = A.tg_command("/autotrade"); assert "Bybit" in t and any(b["callback_data"] == "at:fo" for row in mk["inline_keyboard"] for b in row)
    assert A.settings(0)["enabled"] is False   # exchange controls never switch auto-trade on

def test_old_rows_without_exchange_are_mexc(monkeypatch):
    A.ensure_table(); A._insert(source="sig", ref_id=5, strategy="BRK", symbol="BTCUSDT", direction="long", status="closed", dry=1, pnl_usdt=1.0, closed_at=datetime.now(timezone.utc).isoformat())
    assert A.exof(rows()[0]) == "mexc"
    A._TBL["ok"] = False; A.ensure_table(); A.ensure_table()   # migration is idempotent
