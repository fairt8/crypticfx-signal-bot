"""MEXC futures auto-trade add-on (user 2026-11-09), with Bybit as the BACKUP exchange (user 2026-11-09, t140u). READ-ONLY consumer of the signals the bot already generates.

Isolation (hard requirement): nothing in the scanner, outcome tracker, DON20/DON28 run, Telegram signal posts, dashboard or
Mini App signal lists calls into this module. It runs in its own daemon thread ("autotrade"), every step wrapped in
try/except, and only READS the signals / don20 / don28 tables. Its own writes go to the `autotrade` table and one kv key
(settings). If MEXC, the key, or this code fails, signals keep being generated, saved, tracked and alerted exactly as before.

Flow (every AUTOTRADE_POLL_S, default 60 s, leader instance only):
  new signal of an enabled crypto strategy (created after auto-trade / that strategy was switched on, <= 30 min old)
    -> size = risk USDT / stop distance (MEXC contract size, step, min qty, tick; optional max notional; leverage cap)
    -> limit at the signal entry (optional 5/10/15-min unfilled timeout) or market, isolated, SL/TP attached to the order
  then mirrors the bot's tracked trade: FVG+TREND final stop/target at fill, DON20/DON28 trailing stop (SL amended),
  CHK/FVG-D1 50% at TP1 + stop to entry, and a reduce-only close when the tracked trade closes. Unfilled limits are
  cancelled at the timeout or when the signal invalidates first.
Dry-run (default) logs/simulates the same orders without calling any private exchange endpoint.

Exchanges (app/exchanges.py): primary (default MEXC) and, with failover on (default: on once Bybit keys exist), the other
one as backup. A NEW order goes to the backup only when the primary can't take it with nothing executed there: failed
health check, unreachable / 5xx / maintenance before or on placement (confirmed by a client-order-id lookup when the
primary answers), or the symbol is not tradable on the primary. If the primary's state is UNKNOWN (timeout after the
order was sent) the signal is NOT sent to the backup (no double position); it is resolved by client order id later.
Every trade is managed on the exchange it was opened on; if that exchange is down its exits keep retrying every tick
(the exchange-side SL/TP still protect the position) and Telegram says so."""
import collections, json, os, secrets, threading, time
from datetime import datetime, timezone, timedelta
from . import db, mexc as M, bybit as B, exchanges as X

STRATS = ["DON20", "DON28", "BRK", "PAT-WEDGE", "CHK", "FVG-D1", "FVG-PLAN", "PAT-TRIPLE-C", "FVG+TREND"]   # crypto only; forex excluded
DON = ("DON20", "DON28")
TIMEOUTS = (0, 5, 10, 15)          # minutes; 0 = no timeout (cancel only when the signal invalidates)
ACTIVE = ("placing", "open_order", "filled")
SIG_DONE = ("tp", "sl", "be", "retired", "expired", "cancelled", "filtered")
KEY = "autotrade:settings"
POLL_S = int(os.getenv("AUTOTRADE_POLL_S", "60"))
MAX_AGE_MIN = int(os.getenv("AUTOTRADE_MAX_AGE_MIN", "30"))     # don't enter signals older than this
MAX_SLIP_R = float(os.getenv("AUTOTRADE_MAX_SLIP_R", "0.5"))    # market entry skipped if price moved more than this (R) from entry
MAX_PX_DEV = float(os.getenv("AUTOTRADE_MAX_PX_DEV", "0.02"))   # MEXC vs Binance price sanity (catches renamed / 1000x contracts)
FEE = float(os.getenv("AUTOTRADE_FEE", "0.0005"))               # MEXC API futures taker fee per side (announcement 2026-03-30)
DEFAULTS = dict(enabled=False, dry_run=True, strategies=[], risk_usdt=1.0, max_open=3, leverage=5, order_type="limit",
                limit_timeout_min=15, max_notional_usdt=0.0, daily_loss_usdt=0.0, enabled_at=None, strat_on={}, salt=None, updated_at=None,
                primary_exchange="mexc", failover=None, ex_on={"mexc": True, "bybit": True})   # failover None = on when Bybit keys exist
STATE = dict(last_tick=None, last_result=None, errors=collections.deque(maxlen=30), skips=collections.deque(maxlen=30), backoff_until=0, idle_until=0, perm={})
PERM_NOTE = {"mexc": ("MEXC key can't read the account balance (code 700007). In MEXC ▸ API Management edit this key and also tick "
                      "\"View Account Details\". Until then the margin pre-check is skipped and MEXC itself rejects an order if margin is short.")}
_S = {"t": 0, "v": None}; _LOCK = threading.RLock(); _TBL = {"ok": False}; _ERRSENT = {}

def utcnow(): return datetime.now(timezone.utc)
def iso(t): return t.isoformat()
def _ts(x):
    if not x: return None
    try:
        t = datetime.fromisoformat(str(x).replace("Z", "+00:00").replace(" ", "T"))
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except Exception: return None
def _err(where, e):
    msg = f"{where}: {type(e).__name__}: {str(e)[:200]}"
    STATE["errors"].append(dict(t=iso(utcnow()), msg=msg)); print(f"[autotrade] {msg}", flush=True); return msg

# ---------------- storage (own table only) ----------------
def ddl():
    ID = "SERIAL PRIMARY KEY" if db.PG else "INTEGER PRIMARY KEY"
    return f"""CREATE TABLE IF NOT EXISTS autotrade(id {ID}, created_at TEXT, updated_at TEXT, source TEXT, ref_id INTEGER,
      strategy TEXT, symbol TEXT, contract TEXT, direction TEXT, order_type TEXT, entry REAL, sl REAL, tp REAL, init_sl REAL,
      vol REAL, qty REAL, notional REAL, risk_usdt REAL, leverage INTEGER, ext_oid TEXT, order_id TEXT, position_id TEXT,
      status TEXT, dry INTEGER, filled_at TEXT, fill_price REAL, half_done INTEGER DEFAULT 0, closed_at TEXT, exit_price REAL,
      exit_reason TEXT, pnl_usdt REAL, note TEXT, exchange TEXT, UNIQUE(source, ref_id))"""
def ensure_table():
    if _TBL["ok"]: return
    with db.conn() as c:
        c.execute(ddl())
        if db.PG: c.execute("ALTER TABLE autotrade ADD COLUMN IF NOT EXISTS exchange TEXT")
        elif "exchange" not in {r[1] for r in c.execute("PRAGMA table_info(autotrade)").fetchall()}: c.execute("ALTER TABLE autotrade ADD COLUMN exchange TEXT")
    _TBL["ok"] = True
def exof(r): return (r.get("exchange") if isinstance(r, dict) else None) or "mexc"   # rows from before the Bybit backup are MEXC
def _q(sql, p=()):
    with db.conn() as c: return [dict(r) for r in c.execute(sql, p).fetchall()]
