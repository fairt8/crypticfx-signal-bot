"""MEXC futures auto-trade add-on (user 2026-11-09). READ-ONLY consumer of the signals the bot already generates.

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
Dry-run (default) logs/simulates the same orders without calling any private MEXC endpoint."""
import collections, json, os, secrets, threading, time
from datetime import datetime, timezone, timedelta
from . import db, mexc as M

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
                limit_timeout_min=15, max_notional_usdt=0.0, daily_loss_usdt=0.0, enabled_at=None, strat_on={}, salt=None, updated_at=None)
STATE = dict(last_tick=None, last_result=None, errors=collections.deque(maxlen=30), skips=collections.deque(maxlen=30), backoff_until=0, idle_until=0)
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
      exit_reason TEXT, pnl_usdt REAL, note TEXT, UNIQUE(source, ref_id))"""
def ensure_table():
    if _TBL["ok"]: return
    with db.conn() as c: c.execute(ddl())
    _TBL["ok"] = True
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
            if not v and not M.key_present(): raise ValueError("Live mode needs MEXC_API_KEY and MEXC_API_SECRET in the server env file. Dry-run stays on.")
            s["dry_run"] = v
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
_CL = {"c": None}
def client():
    if _CL["c"] is None: _CL["c"] = M.Client()
    return _CL["c"]
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
    return (f"{icon} <b>AUTO · {esc(what)}</b>{' · 🧪 DRY-RUN' if r['dry'] else ' · MEXC'}\n"
            f"{'🟢 LONG' if r['direction']=='long' else '🔴 SHORT'} <b>{esc(r['symbol'])}</b> · {esc(r['strategy'])} · #{r['ref_id']}")
def _wat_day_start(now):
    w = now + timedelta(hours=1); return (w.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=1))

class Ctx:
    """Per-tick context: lazily fetched MEXC positions / position mode (one call each per tick)."""
    def __init__(self, cl, px, now): self.cl, self.px, self.now = cl, px, now; self._pos = None; self.msgs = []
    def positions(self):
        if self._pos is None: self._pos = self.cl.open_positions() or []
        return self._pos
    def position(self, con, direction):
        pt = 1 if direction == "long" else 2
        for p in self.positions():
            if p.get("symbol") == con and int(p.get("positionType") or 0) == pt and float(p.get("holdVol") or 0) > 0: return p
        return None
    def msg(self, r, text): self.msgs.append((bool(r["dry"]), text))

def _close_live(ctx, r, vol, tag="x"):
    """Reduce-only market close of `vol` contracts of this auto position. Returns True if an order was sent."""
    con = r["contract"]; pos = ctx.position(con, r["direction"])
    if not pos: return False
    vol = min(float(vol), float(pos.get("holdVol") or 0))
    if vol <= 0: return False
    c = ctx.cl.contract(con); p = ctx.px.get(r["symbol"]) or float(pos.get("holdAvgPrice") or r["entry"])
    body = dict(symbol=con, price=M.round_price(p, c), vol=M.floor_vol(vol, c), side=4 if r["direction"] == "long" else 2, type=5,
                openType=int(pos.get("openType") or 1), positionId=pos.get("positionId"), externalOid=(r["ext_oid"] + tag)[:32])
    if ctx.cl.position_mode() == 2: body["reduceOnly"] = True
    ctx.cl.create_order(**body); return True
def _amend_live(ctx, r, sl, tp):
    c = ctx.cl.contract(r["contract"]); pos = ctx.position(r["contract"], r["direction"])
    if not pos: return False
    sl = M.round_price(sl, c) if sl else None; tp = M.round_price(tp, c) if tp else None
    st = [o for o in ctx.cl.stop_orders(r["contract"]) if str(o.get("positionId")) == str(pos.get("positionId")) and int(o.get("state") or 1) == 1]
    if st: ctx.cl.change_stop(st[0]["id"], sl=sl, tp=tp)
    else: ctx.cl.place_stop(pos.get("positionId"), float(pos.get("holdVol") or r["vol"]), sl=sl, tp=tp)
    return True
def _finish(ctx, r, reason, exit_px, icon):
    pnl = (float(r["pnl_usdt"] or 0) if r["half_done"] else 0.0) + (_pnl(r, exit_px) if exit_px else 0.0)
    _upd(r["id"], status="closed", closed_at=iso(ctx.now), exit_price=exit_px, exit_reason=reason, pnl_usdt=round(pnl, 4))
    ctx.msg(r, _hdr(r, icon, f"closed · {reason}") + f"\n🚪 Exit ~{_fmt(exit_px)} · PnL <b>{pnl:+.2f} USDT</b> (est., after fees)")

# ---------------- manage one active auto trade ----------------
def manage(ctx, r, src, s):
    cl, now = ctx.cl, ctx.now; live = not r["dry"]; don = r["source"] in DON
    p = ctx.px.get(r["symbol"]); long = r["direction"] == "long"; sd = _sd(r["direction"])
    if r["status"] == "placing":   # live: create call outcome unknown (network) -> look it up by our idempotent client order id
        o = cl.order_by_ext(r["contract"], r["ext_oid"])
        if o: _upd(r["id"], status="open_order", order_id=str(o.get("orderId"))); return
        if now - _ts(r["created_at"]) > timedelta(minutes=5): _upd(r["id"], status="error", note="order not confirmed by MEXC")
        return
    if r["status"] == "open_order":
        fill = None
        if live:
            o = cl.order_by_ext(r["contract"], r["ext_oid"]) or {}
            st, dv = int(o.get("state") or 0), float(o.get("dealVol") or 0)
            if st == 3: fill = (float(o.get("dealAvgPrice") or r["entry"]), float(o.get("dealVol") or r["vol"]))
            elif st in (4, 5):
                if dv > 0: fill = (float(o.get("dealAvgPrice") or r["entry"]), dv)
                else: _upd(r["id"], status="cancelled", closed_at=iso(now), exit_reason="cancelled on MEXC"); ctx.msg(r, _hdr(r, "✖️", "limit cancelled on MEXC")); return
        else:   # dry: the limit fills when the bot's own tracker fills the signal, or the live price crosses the entry
            tracked = (not don) and src and src.get("filled_at") and src.get("status") in ("open", "tp", "sl", "be")
            crossed = p is not None and ((p <= r["entry"]) if long else (p >= r["entry"]))
            if tracked or crossed: fill = (float(r["entry"]), float(r["vol"]))
        if fill:
            cs = (r["qty"] / r["vol"]) if r["vol"] else 0
            _upd(r["id"], status="filled", filled_at=iso(now), fill_price=fill[0], vol=fill[1], qty=fill[1] * cs)
            ctx.msg(r, _hdr(r, "✅", "filled") + f"\n📍 {_fmt(fill[0])} · {fill[1]:g} contracts\n🛑 {_fmt(r['sl'])}" + (f"   🎯 {_fmt(r['tp'])}" if r["tp"] else "   🎯 trailing")); return
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
                cl.cancel_ext(r["contract"], r["ext_oid"])
                o = cl.order_by_ext(r["contract"], r["ext_oid"]) or {}
                if float(o.get("dealVol") or 0) > 0:   # filled in the race: keep the filled part as the position
                    cs = (r["qty"] / r["vol"]) if r["vol"] else 0; dv = float(o["dealVol"])
                    _upd(r["id"], status="filled", filled_at=iso(now), fill_price=float(o.get("dealAvgPrice") or r["entry"]), vol=dv, qty=dv * cs)
                    ctx.msg(r, _hdr(r, "✅", "partly filled before cancel") + f"\n{dv:g} contracts"); return
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
            try: pos = ctx.position(r["contract"], r["direction"]); pos and cl.cancel_stops(pos.get("positionId"))
            except Exception: pass
        _finish(ctx, r, reason, exit_px, "🏁"); return
    # 2) live: MEXC already closed it (attached SL/TP triggered, liquidation, manual close)
    if live and not ctx.position(r["contract"], r["direction"]):
        near = min([x for x in (r["sl"], r["tp"]) if x], key=lambda x: abs(x - (p or x)))
        _finish(ctx, r, "closed on MEXC (stop/target)", near, "🏁"); return
    # 3) CHK / FVG-D1: 50% at TP1 (1.5R) and stop to entry, like the bot's tracked outcome
    from . import config as C
    if r["strategy"] in C.PTP_STRATS and not r["half_done"] and r["tp"] and p is not None:
        R = abs(r["entry"] - r["init_sl"]); tp1 = r["entry"] + sd * 1.5 * R
        if R and abs(r["tp"] - r["entry"]) > 1.5 * R + 1e-12 and ((p >= tp1) if long else (p <= tp1)):
            half = r["vol"] / 2
            if live:
                c = cl.contract(r["contract"]); half = M.floor_vol(half, c)
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

def open_trade(ctx, s, cnd):
    cl, now = ctx.cl, ctx.now; live = not s["dry_run"]
    con = M.symbol_of(cnd["symbol"])
    if not con: raise M.Skip("not a USDT pair")
    c = cl.contract(con)
    p = ctx.px.get(cnd["symbol"]); long = cnd["direction"] == "long"; entry, sl, tp = cnd["entry"], cnd["sl"], cnd["tp"]; R = abs(entry - sl)
    if p is None: raise M.Skip("no live price")
    if (p <= sl) if long else (p >= sl): raise M.Skip("price already beyond the stop")
    if tp and ((p >= tp) if long else (p <= tp)): raise M.Skip("price already beyond the target")
    market = s["order_type"] == "market"
    if market and R and abs(p - entry) > MAX_SLIP_R * R: raise M.Skip(f"price moved {abs(p-entry)/R:.2f}R from the entry")
    ref = p if market else entry
    z = M.size(c, ref, sl, s["risk_usdt"], s.get("max_notional_usdt") or 0, s["leverage"])
    if live:
        fp = cl.fair_price(con)
        if fp and abs(fp - p) / p > MAX_PX_DEV: raise M.Skip(f"MEXC price {fp:g} differs from Binance {p:g} by {abs(fp-p)/p*100:.1f}% (different contract)")
        if ctx.position(con, "long") or ctx.position(con, "short"): raise M.Skip(f"there is already a MEXC position on {con} (manual?)")
        av = cl.usdt_available()
        if av < z["margin"] * 1.05: raise M.Skip(f"not enough USDT margin ({av:.2f} available, {z['margin']:.2f} needed)")
    tag = "s" if cnd["source"] == "sig" else cnd["source"][-2:]
    ext = f"cfx{s.get('salt') or '0'}{tag}{cnd['ref_id']}"[:32]
    to = 0 if market else int(s.get("limit_timeout_min") or 0)
    row = dict(source=cnd["source"], ref_id=cnd["ref_id"], strategy=cnd["strategy"], symbol=cnd["symbol"], contract=con, direction=cnd["direction"],
               order_type="market" if market else "limit", entry=M.round_price(ref, c), sl=M.round_price(sl, c), tp=M.round_price(tp, c) if tp else None,
               init_sl=float(sl), vol=z["vol"], qty=z["qty"], notional=z["notional"], risk_usdt=z["risk"], leverage=z["leverage"], ext_oid=ext,
               dry=0 if live else 1, note=json.dumps(dict(timeout=to)))
    if not live:   # dry-run: no private call; market fills at the live price now, limit waits for the fill
        row.update(status="filled" if market else "open_order")
        if market: row.update(fill_price=row["entry"], filled_at=iso(now))
        i = _insert(**row)
        if i and market: ctx.msg(dict(row, ref_id=cnd["ref_id"]), _hdr(dict(row), "✅", "filled (market)") + f"\n📍 {_fmt(row['entry'])} · {z['vol']:g} contracts · risk {z['risk']:.2f} USDT")
        print(f"[autotrade] DRY {row['order_type']} {row['direction']} {con} vol={z['vol']:g} @ {row['entry']} sl={row['sl']} tp={row['tp']} ({cnd['strategy']} #{cnd['ref_id']})", flush=True)
        return i
    i = _insert(status="placing", **row)
    if not i: return None   # already handled (idempotent: one auto trade per signal)
    body = dict(symbol=con, price=row["entry"], vol=z["vol"], leverage=z["leverage"], side=1 if long else 3, type=5 if market else 1,
                openType=1, externalOid=ext, stopLossPrice=row["sl"], takeProfitPrice=row["tp"])
    try:
        oid = cl.create_order(**body); _upd(i, status="open_order", order_id=oid)
        print(f"[autotrade] LIVE {row['order_type']} {row['direction']} {con} vol={z['vol']:g} @ {row['entry']} ({cnd['strategy']} #{cnd['ref_id']}) order {oid}", flush=True)
    except M.RateLimited: raise   # stays 'placing'; resolved by externalOid next tick
    except M.MexcError as e:
        _upd(i, status="error", note=json.dumps(dict(timeout=to, error=f"{e.code}: {e.msg}"[:200])))
        ctx.msg(dict(row, ref_id=cnd["ref_id"]), _hdr(dict(row), "⚠️", "order rejected") + f"\n<code>{e.code}</code> {str(e.msg)[:150]}")
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
    cl = cl or client(); px_fn = px_fn or prices
    sigs, dons = load_sources(s, active, now)
    known = {(r["source"], int(r["ref_id"])) for r in rows}
    cands = candidates(s, sigs, dons, known) if s["enabled"] else []
    px = px_fn({r["symbol"] for r in active} | {c["symbol"] for c in cands}) if (active or cands) else {}
    ctx = Ctx(cl, px, now); res = dict(active=len(active), candidates=len(cands), opened=0, skipped=0, errors=0)
    for r in active:
        src = sigs.get(int(r["ref_id"])) if r["source"] == "sig" else dons.get((r["source"], int(r["ref_id"])))
        try: manage(ctx, r, src, s)
        except M.RateLimited as e: _err("rate limit", e); STATE["backoff_until"] = time.time() + 120; break
        except Exception as e:
            res["errors"] += 1; m = _err(f"manage #{r['id']} {r['symbol']}", e)
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
            except M.RateLimited as e: _err("rate limit", e); STATE["backoff_until"] = time.time() + 120; break
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
    Only touches positions this add-on opened; manual MEXC positions are left alone."""
    now = now or utcnow(); ensure_table(); save_settings(dict(enabled=False))
    rows = _q("SELECT * FROM autotrade WHERE status IN ('placing','open_order','filled')")
    cl = cl or client(); px = (px_fn or prices)({r["symbol"] for r in rows}) if rows else {}
    ctx = Ctx(cl, px, now); out = dict(cancelled=0, closed=0, errors=[])
    for r in rows:
        try:
            if r["status"] in ("placing", "open_order"):
                if not r["dry"]: cl.cancel_ext(r["contract"], r["ext_oid"])
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
    return dict(settings=pub, key_present=M.key_present(), strategies=[dict(key=k, short=SG.short(k), tier=SG.status(k), on=k in s["strategies"]) for k in STRATS],
                timeouts=list(TIMEOUTS), active=act, recent=[r for r in rows if r["status"] not in ACTIVE][:60], live=summ(False), dry=summ(True),
                worker=dict(last_tick=STATE["last_tick"], last_result=STATE["last_result"], poll_s=POLL_S, errors=list(STATE["errors"])[-8:], skips=list(STATE["skips"])[-10:]),
                exchange=dict(name="MEXC USDT-M perpetual", base=M.BASE, order_api="open to KYC-verified accounts since 2026-03-31 (Order Placing permission)"))

