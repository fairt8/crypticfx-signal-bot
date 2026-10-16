"""DON20 [EXPERIMENTAL – paper test]: crypto daily Donchian-20 breakout, 3xATR(20) chandelier trail, no fixed target.
Rules from bt_sys/sys_bt.py ('Donchian20 D1 3xATR', crypto LS) / backtest-report-systematic.md.
Runs once a day after the 00:00 UTC daily close in its own thread (never blocks the 15-min scan)."""
import time, threading, json
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, wait
import pandas as pd
from . import config as C, db, binance
N, K, COST = 20, 3.0, 0.001          # lookback, ATR multiple, crypto cost per side (same as backtest)
RUN_AFTER = (0, 5)                    # UTC hh, mm
CRYPTO_B = {"BNB","ARB","SHIB","CKB","TRB","BB","SNB"}   # real coins ending in B; other *B bases are Binance tokenised stocks (excluded, as in the backtest)
def is_stock(s): b = s[:-4]; return b.endswith("B") and b not in CRYPTO_B
STATE = dict(last_run=None, last_result=None, errors=[])
ID = "SERIAL PRIMARY KEY" if db.PG else "INTEGER PRIMARY KEY"
DDL = f"""CREATE TABLE IF NOT EXISTS don20(id {ID}, symbol TEXT, direction TEXT, signal_day TEXT, opened_at TEXT,
  entry REAL, init_stop REAL, stop REAL, atr REAL, best_close REAL, status TEXT DEFAULT 'open', last_checked TEXT,
  closed_at TEXT, exit_price REAL, result_r REAL, net_r REAL, posted INTEGER DEFAULT 0, UNIQUE(symbol, signal_day))"""
def init():
    with db.conn() as c: c.execute(DDL)
def _rows(sql, p=()):
    with db.conn() as c: return [dict(r) for r in c.execute(sql, p).fetchall()]