def _upd(i, **kw):
    kw["updated_at"] = iso(utcnow())
    with db.conn() as c: c.execute(f"UPDATE autotrade SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), i))
def _insert(**kw):
    kw.setdefault("created_at", iso(utcnow())); kw["updated_at"] = kw["created_at"]
    ks = list(kw)
    with db.conn() as c:
        cur = c.execute(f"INSERT INTO autotrade({','.join(ks)}) VALUES({','.join('?'*len(ks))}) ON CONFLICT(source, ref_id) DO NOTHING RETURNING id", tuple(kw[k] for k in ks))
        r = cur.fetchone()
    return (r["id"] if db.PG else r[0]) if r else None

# ---------------- settings (kv) ----------------
def settings(max_age=300):
    with _LOCK:
        if _S["v"] is not None and time.time() - _S["t"] < max_age: return dict(_S["v"])
        try: raw = db.kv_get(KEY)
        except Exception as e:
            if _S["v"] is not None: return dict(_S["v"])
            raise
        v = dict(DEFAULTS, **(json.loads(raw) if raw else {}))
        _S.update(t=time.time(), v=v); return dict(v)
def _num(x, lo, hi, name, kind=float):
    try: v = kind(x)
    except Exception: raise ValueError(f"{name} must be a number")
    if not (lo <= v <= hi): raise ValueError(f"{name} must be between {lo:g} and {hi:g}")
    return v
def validate(patch, cur):
    s = dict(cur); now = iso(utcnow())
    for k, v in (patch or {}).items():
        if k == "enabled":
            v = bool(v)
            if v and not s["enabled"]: s["enabled_at"] = now
            s["enabled"] = v
        elif k == "dry_run":
            v = bool(v)
            if not v and not any(X.key_present(x) for x in X.NAMES if (s.get("ex_on") or {}).get(x, True)):
                raise ValueError("Live mode needs an exchange key in the server env file (MEXC_API_KEY/MEXC_API_SECRET or BYBIT_API_KEY/BYBIT_API_SECRET). Dry-run stays on.")
            s["dry_run"] = v
        elif k == "primary_exchange":
            if v not in X.NAMES: raise ValueError("primary exchange must be mexc or bybit")
            s[k] = v
        elif k == "failover":
            s[k] = None if v is None else bool(v)
        elif k == "ex_on":
            if not isinstance(v, dict) or any(x not in X.NAMES for x in v): raise ValueError("ex_on must map mexc/bybit to on/off")
            on = dict(DEFAULTS["ex_on"], **(s.get("ex_on") or {})); on.update({x: bool(y) for x, y in v.items()})
            if not any(on.values()): raise ValueError("keep at least one exchange enabled")
            s[k] = on
        elif k == "strategies":
            bad = [x for x in v if x not in STRATS]
            if bad: raise ValueError(f"not an auto-trade strategy: {', '.join(bad)} (crypto only: {', '.join(STRATS)})")
            on = dict(s.get("strat_on") or {})
            for x in v:
                if x not in s["strategies"]: on[x] = now
            s["strategies"] = [x for x in STRATS if x in v]; s["strat_on"] = on
        elif k == "risk_usdt": s[k] = round(_num(v, 0.1, 100000, "Risk per trade (USDT)"), 4)
        elif k == "max_open": s[k] = _num(v, 1, 50, "Max open trades", int)
        elif k == "leverage": s[k] = _num(v, 1, 125, "Leverage cap", int)
        elif k == "order_type":
            if v not in ("limit", "market"): raise ValueError("order type must be limit or market")
            s[k] = v
        elif k == "limit_timeout_min":
            v = _num(v, 0, 15, "Limit timeout", int)
            if v not in TIMEOUTS: raise ValueError("limit timeout must be 5, 10, 15 or 0 (none)")
            s[k] = v
        elif k == "max_notional_usdt": s[k] = round(_num(v, 0, 10000000, "Max notional (USDT)"), 2)
        elif k == "daily_loss_usdt": s[k] = round(_num(v, 0, 10000000, "Daily loss limit (USDT)"), 2)
        else: raise ValueError(f"unknown setting: {k}")
    if not s.get("salt"): s["salt"] = secrets.token_hex(2)
    s["updated_at"] = now; return s
def save_settings(patch):
    with _LOCK:
        s = validate(patch, settings(max_age=0))
        db.kv_set(KEY, json.dumps(s)); _S.update(t=time.time(), v=s); STATE["idle_until"] = 0
        return dict(s)

# ---------------- clients / prices ----------------
_CL = {"c": None, "ads": None}
def client():
    if _CL["c"] is None: _CL["c"] = M.Client()
    return _CL["c"]
def adapters(cl=None):
    """{name: adapter}. cl: None (real clients), a MEXC-style client (tests), or a dict {name: client or adapter}."""
    if cl is None:
        if _CL["ads"] is None: _CL["ads"] = {"mexc": X.Mexc(client()), "bybit": X.Bybit(B.Client())}
        return _CL["ads"]
    if isinstance(cl, dict): return {k: X.wrap(k, v) for k, v in cl.items()}
    return {"mexc": X.wrap("mexc", cl)}
def failover_on(s): return bool(s["failover"]) if s.get("failover") is not None else B.key_present()
def ex_on(s, name): return bool(dict(DEFAULTS["ex_on"], **(s.get("ex_on") or {})).get(name, True))
def route(s, ads):
    """Exchanges to try for a NEW order, in order: primary, then the backup when failover is on."""
    pri = s.get("primary_exchange") or "mexc"; order = [pri] + ([x for x in X.NAMES if x != pri] if failover_on(s) else [])
    live = not s["dry_run"]
    return [x for x in order if x in ads and ex_on(s, x) and (not live or X.key_present(x))]
def prices(symbols):
    from . import trades
    return trades.prices(sorted(set(symbols)), [])

# ---------------- reading the bot's signals (read-only) ----------------
SIG_COLS = "id,symbol,market,direction,entry,sl,tp,rr,status,strategy,tags,created_at,filled_at,closed_at,result_r"
DON_COLS = "id,symbol,direction,signal_day,opened_at,entry,init_stop,stop,status,closed_at,exit_price,result_r"
def _eff(r):
    from . import strategies as SG
    return SG.eff(r.get("strategy"), (r.get("tags") or "").split(",") if isinstance(r.get("tags"), str) else r.get("tags"))
def load_sources(s, active, now):
    """Returns ({sig_id: row}, {('DON20', id): row}) for active auto rows + new candidates. One query per table."""
    since = iso(now - timedelta(minutes=MAX_AGE_MIN))
    want = set(s["strategies"]) if s["enabled"] else set()
    ids = [int(r["ref_id"]) for r in active if r["source"] == "sig"]
    sigs, dons = {}, {}
    cond, p = [], []
    if want - set(DON): cond.append("(created_at>=? AND market='crypto' AND status IN ('pending','open'))"); p.append(since)
    if ids: cond.append(f"id IN ({','.join('?'*len(ids))})"); p += ids
    if cond:
        for r in _q(f"SELECT {SIG_COLS} FROM signals WHERE " + " OR ".join(cond), tuple(p)): sigs[r["id"]] = r
    from . import don20
    for k in DON:
        ids = [int(r["ref_id"]) for r in active if r["source"] == k]; cond, p = [], []
        if k in want: cond.append("(opened_at>=? AND status='open')"); p.append(since)
        if ids: cond.append(f"id IN ({','.join('?'*len(ids))})"); p += ids
        if not cond: continue
        try:
            for r in _q(f"SELECT {DON_COLS} FROM {don20.TABLE[k]} WHERE " + " OR ".join(cond), tuple(p)): dons[(k, r["id"])] = r
        except Exception as e: _err(f"read {k}", e)
    return sigs, dons

# ---------------- helpers ----------------
def _sd(d): return 1 if d == "long" else -1
def _pnl(r, exit_px, qty=None):
    q = float(qty if qty is not None else r["qty"] or 0); f = float(r["fill_price"] or r["entry"])
    return _sd(r["direction"]) * (float(exit_px) - f) * q - FEE * q * (f + float(exit_px))
def _fmt(x):
    from .telegram import fmt_price
    try: return fmt_price(float(x))
    except Exception: return str(x)
def _hdr(r, icon, what):
    from .telegram import esc
    lb = X.LABEL.get(exof(r), "MEXC")
    return (f"{icon} <b>AUTO · {esc(what)}</b>{(' · 🧪 DRY-RUN · ' + lb) if r['dry'] else ' · ' + lb}\n"
            f"{'🟢 LONG' if r['direction']=='long' else '🔴 SHORT'} <b>{esc(r['symbol'])}</b> · {esc(r['strategy'])} · #{r['ref_id']}")
def _wat_day_start(now):
    w = now + timedelta(hours=1); return (w.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=1))