def panel_text():
    from .telegram import esc
    s = settings(); v = None
    try: v = view()
    except Exception as e: _err("panel view", e)
    st = "🟢 <b>ON</b>" if s["enabled"] else "🔴 <b>OFF</b>"; md = "🧪 dry-run (no real orders)" if s["dry_run"] else "💸 <b>LIVE</b> (real orders)"
    ot = "market" if s["order_type"] == "market" else ("limit at entry · " + (f"cancel if not filled in {s['limit_timeout_min']} min" if s["limit_timeout_min"] else "no timeout"))
    L = ["🤖 <b>Auto-trade · MEXC futures</b>", "━━━━━━━━━━━━━━", f"Status {st} · {md}",
         f"🔑 API key: {'set ✅' if M.key_present() else 'not set (add it on the server)'}",
         f"💵 Risk <b>{s['risk_usdt']:g} USDT</b>/trade · max open <b>{s['max_open']}</b> · leverage ≤ <b>{s['leverage']}x</b>",
         f"🧾 Order: {esc(ot)}",
         f"🧱 Max notional: {('%g USDT' % s['max_notional_usdt']) if s['max_notional_usdt'] else 'off'} · daily loss limit: {('%g USDT' % s['daily_loss_usdt']) if s['daily_loss_usdt'] else 'off'}",
         "📋 Strategies: " + (esc(", ".join(s["strategies"])) if s["strategies"] else "<i>none</i>")]
    if v:
        b = v["dry"] if s["dry_run"] else v["live"]
        L.append(f"📈 Open {b['open']} · pending {b['pending']} · today {b['today_usdt']:+.2f} · all {b['pnl_usdt']:+.2f} USDT ({b['closed']} closed)")
    L += ["", "<i>Signals and alerts are never paused or changed by auto-trade.</i>",
          "Set numbers: <code>/autotrade risk 2</code> · <code>maxopen 3</code> · <code>lev 5</code> · <code>notional 100</code> · <code>dailyloss 20</code> (0 = off)"]
    return "\n".join(L)