def open_positions(): return _rows("SELECT * FROM don20 WHERE status='open' ORDER BY id")
def all_positions(limit=200): return _rows("SELECT * FROM don20 ORDER BY id DESC LIMIT ?", (limit,))
def _upd(i, **kw):
    with db.conn() as c: c.execute(f"UPDATE don20 SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), i))
def summary():
    rs = _rows("SELECT status, result_r, net_r FROM don20"); cl = [r for r in rs if r["status"] == "closed"]
    w = sum((r["net_r"] or 0) > 0 for r in cl); nets = [r["net_r"] or 0 for r in cl]
    return dict(label="⭐ DON20 [PRIMARY]", signals=len(rs), closed=len(cl), open=len(rs)-len(cl),
                win_rate=round(100*w/len(cl), 1) if cl else None, gross_r=round(sum(r["result_r"] or 0 for r in cl), 2),
                net_r=round(sum(nets), 2), net_per_trade=round(sum(nets)/len(cl), 3) if cl else None)

def atr(d, n=N):
    tr = pd.concat([d.h-d.l, (d.h-d.c.shift()).abs(), (d.l-d.c.shift()).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()
def signal(d):
    """d = closed daily candles. Returns ('long'|'short', atr) for the last closed day or None."""
    if len(d) < N + 2: return None
    hi = d.h.iloc[-N-1:-1].max(); lo = d.l.iloc[-N-1:-1].min(); c = d.c.iloc[-1]; a = atr(d).iloc[-1]
    if not a or a != a or a <= 0: return None
    if c > hi: return "long", float(a)
    if c < lo: return "short", float(a)
    return None
def _r(p, x):
    sd = 1 if p["direction"] == "long" else -1; risk = abs(p["entry"] - p["init_stop"])
    g = sd*(x - p["entry"])/risk; return g, g - COST*(p["entry"] + x)/risk

def fetch_daily(symbols, budget=None):
    budget = budget or min(C.FETCH_BUDGET_S, 120); out = {}
    def f(s):
        try: return s, binance.klines(s, "1d", 60)
        except Exception: return s, None
    ex = ThreadPoolExecutor(C.SCAN_WORKERS); futs = [ex.submit(f, s) for s in symbols]
    done, pending = wait(futs, timeout=budget)
    for fu in done:
        try:
            s, d = fu.result()
            if d is not None and len(d): out[s] = d
        except Exception: pass
    ex.shutdown(wait=False, cancel_futures=True)
    if pending: STATE["errors"].append(f"daily fetch budget hit: {len(pending)} skipped")
    return out
def prices():
    try: return {t["symbol"]: float(t["price"]) for t in binance.get("/api/v3/ticker/price")}
    except Exception as e: STATE["errors"].append(f"prices: {e}"); return {}

def close(p, x, when, post, msgs):
    g, n = _r(p, x)
    _upd(p["id"], status="closed", closed_at=when, exit_price=x, result_r=round(g, 3), net_r=round(n, 3))
    msgs.append(f"EXIT DON20 {p['direction'].upper()} {p['symbol']} ⭐ [PRIMARY]\nTrailing stop hit at {fmtp(x)} "
                f"(entry {fmtp(p['entry'])}).\nResult: {g:+.2f}R gross, {n:+.2f}R after fees.")
def fmtp(x):
    from .telegram import fmt_price; return fmt_price(x)

def check_stops(cache, post=True):
    """Called from every 15-min scan with the already-fetched 15m candles: close DON20 positions whose stop was touched."""
    msgs = []
    for p in open_positions():
        try:
            d = cache.get(p["symbol"]); 
            if not d: continue
            m = d[1]; since = pd.Timestamp(p["last_checked"] or p["opened_at"])
            m = m[m.t >= since]
            if not len(m): continue
            sd = 1 if p["direction"] == "long" else -1; hit = None
            for _, b in m.iterrows():
                if (sd == 1 and b.l <= p["stop"]) or (sd == -1 and b.h >= p["stop"]):
                    hit = min(p["stop"], b.o) if sd == 1 else max(p["stop"], b.o); when = b.t.isoformat(); break
            if hit is not None: close(p, hit, when, post, msgs)
            else: _upd(p["id"], last_checked=m.ct.iloc[-1].isoformat())
        except Exception as e: STATE["errors"].append(f"stops {p['symbol']}: {e}")
    _send(msgs, post)
    return len(msgs)
def _send(msgs, post):
    if not post: return
    from . import telegram
    for t in msgs:
        try: telegram.send(t)
        except Exception as e: STATE["errors"].append(f"telegram: {e}")

def daily_run(universe, post=True, now=None):
    now = now or datetime.now(timezone.utc); t0 = time.time(); msgs = []
    opn = open_positions(); syms = sorted(set(universe) | {p["symbol"] for p in opn})
    data = fetch_daily(syms); px = prices()
    # 1) open positions: stop touched on any daily bar since last check? else trail to best close -/+ 3xATR (only in favour)
    trail, closed_today = [], set()
    for p in opn:
        try:
            d = data.get(p["symbol"])
            if d is None: continue
            sd = 1 if p["direction"] == "long" else -1
            since = pd.Timestamp(p["last_checked"] or p["opened_at"]); new = d[d.ct >= since]
            hit = None
            for _, b in new.iterrows():
                if (sd == 1 and b.l <= p["stop"]) or (sd == -1 and b.h >= p["stop"]):
                    hit = (min(p["stop"], b.o) if sd == 1 else max(p["stop"], b.o)), b.t.isoformat(); break
            if hit: close(p, hit[0], hit[1], post, msgs); closed_today.add(p["symbol"]); continue
            after = d[d.t >= pd.Timestamp(p["opened_at"]).floor("D")]
            best = p["best_close"]
            if len(after): best = max(best, after.c.max()) if sd == 1 else min(best, after.c.min())
            a = float(atr(d).iloc[-1]); ns = best - sd*K*a
            stop = max(p["stop"], ns) if sd == 1 else min(p["stop"], ns)
            _upd(p["id"], stop=stop, best_close=best, atr=a, last_checked=d.ct.iloc[-1].isoformat())
            trail.append((p, p["stop"], stop))
        except Exception as e: STATE["errors"].append(f"trail {p['symbol']}: {e}")
    # 2) new entries (one open DON20 position per coin)
    held = {p["symbol"] for p in open_positions()} | closed_today; new_pos = []
    day = None
    for s in universe:
        if s in held or is_stock(s): continue
        try:
            d = data.get(s)
            if d is None: continue
            sg = signal(d)
            if not sg: continue
            side, a = sg; day = d.t.iloc[-1].strftime("%Y-%m-%d")
            e = px.get(s) or float(d.c.iloc[-1]); sd = 1 if side == "long" else -1; st = e - sd*K*a
            new_pos.append(dict(symbol=s, direction=side, signal_day=day, entry=e, stop=st, atr=a, close=float(d.c.iloc[-1])))
        except Exception as e: STATE["errors"].append(f"signal {s}: {e}")
    for n in new_pos:
        with db.conn() as c:
            cur = c.execute("""INSERT INTO don20(symbol,direction,signal_day,opened_at,entry,init_stop,stop,atr,best_close,last_checked)
              VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol, signal_day) DO NOTHING RETURNING id""",
              (n["symbol"], n["direction"], n["signal_day"], now.isoformat(), n["entry"], n["stop"], n["stop"], n["atr"], n["entry"], now.isoformat()))
            r = cur.fetchone()
        if not r: continue
        n["id"] = r["id"] if db.PG else r[0]
        msgs.append(f"⭐ DON20 {n['direction'].upper()} {n['symbol']} [PRIMARY]\n#{n['id']} Daily close {fmtp(n['close'])} "
                    f"{'above the 20-day high' if n['direction']=='long' else 'below the 20-day low'}\nEntry (market, now): {fmtp(n['entry'])}\n"
                    f"Initial stop (3×ATR20, 1R): {fmtp(n['stop'])}\nTrailing 3×ATR, no fixed target, expect ~40% wins, avg winner ~1.4R.\n"
                    "Daily trailing-stop updates follow; EXIT is posted when the stop is hit.\n"
                    f"Optional: take 50% at 1.5R ({fmtp(n['entry'] + (1.5 if n['direction']=='long' else -1.5)*abs(n['entry']-n['stop']))}), move SL to entry, trail the rest.\n\nNot financial advice.")
    if trail:
        lines = [f"⭐ DON20 trailing stops – {now.strftime('%d %b')} [PRIMARY]"]
        for p, old, new in trail:
            lines.append(f"• {p['symbol']} {p['direction'].upper()} entry {fmtp(p['entry'])} → stop {fmtp(new)}" + ("" if new != old else " (unchanged)"))
        msgs.append("\n".join(lines))
    _send(msgs, post)
    res = dict(day=now.strftime("%Y-%m-%d"), fetched=len(data), universe=len(universe), new=len(new_pos),
               new_long=sum(n["direction"] == "long" for n in new_pos), new_short=sum(n["direction"] == "short" for n in new_pos),
               trailed=len(trail), closed=len(closed_today), secs=round(time.time()-t0))
    STATE.update(last_run=now.isoformat(), last_result=res); STATE["errors"] = STATE["errors"][-20:]
    print(f"[don20] {res}", flush=True); return res, new_pos

def due(now=None):
    now = now or datetime.now(timezone.utc)
    if (now.hour, now.minute) < RUN_AFTER: return False
    return db.kv_get("don20_last_day") != now.strftime("%Y-%m-%d")
def loop(get_universe, is_leader):
    while True:
        try:
            if is_leader() and due():
                day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                th = threading.Thread(target=lambda: daily_run(get_universe()), daemon=True, name="don20"); th.start()
                th.join(C.SCAN_WATCHDOG_S)   # watchdog: a hung run is abandoned; day still marked so it doesn't loop
                if th.is_alive(): STATE["errors"].append("watchdog: DON20 daily run abandoned")
                db.kv_set("don20_last_day", day)
        except BaseException as e: STATE["errors"].append(f"loop: {e}")
        time.sleep(120)
_started = False
def start(get_universe, is_leader):
    global _started
    if _started or not C.ENABLE_DON20: return
    _started = True; threading.Thread(target=loop, args=(get_universe, is_leader), daemon=True, name="don20-loop").start()

if __name__ == "__main__":
    import sys; db.init(); init()
    from . import scanner
    res, new = daily_run(scanner.crypto_universe(), post="--no-post" not in sys.argv)
    print(json.dumps(res, indent=1)); print("errors:", STATE["errors"][:5])
    for n in new: print(n["direction"], n["symbol"], n["entry"], round(n["stop"], 8))