class Ctx:
    """Per-tick context: exchange adapters + lazily fetched positions (one call per exchange per tick)."""
    def __init__(self, ads, px, now): self.ads, self.px, self.now = ads, px, now; self._pos = {}; self.msgs = []
    @property
    def cl(self): return getattr(self.ads.get("mexc"), "cl", None)
    def ad(self, r_or_name):
        n = r_or_name if isinstance(r_or_name, str) else exof(r_or_name)
        a = self.ads.get(n)
        if a is None: raise RuntimeError(f"{X.LABEL.get(n, n)} adapter not available")
        return a
    def positions(self, ex):
        if ex not in self._pos: self._pos[ex] = self.ad(ex).positions() or []
        return self._pos[ex]
    def position(self, ex, con, direction):
        for p in self.positions(ex):
            if p.get("symbol") == con and p.get("direction") == direction and float(p.get("size") or 0) > 0: return p
        return None
    def msg(self, r, text): self.msgs.append((bool(r["dry"]), text))

def _close_live(ctx, r, vol, tag="x"):
    """Reduce-only market close of `vol` units of this auto position on ITS exchange. Returns True if an order was sent."""
    ex = exof(r); ad = ctx.ad(ex); con = r["contract"]; pos = ctx.position(ex, con, r["direction"])
    if not pos: return False
    vol = min(float(vol), float(pos.get("size") or 0))
    if vol <= 0: return False
    c = ad.instrument(con); p = ctx.px.get(r["symbol"]) or pos.get("avg") or r["entry"]
    ad.close(pos, M.floor_vol(vol, c), M.round_price(p, c), r["ext_oid"] + tag); return True
def _amend_live(ctx, r, sl, tp):
    ex = exof(r); ad = ctx.ad(ex); c = ad.instrument(r["contract"]); pos = ctx.position(ex, r["contract"], r["direction"])
    if not pos: return False
    ad.set_tpsl(pos, M.round_price(sl, c) if sl else None, M.round_price(tp, c) if tp else None); return True
def _finish(ctx, r, reason, exit_px, icon):
    pnl = (float(r["pnl_usdt"] or 0) if r["half_done"] else 0.0) + (_pnl(r, exit_px) if exit_px else 0.0)
    _upd(r["id"], status="closed", closed_at=iso(ctx.now), exit_price=exit_px, exit_reason=reason, pnl_usdt=round(pnl, 4))
    ctx.msg(r, _hdr(r, icon, f"closed · {reason}") + f"\n🚪 Exit ~{_fmt(exit_px)} · PnL <b>{pnl:+.2f} USDT</b> (est., after fees)")