def panel_markup():
    s = settings(); B = lambda t, d: {"text": t, "callback_data": d}
    rows = [[B("🔴 Turn OFF" if s["enabled"] else "🟢 Turn ON", "at:en"), B("💸 Go LIVE…" if s["dry_run"] else "🧪 Back to dry-run", "at:dr")]]
    ks = [B(("✅ " if k in s["strategies"] else "⬜ ") + k, "at:s:" + k) for k in STRATS]
    rows += [ks[i:i+3] for i in range(0, len(ks), 3)]
    rows.append([B(("● " if s["order_type"] == "limit" else "") + "Limit", "at:ot:limit"), B(("● " if s["order_type"] == "market" else "") + "Market", "at:ot:market")])
    rows.append([B(("● " if s["limit_timeout_min"] == t else "") + (f"{t} min" if t else "No timeout"), f"at:to:{t}") for t in (5, 10, 15, 0)])
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
            else: return "Usage: /autotrade [on|off|limit|market|risk N|maxopen N|lev N|notional N|dailyloss N|timeout 5|10|15|0]", None
    except ValueError as e: return f"⚠️ {e}", None
    return panel_text(), panel_markup()
def tg_callback(data):
    """Inline-button handler. Returns (toast, new_text, markup, extra_message)."""
    s = settings(); d = data[3:]
    if d == "en": s = save_settings(dict(enabled=not s["enabled"])); return ("Auto-trade " + ("ON" if s["enabled"] else "OFF")), panel_text(), panel_markup(), None
    if d == "dr":
        if s["dry_run"]:
            if not M.key_present(): return "Add the MEXC key on the server first", panel_text(), panel_markup(), None
            return "Confirm below", None, None, ("⚠️ <b>Go LIVE?</b> Auto-trade will place REAL MEXC futures orders with your key.",
                                                 {"inline_keyboard": [[{"text": "✅ Yes, go LIVE", "callback_data": "at:live"}, {"text": "Cancel", "callback_data": "at:no"}]]})
        save_settings(dict(dry_run=True)); return "Dry-run on", panel_text(), panel_markup(), None
    if d == "live":
        try: save_settings(dict(dry_run=False)); return "LIVE mode on", panel_text(), panel_markup(), None
        except ValueError as e: return str(e)[:190], None, None, None
    if d == "no": return "Cancelled", "Cancelled – nothing changed.", None, None
    if d.startswith("s:"):
        k = d[2:]; cur = list(s["strategies"]); cur = [x for x in cur if x != k] if k in cur else cur + [k]
        save_settings(dict(strategies=cur)); return f"{k} {'on' if k in cur else 'off'}", panel_text(), panel_markup(), None
    if d.startswith("ot:"): save_settings(dict(order_type=d[3:])); return "Order type: " + d[3:], panel_text(), panel_markup(), None
    if d.startswith("to:"): save_settings(dict(limit_timeout_min=int(d[3:]))); return "Limit timeout set", panel_text(), panel_markup(), None
    if d == "fl":
        return "Confirm below", None, None, ("🛑 <b>Flatten all auto trades?</b> Turns auto-trade OFF, cancels pending auto limits and market-closes every auto position on MEXC. Manual positions are not touched.",
                                             {"inline_keyboard": [[{"text": "🛑 Yes, flatten all", "callback_data": "at:flx"}, {"text": "Cancel", "callback_data": "at:no"}]]})
    if d == "flx":
        o = flatten(); return "Flattened", f"🛑 Flattened: {o['closed']} closed, {o['cancelled']} limits cancelled" + (f", {len(o['errors'])} errors (see Mini App)" if o["errors"] else "") + ". Auto-trade is OFF.", None, None
    return "", panel_text(), panel_markup(), None