# ---------------- manage one active auto trade (always on the exchange it was opened on) ----------------
def manage(ctx, r, src, s):
    now = ctx.now; live = not r["dry"]; don = r["source"] in DON; ex = exof(r); lb = X.LABEL.get(ex, ex)
    ad = ctx.ad(ex) if live else ctx.ads.get(ex)
    p = ctx.px.get(r["symbol"]); long = r["direction"] == "long"; sd = _sd(r["direction"])
    if r["status"] == "placing":   # live: create call outcome unknown (network) -> look it up by our idempotent client order id
        o = ad.order(r["contract"], r["ext_oid"])
        if o: _upd(r["id"], status="open_order", order_id=str(o.get("order_id"))); return
        if now - _ts(r["created_at"]) > timedelta(minutes=5): _upd(r["id"], status="error", note=f"order not confirmed by {lb}")
        return
    if r["status"] == "open_order":
        fill = None
        if live:
            o = ad.order(r["contract"], r["ext_oid"]) or {}
            st, dv = o.get("state"), float(o.get("filled") or 0)
            if st == "filled": fill = (float(o.get("avg") or r["entry"]), dv or float(r["vol"]))
            elif st == "cancelled":
                if dv > 0: fill = (float(o.get("avg") or r["entry"]), dv)
                else: _upd(r["id"], status="cancelled", closed_at=iso(now), exit_reason=f"cancelled on {lb}"); ctx.msg(r, _hdr(r, "✖️", f"limit cancelled on {lb}")); return
        else:   # dry: the limit fills when the bot's own tracker fills the signal, or the live price crosses the entry
            tracked = (not don) and src and src.get("filled_at") and src.get("status") in ("open", "tp", "sl", "be")
            crossed = p is not None and ((p <= r["entry"]) if long else (p >= r["entry"]))
            if tracked or crossed: fill = (float(r["entry"]), float(r["vol"]))
        if fill:
            cs = (r["qty"] / r["vol"]) if r["vol"] else 0
            _upd(r["id"], status="filled", filled_at=iso(now), fill_price=fill[0], vol=fill[1], qty=fill[1] * cs)
            ctx.msg(r, _hdr(r, "✅", "filled") + f"\n📍 {_fmt(fill[0])} · {fill[1]:g} {'contracts' if ex == 'mexc' else 'qty'}\n🛑 {_fmt(r['sl'])}" + (f"   🎯 {_fmt(r['tp'])}" if r["tp"] else "   🎯 trailing")); return
        reason = None
        try: to = int(json.loads(r.get("note") or "{}").get("timeout", 0))
        except Exception: to = 0
        if to and now - _ts(r["created_at"]) >= timedelta(minutes=to): reason = f"not filled in {to} min"
        elif src is None: reason = "signal no longer tracked"
        elif don and src.get("status") != "open": reason = "DON position closed before fill"
        elif not don and src.get("status") in SIG_DONE: reason = f"signal {src.get('status')}"
        elif p is not None and ((p <= r["sl"]) if long else (p >= r["sl"])): reason = "price hit the stop before fill"
        if reason:
            if live:
                ad.cancel(r["contract"], r["ext_oid"])
                o = ad.order(r["contract"], r["ext_oid"]) or {}
                if float(o.get("filled") or 0) > 0:   # filled in the race: keep the filled part as the position
                    cs = (r["qty"] / r["vol"]) if r["vol"] else 0; dv = float(o["filled"])
                    _upd(r["id"], status="filled", filled_at=iso(now), fill_price=float(o.get("avg") or r["entry"]), vol=dv, qty=dv * cs)
                    ctx.msg(r, _hdr(r, "✅", "partly filled before cancel") + f"\n{dv:g} filled"); return
            _upd(r["id"], status="cancelled", closed_at=iso(now), exit_reason=reason)
            ctx.msg(r, _hdr(r, "⌛", "limit cancelled") + f"\n<i>{reason}</i>")
        return
    if r["status"] != "filled": return
    # 1) the bot's tracked trade closed -> close ours (reduce-only)
    reason = exit_px = None
    if don:
        if src is None or src.get("status") != "open": reason, exit_px = "DON exit (trailing stop)", (src or {}).get("exit_price") or p
    elif src is None or src.get("status") in SIG_DONE:
        st = (src or {}).get("status")
        reason = {"tp": "target hit", "sl": "stop hit", "be": "runner stopped at entry"}.get(st, f"signal {st}")
        exit_px = {"tp": r["tp"], "sl": r["sl"], "be": r["fill_price"] or r["entry"]}.get(st) or p
    if reason:
        if live:
            if _close_live(ctx, r, r["vol"]): exit_px = p or exit_px
            try: pos = ctx.position(ex, r["contract"], r["direction"]); pos and ad.cancel_tpsl(pos)
            except Exception: pass
        _finish(ctx, r, reason, exit_px, "🏁"); return
    # 2) live: the exchange already closed it (attached SL/TP triggered, liquidation, manual close)
    if live and not ctx.position(ex, r["contract"], r["direction"]):
        near = min([x for x in (r["sl"], r["tp"]) if x], key=lambda x: abs(x - (p or x)))
        _finish(ctx, r, f"closed on {lb} (stop/target)", near, "🏁"); return
    # 3) CHK / FVG-D1: 50% at TP1 (1.5R) and stop to entry, like the bot's tracked outcome
    from . import config as C
    if r["strategy"] in C.PTP_STRATS and not r["half_done"] and r["tp"] and p is not None:
        R = abs(r["entry"] - r["init_sl"]); tp1 = r["entry"] + sd * 1.5 * R
        if R and abs(r["tp"] - r["entry"]) > 1.5 * R + 1e-12 and ((p >= tp1) if long else (p <= tp1)):
            half = r["vol"] / 2
            if live:
                c = ad.instrument(r["contract"]); half = M.floor_vol(half, c)
                if half >= float(c.get("minVol") or 0) and half > 0: _close_live(ctx, r, half, "h")
                else: half = 0
                _amend_live(ctx, r, r["entry"], r["tp"])
            cs = (r["qty"] / r["vol"]) if r["vol"] else 0; part = _pnl(r, tp1, half * cs) if half else 0.0
            _upd(r["id"], half_done=1, sl=r["fill_price"] or r["entry"], vol=r["vol"] - half, qty=(r["vol"] - half) * cs, pnl_usdt=round(part, 4))
            ctx.msg(r, _hdr(r, "🎯", "TP1 · 50% closed, stop to entry") + f"\n+{part:.2f} USDT (est.)"); return
    # 4) follow the bot's stop/target (FVG+TREND final levels at fill, DON trailing stop)
    want_sl = (src.get("stop") if don else (r["sl"] if r["half_done"] else src.get("sl")))
    want_tp = None if don else src.get("tp")
    if want_sl and (abs(float(want_sl) - float(r["sl"] or 0)) > 1e-12 or (want_tp and abs(float(want_tp) - float(r["tp"] or 0)) > 1e-12)):
        if live: _amend_live(ctx, r, want_sl, want_tp)
        _upd(r["id"], sl=float(want_sl), tp=float(want_tp) if want_tp else r["tp"])

# ---------------- open a new auto trade ----------------
def candidates(s, sigs, dons, known):
    out = []; on = s.get("strat_on") or {}
    def since(k): return max(filter(None, [_ts(s.get("enabled_at")), _ts(on.get(k))]), default=None)
    for r in sigs.values():
        k = _eff(r)
        if k not in s["strategies"] or k in DON or ("sig", r["id"]) in known or r.get("market") != "crypto": continue
        if r.get("status") not in ("pending", "open"): continue
        t = _ts(r.get("created_at")); sk = since(k)
        if sk and t and t < sk: continue
        out.append(dict(source="sig", ref_id=r["id"], strategy=k, symbol=r["symbol"], direction=r["direction"], entry=float(r["entry"]),
                        sl=float(r["sl"]), tp=float(r["tp"]) if r.get("tp") else None, t=t))
    for (k, i), r in dons.items():
        if k not in s["strategies"] or (k, i) in known or r.get("status") != "open": continue
        t = _ts(r.get("opened_at")); sk = since(k)
        if sk and t and t < sk: continue
        out.append(dict(source=k, ref_id=i, strategy=k, symbol=r["symbol"], direction=r["direction"], entry=float(r["entry"]),
                        sl=float(r["stop"]), tp=None, t=t))
    out.sort(key=lambda c: c["t"] or utcnow()); return out

def _perm(ctx, ex, s):
    """Remember + (max every 12 h, live only) tell the user that the key lacks the balance permission."""
    STATE["perm"][ex] = PERM_NOTE.get(ex, f"{X.LABEL.get(ex, ex)} key lacks a permission")
    k = ("perm", ex)
    if time.time() - _ERRSENT.get(k, 0) > 12 * 3600:
        _ERRSENT[k] = time.time(); ctx.msgs.append((s["dry_run"], "🔑 <b>AUTO · key permission</b>\n" + STATE["perm"][ex]))

def open_trade(ctx, s, cnd):
    """Route a new order: primary first, backup only when the primary can't take it with nothing executed there."""
    order = route(s, ctx.ads); why = []; rid = None
    if not order: raise M.Skip("no exchange enabled" + ("" if s["dry_run"] else " with an API key"))
    for ex in order:
        ad = ctx.ads[ex]
        if not ad.healthy(): why.append(f"{ad.label} health check failed" + (f" ({ad.health().get('why')})" if ad.health().get("why") else "")); continue
        try: return _open_on(ctx, s, cnd, ad, rid, why)
        except X.Unavailable as e:
            why.append(str(e)); rid = e.row_id or rid
    msg = "; ".join(why) or "no exchange available"
    if rid:   # a placement failed with nothing executed and no backup could take it
        _upd(rid, status="error", closed_at=iso(ctx.now), note=json.dumps(dict(error=msg[:300])))
        ctx.msgs.append((s["dry_run"], f"⚠️ <b>AUTO · not placed</b> {cnd['symbol']} · {cnd['strategy']} #{cnd['ref_id']}\n<i>{msg[:300]}</i>"))
        return None
    raise M.Skip(msg)

def _open_on(ctx, s, cnd, ad, rid, why):
    now = ctx.now; live = not s["dry_run"]; ex = ad.name
    def down(e, what):
        ad.mark_down(e); return X.Unavailable(f"{ad.label} {what} ({X.short(e)})", row_id=rid)
    con = ad.symbol_of(cnd["symbol"])
    if not con: raise M.Skip("not a USDT pair")
    try: c = ad.instrument(con)
    except M.NotListed as e: raise X.Unavailable(str(e), row_id=rid)
    except (M.Skip, M.RateLimited, B.RateLimited): raise
    except Exception as e:
        if X.kind(e): raise down(e, "unreachable")
        raise
    p = ctx.px.get(cnd["symbol"]); long = cnd["direction"] == "long"; entry, sl, tp = cnd["entry"], cnd["sl"], cnd["tp"]; R = abs(entry - sl)
    if p is None: raise M.Skip("no live price")
    if (p <= sl) if long else (p >= sl): raise M.Skip("price already beyond the stop")
    if tp and ((p >= tp) if long else (p <= tp)): raise M.Skip("price already beyond the target")
    market = s["order_type"] == "market"
    if market and R and abs(p - entry) > MAX_SLIP_R * R: raise M.Skip(f"price moved {abs(p-entry)/R:.2f}R from the entry")
    ref = p if market else entry
    z = M.size(c, ref, sl, s["risk_usdt"], s.get("max_notional_usdt") or 0, s["leverage"])
    if live:
        try:
            fp = ad.fair_price(con)
            if fp and abs(fp - p) / p > MAX_PX_DEV: raise M.Skip(f"{ad.label} price {fp:g} differs from Binance {p:g} by {abs(fp-p)/p*100:.1f}% (different contract)")
            if ctx.position(ex, con, "long") or ctx.position(ex, con, "short"): raise M.Skip(f"there is already a {ad.label} position on {con} (manual?)")
            try: av = ad.usdt_available(); STATE["perm"].pop(ex, None)
            except M.NoPermission: av = None; _perm(ctx, ex, s)
            if av is not None and av < z["margin"] * 1.05: raise M.Skip(f"not enough USDT margin on {ad.label} ({av:.2f} available, {z['margin']:.2f} needed)")
        except (M.Skip, M.RateLimited, B.RateLimited): raise
        except Exception as e:
            if X.kind(e): raise down(e, "unreachable before the order")
            raise
    tag = "s" if cnd["source"] == "sig" else cnd["source"][-2:]
    ext = ad.client_id(s.get("salt"), tag, cnd["ref_id"])
    to = 0 if market else int(s.get("limit_timeout_min") or 0)
    via = f" via {ad.label} (backup)" if why else ""
    row = dict(strategy=cnd["strategy"], symbol=cnd["symbol"], contract=con, direction=cnd["direction"], exchange=ex,
               order_type="market" if market else "limit", entry=M.round_price(ref, c), sl=M.round_price(sl, c), tp=M.round_price(tp, c) if tp else None,
               init_sl=float(sl), vol=z["vol"], qty=z["qty"], notional=z["notional"], risk_usdt=z["risk"], leverage=z["leverage"], ext_oid=ext,
               dry=0 if live else 1, note=json.dumps(dict(timeout=to, **({"failover": "; ".join(why)[:200]} if why else {}))))
    full = dict(row, source=cnd["source"], ref_id=cnd["ref_id"])
    fo_line = ("\n↪️ <b>Backup exchange</b>: " + "; ".join(why)[:220]) if why else ""
    if not live:   # dry-run: no private call; market fills at the live price now, limit waits for the fill
        row.update(status="filled" if market else "open_order")
        if market: row.update(fill_price=row["entry"], filled_at=iso(now))
        if rid: _upd(rid, **row); i = rid
        else: i = _insert(source=cnd["source"], ref_id=cnd["ref_id"], **row)
        if i and (market or why): ctx.msg(full, _hdr(full, "✅" if market else "📝", ("filled (market)" if market else "limit placed") + via) + f"\n📍 {_fmt(row['entry'])} · {z['vol']:g} · risk {z['risk']:.2f} USDT" + fo_line)
        print(f"[autotrade] DRY {ex} {row['order_type']} {row['direction']} {con} vol={z['vol']:g} @ {row['entry']} sl={row['sl']} tp={row['tp']} ({cnd['strategy']} #{cnd['ref_id']})", flush=True)
        return i
    if rid: _upd(rid, status="placing", **row); i = rid
    else:
        i = _insert(source=cnd["source"], ref_id=cnd["ref_id"], status="placing", **row)
        if not i: return None   # already handled (idempotent: one auto trade per signal, on one exchange)
    try:
        oid = ad.place_open(con, cnd["direction"], z["vol"], row["entry"], market, z["leverage"], row["sl"], row["tp"], ext)
        _upd(i, status="open_order", order_id=oid)
        print(f"[autotrade] LIVE {ex} {row['order_type']} {row['direction']} {con} vol={z['vol']:g} @ {row['entry']} ({cnd['strategy']} #{cnd['ref_id']}) order {oid}", flush=True)
        if why: ctx.msg(full, _hdr(full, "↪️", f"order placed{via}") + fo_line)
        return i
    except (M.RateLimited, B.RateLimited): raise   # stays 'placing'; resolved by client order id next tick
    except Exception as e:
        k = X.kind(e)
        if k is None and isinstance(e, (M.MexcError, B.BybitError)):   # a definitive business rejection: no failover
            _upd(i, status="error", note=json.dumps(dict(timeout=to, error=f"{ad.label} {e.code}: {e.msg}"[:200])))
            ctx.msg(full, _hdr(full, "⚠️", "order rejected") + f"\n<code>{e.code}</code> {str(e.msg)[:150]}"); return i
        try: o = ad.order(con, ext); known = True             # did it reach the exchange? (idempotent client order id)
        except Exception: o, known = None, False
        if o:
            _upd(i, status="open_order", order_id=str(o.get("order_id"))); return i
        if k in ("not_sent", "server") and (known or k == "not_sent"):
            ad.mark_down(e)
            raise X.Unavailable(f"{ad.label} order failed ({X.short(e)}); {'confirmed no order there' if known else 'connection never opened'}", row_id=i)
        # state UNKNOWN (timeout after send / unexpected error): never send this signal to the backup
        _err(f"open {cnd['symbol']} on {ad.label}: state unknown, no failover", e)
        _upd(i, note=json.dumps(dict(timeout=to, unknown=f"{X.short(e)}"[:200])))
        ctx.msg(full, _hdr(full, "⏳", f"{ad.label} order state unknown") + f"\n<i>{X.short(e)[:150]}</i>\nNot sent to the backup exchange, to avoid a double position. Checking {ad.label} by order id next minute.")
        return i

def daily_pnl(now, dry):
    t0 = iso(_wat_day_start(now))
    rs = _q("SELECT pnl_usdt FROM autotrade WHERE status='closed' AND closed_at>=? AND dry=?", (t0, 1 if dry else 0))
    return sum(float(r["pnl_usdt"] or 0) for r in rs)

# ---------------- one tick ----------------
def tick(cl=None, px_fn=None, now=None):
    now = now or utcnow(); s = settings()
    if not s["enabled"] and time.time() < STATE["idle_until"]: return dict(idle=True)
    ensure_table()
    rows = _q("SELECT * FROM autotrade WHERE status IN ('placing','open_order','filled') OR created_at>=?", (iso(now - timedelta(days=2)),))
    active = [r for r in rows if r["status"] in ACTIVE]
    if not s["enabled"] and not active:
        STATE["idle_until"] = time.time() + 600; return dict(idle=True)
    ads = adapters(cl); px_fn = px_fn or prices
    sigs, dons = load_sources(s, active, now)
    known = {(r["source"], int(r["ref_id"])) for r in rows}
    cands = candidates(s, sigs, dons, known) if s["enabled"] else []
    px = px_fn({r["symbol"] for r in active} | {c["symbol"] for c in cands}) if (active or cands) else {}
    ctx = Ctx(ads, px, now); res = dict(active=len(active), candidates=len(cands), opened=0, skipped=0, errors=0)
    for r in active:
        src = sigs.get(int(r["ref_id"])) if r["source"] == "sig" else dons.get((r["source"], int(r["ref_id"])))
        try: manage(ctx, r, src, s)
        except (M.RateLimited, B.RateLimited) as e: _err("rate limit", e); STATE["backoff_until"] = time.time() + 120; break
        except Exception as e:
            res["errors"] += 1; ex = exof(r); lb = X.LABEL.get(ex, ex); m = _err(f"manage #{r['id']} {r['symbol']} on {lb}", e)
            if X.kind(e):   # the opening exchange is down: keep retrying its exits/updates; its own SL/TP orders still protect it
                if ex in ads: ads[ex].mark_down(e)
                k = (ex, "down")
                if time.time() - _ERRSENT.get(k, 0) > 3600:
                    _ERRSENT[k] = time.time()
                    ctx.msgs.append((bool(r["dry"]), f"⚠️ <b>AUTO · {lb} unreachable</b>\nOpen auto trades on {lb} are managed only on {lb}: exits and stop updates "
                                    f"retry every {POLL_S}s. The stop-loss / take-profit already placed on {lb} still protect them.\n<code>{X.short(e)[:150]}</code>"))
            else:
                k = (r["id"], type(e).__name__)
                if time.time() - _ERRSENT.get(k, 0) > 3600: _ERRSENT[k] = time.time(); ctx.msg(r, _hdr(r, "⚠️", "auto-trade error") + f"\n<code>{m[-180:]}</code>")
    if s["enabled"] and cands and time.time() >= STATE["backoff_until"]:
        lim = float(s.get("daily_loss_usdt") or 0)
        if lim and daily_pnl(now, s["dry_run"]) <= -lim:
            day = _wat_day_start(now).date().isoformat()
            if STATE.get("loss_day") != day:
                STATE["loss_day"] = day
                ctx.msgs.append((s["dry_run"], f"🛑 <b>AUTO · daily loss limit hit</b> ({lim:g} USDT). No new auto trades until 00:00 WAT."))
            cands = []
        n_open = len([r for r in active if r["status"] in ACTIVE]); held = {r["symbol"] for r in active}
        for cnd in cands:
            if n_open >= int(s["max_open"]): STATE["skips"].append(dict(t=iso(now), sym=cnd["symbol"], k=cnd["strategy"], why="max open reached")); break
            if cnd["symbol"] in held: STATE["skips"].append(dict(t=iso(now), sym=cnd["symbol"], k=cnd["strategy"], why="already an auto trade on this coin")); continue
            try:
                if open_trade(ctx, s, cnd): n_open += 1; held.add(cnd["symbol"]); res["opened"] += 1
            except M.Skip as e:
                res["skipped"] += 1; STATE["skips"].append(dict(t=iso(now), sym=cnd["symbol"], k=cnd["strategy"], why=str(e)))
                try: _insert(source=cnd["source"], ref_id=cnd["ref_id"], strategy=cnd["strategy"], symbol=cnd["symbol"], direction=cnd["direction"],
                             entry=cnd["entry"], sl=cnd["sl"], tp=cnd["tp"], status="skipped", dry=1 if s["dry_run"] else 0, note=json.dumps(dict(skip=str(e)[:200])))
                except Exception as x: _err("record skip", x)
            except (M.RateLimited, B.RateLimited) as e: _err("rate limit", e); STATE["backoff_until"] = time.time() + 120; break
            except Exception as e: res["errors"] += 1; _err(f"open {cnd['symbol']}", e)
    notify(ctx.msgs, s)
    STATE.update(last_tick=iso(now), last_result=res); return res

def notify(msgs, s):
    """Telegram notes on fill / cancel / exit / error, only while auto-trade is on (live positions are always reported)."""
    out = [t for dry, t in msgs if s["enabled"] or not dry]
    if not out: return
    try:
        from . import telegram
        for t in out[:8]: telegram.send(t, html=True)
        if len(out) > 8: telegram.send(f"🤖 AUTO · +{len(out)-8} more updates – Mini App ▸ Auto", html=True)
    except Exception as e: _err("telegram", e)

# ---------------- flatten all (separate, confirmed action) ----------------
def flatten(cl=None, px_fn=None, now=None):
    """Switch auto-trade OFF, cancel every pending auto limit and close every auto position (reduce-only market).
    Only touches positions this add-on opened (each on its own exchange); manual positions are left alone."""
    now = now or utcnow(); ensure_table(); save_settings(dict(enabled=False))
    rows = _q("SELECT * FROM autotrade WHERE status IN ('placing','open_order','filled')")
    ads = adapters(cl); px = (px_fn or prices)({r["symbol"] for r in rows}) if rows else {}
    ctx = Ctx(ads, px, now); out = dict(cancelled=0, closed=0, errors=[])
    for r in rows:
        try:
            if r["status"] in ("placing", "open_order"):
                if not r["dry"]: ctx.ad(r).cancel(r["contract"], r["ext_oid"])
                _upd(r["id"], status="cancelled", closed_at=iso(now), exit_reason="flatten"); out["cancelled"] += 1
            else:
                if not r["dry"]: _close_live(ctx, r, r["vol"])
                _finish(ctx, r, "flatten", px.get(r["symbol"]) or r["fill_price"] or r["entry"], "🛑"); out["closed"] += 1
        except Exception as e: out["errors"].append(_err(f"flatten #{r['id']}", e))
    return out

# ---------------- worker (own thread; never touches the scanner) ----------------
_started = {"v": False}
def loop(is_leader):
    while True:
        try:
            if time.time() >= STATE["backoff_until"] and is_leader(): tick()
        except BaseException as e: _err("tick", e)
        time.sleep(POLL_S)
def start(is_leader):
    if _started["v"] or os.getenv("AUTOTRADE_WORKER", "1") != "1": return
    _started["v"] = True; threading.Thread(target=loop, args=(is_leader,), daemon=True, name="autotrade").start()

# ---------------- views (Mini App / Telegram) ----------------
def view():
    from . import strategies as SG
    s = settings(); ensure_table()
    rows = _q("SELECT * FROM autotrade ORDER BY id DESC LIMIT 300")
    act = [r for r in rows if r["status"] in ACTIVE]
    px = prices({r["symbol"] for r in act if r["status"] == "filled"}) if act else {}
    for r in act:
        q = px.get(r["symbol"])
        if r["status"] == "filled" and q: r["price_now"] = q; r["upnl_usdt"] = round(_pnl(r, q) + (float(r["pnl_usdt"] or 0) if r["half_done"] else 0), 4)
    def summ(dry):
        cl = [r for r in rows if r["status"] == "closed" and bool(r["dry"]) == dry]
        t0 = _wat_day_start(utcnow()); td = [r for r in cl if (_ts(r["closed_at"]) or t0) >= t0]
        w = sum(1 for r in cl if (r["pnl_usdt"] or 0) > 0)
        return dict(closed=len(cl), pnl_usdt=round(sum(float(r["pnl_usdt"] or 0) for r in cl), 2), today_usdt=round(sum(float(r["pnl_usdt"] or 0) for r in td), 2),
                    win_rate=round(100 * w / len(cl), 1) if cl else None, open=sum(1 for r in act if bool(r["dry"]) == dry and r["status"] == "filled"),
                    pending=sum(1 for r in act if bool(r["dry"]) == dry and r["status"] != "filled"),
                    upnl_usdt=round(sum(r.get("upnl_usdt") or 0 for r in act if bool(r["dry"]) == dry), 2))
    pub = {k: v for k, v in s.items() if k not in ("salt",)}
    for r in rows:
        try: n = json.loads(r.get("note") or "{}"); r["skip"] = n.get("skip"); r["error"] = n.get("error"); r["timeout"] = n.get("timeout")
        except Exception: pass
    exs = []
    for n in X.NAMES:
        h = (_CL["ads"] or {}).get(n); h = h.health() if h else {}
        exs.append(dict(name=n, label=X.LABEL[n], key_present=X.key_present(n), enabled=ex_on(s, n), primary=(s.get("primary_exchange") or "mexc") == n,
                        healthy=h.get("ok"), checked_at=datetime.fromtimestamp(h["t"], timezone.utc).isoformat() if h.get("t") else None, why=h.get("why"),
                        perm_note=STATE["perm"].get(n)))
    for r in rows: r["exchange"] = exof(r)
    return dict(settings=pub, key_present=M.key_present(), exchanges=exs, failover=failover_on(s), route=[X.LABEL[x] for x in route(s, {n: 1 for n in X.NAMES})], strategies=[dict(key=k, short=SG.short(k), tier=SG.status(k), on=k in s["strategies"]) for k in STRATS],
                timeouts=list(TIMEOUTS), active=act, recent=[r for r in rows if r["status"] not in ACTIVE][:60], live=summ(False), dry=summ(True),
                worker=dict(last_tick=STATE["last_tick"], last_result=STATE["last_result"], poll_s=POLL_S, errors=list(STATE["errors"])[-8:], skips=list(STATE["skips"])[-10:]),
                exchange=dict(name=" → ".join(X.LABEL[x] for x in route(dict(s, dry_run=True), {n: 1 for n in X.NAMES})) or "none", base=M.BASE,
                              order_api="MEXC USDT-M perpetual (primary by default) · Bybit V5 USDT linear perpetual (backup)"))

def panel_text():
    from .telegram import esc
    s = settings(); v = None
    try: v = view()
    except Exception as e: _err("panel view", e)
    st = "🟢 <b>ON</b>" if s["enabled"] else "🔴 <b>OFF</b>"; md = "🧪 dry-run (no real orders)" if s["dry_run"] else "💸 <b>LIVE</b> (real orders)"
    ot = "market" if s["order_type"] == "market" else ("limit at entry · " + (f"cancel if not filled in {s['limit_timeout_min']} min" if s["limit_timeout_min"] else "no timeout"))
    pri = s.get("primary_exchange") or "mexc"; bk = [x for x in X.NAMES if x != pri][0]
    def kl(n): return f"{X.LABEL[n]} key {'✅' if X.key_present(n) else '— not set'}" + ("" if ex_on(s, n) else " · disabled")
    L = ["🤖 <b>Auto-trade · MEXC futures + Bybit backup</b>", "━━━━━━━━━━━━━━", f"Status {st} · {md}",
         f"🏦 Primary <b>{X.LABEL[pri]}</b> · backup <b>{X.LABEL[bk]}</b>: failover {'ON' if failover_on(s) else 'OFF'}" + ("" if s.get("failover") is not None else " (auto)"),
         f"🔑 {kl('mexc')} · {kl('bybit')}",
         f"💵 Risk <b>{s['risk_usdt']:g} USDT</b>/trade · max open <b>{s['max_open']}</b> · leverage ≤ <b>{s['leverage']}x</b>",
         f"🧾 Order: {esc(ot)}",
         f"🧱 Max notional: {('%g USDT' % s['max_notional_usdt']) if s['max_notional_usdt'] else 'off'} · daily loss limit: {('%g USDT' % s['daily_loss_usdt']) if s['daily_loss_usdt'] else 'off'}",
         "📋 Strategies: " + (esc(", ".join(s["strategies"])) if s["strategies"] else "<i>none</i>")]
    if v:
        b = v["dry"] if s["dry_run"] else v["live"]
        L.append(f"📈 Open {b['open']} · pending {b['pending']} · today {b['today_usdt']:+.2f} · all {b['pnl_usdt']:+.2f} USDT ({b['closed']} closed)")
    for n, note in STATE["perm"].items(): L.append("⚠️ " + esc(note))
    L += ["", "<i>Signals and alerts are never paused or changed by auto-trade. Each trade stays on the exchange it was opened on.</i>",
          "Set numbers: <code>/autotrade risk 2</code> · <code>maxopen 3</code> · <code>lev 5</code> · <code>notional 100</code> · <code>dailyloss 20</code> (0 = off)"]
    return "\n".join(L)
def panel_markup():
    s = settings(); B = lambda t, d: {"text": t, "callback_data": d}
    rows = [[B("🔴 Turn OFF" if s["enabled"] else "🟢 Turn ON", "at:en"), B("💸 Go LIVE…" if s["dry_run"] else "🧪 Back to dry-run", "at:dr")]]
    ks = [B(("✅ " if k in s["strategies"] else "⬜ ") + k, "at:s:" + k) for k in STRATS]
    rows += [ks[i:i+3] for i in range(0, len(ks), 3)]
    rows.append([B(("● " if s["order_type"] == "limit" else "") + "Limit", "at:ot:limit"), B(("● " if s["order_type"] == "market" else "") + "Market", "at:ot:market")])
    rows.append([B(("● " if s["limit_timeout_min"] == t else "") + (f"{t} min" if t else "No timeout"), f"at:to:{t}") for t in (5, 10, 15, 0)])
    pri = s.get("primary_exchange") or "mexc"
    rows.append([B(f"🏦 Primary: {X.LABEL[pri]} ⇄", "at:px"), B(("✅" if failover_on(s) else "⬜") + " Failover", "at:fo")])
    rows.append([B(("✅ " if ex_on(s, n) else "⬜ ") + X.LABEL[n], "at:x:" + n) for n in X.NAMES])
    rows.append([B("🛑 Flatten all…", "at:fl"), B("↻ Refresh", "at:rf")])
    return {"inline_keyboard": rows}
NUM = {"risk": "risk_usdt", "maxopen": "max_open", "max": "max_open", "lev": "leverage", "leverage": "leverage", "notional": "max_notional_usdt",
       "dailyloss": "daily_loss_usdt", "loss": "daily_loss_usdt", "timeout": "limit_timeout_min"}
def tg_command(text):
    """/autotrade [on|off|risk N|maxopen N|lev N|notional N|dailyloss N|timeout N] -> (reply text, markup or None)."""
    a = text.split()[1:]
    try:
        if a:
            w = a[0].lower()
            if w in ("on", "off"): save_settings(dict(enabled=w == "on"))
            elif w in NUM and len(a) > 1: save_settings({NUM[w]: a[1]})
            elif w in ("limit", "market"): save_settings(dict(order_type=w))
            elif w == "primary" and len(a) > 1: save_settings(dict(primary_exchange=a[1].lower()))
            elif w == "failover" and len(a) > 1 and a[1].lower() in ("on", "off", "auto"): save_settings(dict(failover=None if a[1].lower() == "auto" else a[1].lower() == "on"))
            elif w in X.NAMES and len(a) > 1 and a[1].lower() in ("on", "off"): save_settings(dict(ex_on={w: a[1].lower() == "on"}))
            else: return ("Usage: /autotrade [on|off|limit|market|risk N|maxopen N|lev N|notional N|dailyloss N|timeout 5|10|15|0|"
                          "primary mexc|bybit|failover on|off|auto|mexc on|off|bybit on|off]"), None
    except ValueError as e: return f"⚠️ {e}", None
    return panel_text(), panel_markup()
def tg_callback(data):
    """Inline-button handler. Returns (toast, new_text, markup, extra_message)."""
    s = settings(); d = data[3:]
    if d == "en": s = save_settings(dict(enabled=not s["enabled"])); return ("Auto-trade " + ("ON" if s["enabled"] else "OFF")), panel_text(), panel_markup(), None
    if d == "dr":
        if s["dry_run"]:
            if not any(X.key_present(x) for x in X.NAMES if ex_on(s, x)): return "Add an exchange key on the server first", panel_text(), panel_markup(), None
            return "Confirm below", None, None, ("⚠️ <b>Go LIVE?</b> Auto-trade will place REAL futures orders with your key(s): " + " → ".join(X.LABEL[x] for x in route(dict(s, dry_run=False), {n: 1 for n in X.NAMES})) + ".",
                                                 {"inline_keyboard": [[{"text": "✅ Yes, go LIVE", "callback_data": "at:live"}, {"text": "Cancel", "callback_data": "at:no"}]]})
        save_settings(dict(dry_run=True)); return "Dry-run on", panel_text(), panel_markup(), None
    if d == "live":
        try: save_settings(dict(dry_run=False)); return "LIVE mode on", panel_text(), panel_markup(), None
        except ValueError as e: return str(e)[:190], None, None, None
    if d == "no": return "Cancelled", "Cancelled – nothing changed.", None, None
    if d.startswith("s:"):
        k = d[2:]; cur = list(s["strategies"]); cur = [x for x in cur if x != k] if k in cur else cur + [k]
        save_settings(dict(strategies=cur)); return f"{k} {'on' if k in cur else 'off'}", panel_text(), panel_markup(), None
    try:
        if d == "px": s = save_settings(dict(primary_exchange=[x for x in X.NAMES if x != (s.get("primary_exchange") or "mexc")][0])); return "Primary: " + X.LABEL[s["primary_exchange"]], panel_text(), panel_markup(), None
        if d == "fo": s = save_settings(dict(failover=not failover_on(s))); return "Failover " + ("ON" if s["failover"] else "OFF"), panel_text(), panel_markup(), None
        if d.startswith("x:") and d[2:] in X.NAMES: n = d[2:]; save_settings(dict(ex_on={n: not ex_on(s, n)})); return f"{X.LABEL[n]} {'on' if ex_on(settings(0), n) else 'off'}", panel_text(), panel_markup(), None
    except ValueError as e: return str(e)[:190], None, None, None
    if d.startswith("ot:"): save_settings(dict(order_type=d[3:])); return "Order type: " + d[3:], panel_text(), panel_markup(), None
    if d.startswith("to:"): save_settings(dict(limit_timeout_min=int(d[3:]))); return "Limit timeout set", panel_text(), panel_markup(), None
    if d == "fl":
        return "Confirm below", None, None, ("🛑 <b>Flatten all auto trades?</b> Turns auto-trade OFF, cancels pending auto limits and market-closes every auto position on the exchange it was opened on. Manual positions are not touched.",
                                             {"inline_keyboard": [[{"text": "🛑 Yes, flatten all", "callback_data": "at:flx"}, {"text": "Cancel", "callback_data": "at:no"}]]})
    if d == "flx":
        o = flatten(); return "Flattened", f"🛑 Flattened: {o['closed']} closed, {o['cancelled']} limits cancelled" + (f", {len(o['errors'])} errors (see Mini App)" if o["errors"] else "") + ". Auto-trade is OFF.", None, None
    return "", panel_text(), panel_markup(), None
