"""DON20 [⭐ PRIMARY] + DON28 [🔷 SECONDARY]: crypto daily Donchian-20 breakout, 3xATR(20) chandelier trail, no fixed target.
DON20 rules from bt_sys/sys_bt.py ('Donchian20 D1 3xATR', crypto LS) / backtest-report-systematic.md.
DON28 (user 2026-11-04, research/don20_filters/don28_3y.py, +349.4R over 3y) = the same DON20 setup, kept only when it agrees
with the coin's own 200-day SMA: longs only when the daily close is above SMA200, shorts only when at/below it
(research cma: close > SMA200 -> +1 else -1). Like the research ('no filter while the SMA is unknown'), a coin with fewer
than 200 daily bars is NOT filtered (see SMA_UNKNOWN_PASSES). DON28 is tracked independently (own table don28, own one-position-
per-coin rule, own trail/exits), so it can differ from DON20 when one of them already holds the coin.
Runs once a day after the 00:00 UTC daily close in its own thread (never blocks the 15-min scan); one daily fetch serves both."""
import time, threading, json
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, wait
import pandas as pd
from . import config as C, db, binance
N, K, COST = 20, 3.0, 0.001          # lookback, ATR multiple, crypto cost per side (same as backtest)
SMA_N = 200                          # DON28 trend filter: coin's own 200-day SMA of daily closes
SMA_UNKNOWN_PASSES = True            # research parity: < 200 daily bars -> no filter (DON28 = DON20 for that coin)
DAILY_BARS = 260                     # daily klines per coin (>= SMA_N + 1 closed bars for DON28; DON20 needs N+2)
RUN_AFTER = (0, 5)                    # UTC hh, mm
CRYPTO_B = {"BNB","ARB","SHIB","CKB","TRB","BB","SNB"}   # real coins ending in B; other *B bases are Binance tokenised stocks (excluded, as in the backtest)
def is_stock(s): b = s[:-4]; return b.endswith("B") and b not in CRYPTO_B
STATE = dict(last_run=None, last_result=None, errors=[])
TABLE = {"DON20": "don20", "DON28": "don28"}
def keys(): return ["DON20"] + (["DON28"] if C.ENABLE_DON28 else [])
ID = "SERIAL PRIMARY KEY" if db.PG else "INTEGER PRIMARY KEY"
def ddl(t): return f"""CREATE TABLE IF NOT EXISTS {t}(id {ID}, symbol TEXT, direction TEXT, signal_day TEXT, opened_at TEXT,
  entry REAL, init_stop REAL, stop REAL, atr REAL, best_close REAL, status TEXT DEFAULT 'open', last_checked TEXT,
  closed_at TEXT, exit_price REAL, result_r REAL, net_r REAL, posted INTEGER DEFAULT 0, UNIQUE(symbol, signal_day))"""
DDL = ddl("don20")
def init():
    with db.conn() as c:
        for t in TABLE.values(): c.execute(ddl(t))
def _rows(sql, p=()):
    with db.conn() as c: return [dict(r) for r in c.execute(sql, p).fetchall()]
def open_positions(k="DON20"): return _rows(f"SELECT * FROM {TABLE[k]} WHERE status='open' ORDER BY id")
def all_positions(limit=200, k="DON20"): return _rows(f"SELECT * FROM {TABLE[k]} ORDER BY id DESC LIMIT ?", (limit,))
def _upd(i, k="DON20", **kw):
    with db.conn() as c: c.execute(f"UPDATE {TABLE[k]} SET {','.join(x+'=?' for x in kw)} WHERE id=?", (*kw.values(), i))
def summary(k="DON20"):
    from . import strategies as SG
    rs = _rows(f"SELECT status, result_r, net_r FROM {TABLE[k]}"); cl = [r for r in rs if r["status"] == "closed"]
    w = sum((r["net_r"] or 0) > 0 for r in cl); nets = [r["net_r"] or 0 for r in cl]
    return dict(label=f"{SG.label(k).split()[0]} {k} [{SG.status(k).upper()}]", signals=len(rs), closed=len(cl), open=len(rs)-len(cl),
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
def sma200(d):
    """(side, sma) for the last closed day: side +1 close > SMA200, -1 close <= SMA200, 0 unknown (< SMA_N bars)."""
    if len(d) < SMA_N: return 0, None
    ma = float(d.c.iloc[-SMA_N:].mean()); return (1 if float(d.c.iloc[-1]) > ma else -1), ma
def don28_ok(d, side):
    """DON28 filter on a DON20 signal: (passes, sma side, sma)."""
    s, ma = sma200(d); sd = 1 if side == "long" else -1
    return (s == sd) or (s == 0 and SMA_UNKNOWN_PASSES), s, ma
def _r(p, x):
    sd = 1 if p["direction"] == "long" else -1; risk = abs(p["entry"] - p["init_stop"])
    g = sd*(x - p["entry"])/risk; return g, g - COST*(p["entry"] + x)/risk

def fetch_daily(symbols, budget=None):
    budget = budget or min(C.FETCH_BUDGET_S, 120); out = {}
    def f(s):
        try: return s, binance.klines(s, "1d", DAILY_BARS)
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

def _hdr(k):
    from . import strategies as SG; return f"{SG.label(k)} · {k}"
def close(p, x, when, post, msgs, k="DON20"):
    g, n = _r(p, x)
    _upd(p["id"], k, status="closed", closed_at=when, exit_price=x, result_r=round(g, 3), net_r=round(n, 3))
    from .telegram import esc, code, wat
    ic = "✅" if n > 0 else "❌"
    msgs.append(dict(k=k, kind="exit", symbol=p["symbol"], direction=p["direction"], day=p["signal_day"], id=p["id"], g=g, n=n,
        text="\n".join([f"{ic} <b>EXIT · {_hdr(k)}</b>", "━━━━━━━━━━━━━━",
        f"{'🟢 LONG' if p['direction']=='long' else '🔴 SHORT'}  <b>{esc(p['symbol'])}</b>  · crypto  #{p['id']}",
        f"📍 Entry   {code(p['entry'])}", f"🚪 Exit    {code(x)}  <i>(trailing stop)</i>",
        f"💰 Result  <b>{g:+.2f}R</b> gross · <b>{n:+.2f}R</b> net", f"🕒 {wat(when)}"]), extra=[]))
def fmtp(x):
    from .telegram import fmt_price; return fmt_price(x)

def check_stops(cache, post=True):
    """Called from every 15-min scan with the already-fetched 15m candles: close DON20/DON28 positions whose stop was touched."""
    msgs = []; seen = {}   # (table, last_checked) -> ids: one batched UPDATE per table instead of one per position (Neon quota)
    for k in keys():
        for p in open_positions(k):
            try:
                d = cache.get(p["symbol"])
                if not d: continue
                m = d[1]; since = pd.Timestamp(p["last_checked"] or p["opened_at"])
                m = m[m.t >= since]
                if not len(m): continue
                sd = 1 if p["direction"] == "long" else -1; hit = None
                for _, b in m.iterrows():
                    if (sd == 1 and b.l <= p["stop"]) or (sd == -1 and b.h >= p["stop"]):
                        hit = min(p["stop"], b.o) if sd == 1 else max(p["stop"], b.o); when = b.t.isoformat(); break
                if hit is not None: close(p, hit, when, post, msgs, k)
                else: seen.setdefault((TABLE[k], m.ct.iloc[-1].isoformat()), []).append(int(p["id"]))
            except Exception as e: STATE["errors"].append(f"stops {k} {p['symbol']}: {e}")
    if seen:
        try:
            with db.conn() as c:
                for (t, lc), ids in seen.items(): c.execute(f"UPDATE {t} SET last_checked=? WHERE id IN ({','.join('?'*len(ids))})", (lc, *ids))
        except Exception as e: STATE["errors"].append(f"stops last_checked: {e}")
    _dispatch(msgs, post)
    return len(msgs)

def _twin(m, items):
    """The DON20 item (same kind, coin, direction and signal day) a DON28 item can be folded into, else None."""
    for x in items:
        if x["k"] == "DON20" and x["kind"] == m["kind"] and x["symbol"] == m["symbol"] and x["direction"] == m["direction"] and x.get("day") == m.get("day"):
            return x
    return None
def _dispatch(items, post):
    """Push by alert mode. A DON28 entry/exit that mirrors a DON20 one is folded into the DON20 message as a line (no duplicate);
    otherwise DON28 gets its own 🔷 SECONDARY message, only when the alert mode includes SECONDARY. Muted entries are recorded."""
    if not post or not items: return
    from . import telegram, alerts
    push = {k: alerts.should_push(k) for k in TABLE}; out = []
    for m in items:
        if m["k"] == "DON20":
            if push["DON20"]: out.append(m)
            elif m["kind"] == "entry": alerts.mute([dict(symbol=m["symbol"], strategy="DON20")])
            continue
        if not push.get(m["k"]):
            if m["kind"] == "entry": alerts.mute([dict(symbol=m["symbol"], strategy=m["k"])])
            continue
        tw = _twin(m, items) if push["DON20"] and m["kind"] in ("entry", "exit") else None
        if tw is not None: tw["extra"].append(m["line"] if m["kind"] == "entry" else f"🔷 also DON28 #{m['id']} closed: <b>{m['n']:+.2f}R</b> net")
        else: out.append(m)
    for m in out:
        t = m["text"] + ("" if not m.get("extra") else "\n" + "\n".join(m["extra"]))
        if m["kind"] == "entry" and m.get("extra"): t = m["text"].replace("\n\n<i>Not financial advice.</i>", "") + "\n" + "\n".join(m["extra"]) + "\n\n<i>Not financial advice.</i>"
        try: telegram.send(t, html=True)
        except Exception as e: STATE["errors"].append(f"telegram: {e}")

def _trail(k, opn, data, post, msgs):
    """Open positions: stop touched on any daily bar since last check? else trail to best close -/+ 3xATR (only in favour)."""
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
            if hit: close(p, hit[0], hit[1], post, msgs, k); closed_today.add(p["symbol"]); continue
            after = d[d.t >= pd.Timestamp(p["opened_at"]).floor("D")]
            best = p["best_close"]
            if len(after): best = max(best, after.c.max()) if sd == 1 else min(best, after.c.min())
            a = float(atr(d).iloc[-1]); ns = best - sd*K*a
            stop = max(p["stop"], ns) if sd == 1 else min(p["stop"], ns)
            _upd(p["id"], k, stop=stop, best_close=best, atr=a, last_checked=d.ct.iloc[-1].isoformat())
            trail.append((p, p["stop"], stop))
        except Exception as e: STATE["errors"].append(f"trail {k} {p['symbol']}: {e}")
    return trail, closed_today

def _entries(k, universe, data, px, closed_today, now, msgs):
    """New entries (one open position per coin per strategy). DON28 = DON20 signal that passes the SMA200 filter."""
    held = {p["symbol"] for p in open_positions(k)} | closed_today; new_pos = []; blocked = 0
    for s in universe:
        if s in held or is_stock(s): continue
        try:
            d = data.get(s)
            if d is None: continue
            sg = signal(d)
            if not sg: continue
            side, a = sg; day = d.t.iloc[-1].strftime("%Y-%m-%d"); sma = (None, None)
            if k == "DON28":
                ok, sside, ma = don28_ok(d, side)
                if not ok: blocked += 1; continue
                sma = (sside, ma)
            e = px.get(s) or float(d.c.iloc[-1]); sd = 1 if side == "long" else -1; st = e - sd*K*a
            new_pos.append(dict(strategy=k, symbol=s, direction=side, signal_day=day, entry=e, stop=st, atr=a, close=float(d.c.iloc[-1]), sma=sma))
        except Exception as e: STATE["errors"].append(f"signal {k} {s}: {e}")
    new_pos, thin = binance.liquid(new_pos, key=lambda n: ("crypto", n["symbol"]))   # liquidity floor: no new entries in thin coins
    if thin: STATE.setdefault("skipped_low_volume", {})[k] = thin
    from .telegram import esc, code, wat
    T = TABLE[k]
    for n in new_pos:
        with db.conn() as c:
            cur = c.execute(f"""INSERT INTO {T}(symbol,direction,signal_day,opened_at,entry,init_stop,stop,atr,best_close,last_checked)
              VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol, signal_day) DO NOTHING RETURNING id""",
              (n["symbol"], n["direction"], n["signal_day"], now.isoformat(), n["entry"], n["stop"], n["stop"], n["atr"], n["entry"], now.isoformat()))
            r = cur.fetchone()
        if not r: continue
        n["id"] = r["id"] if db.PG else r[0]
        r1 = abs(n['entry']-n['stop']); sd = 1 if n['direction'] == 'long' else -1
        sside, ma = n["sma"]
        smatxt = ("SMA200 n/a (under 200 daily bars, not filtered)" if not sside else
                  f"{'above' if sside == 1 else 'below'} SMA200 {code(ma)}")
        hdr = "⭐ <b>PRIMARY · DON20</b>" if k == "DON20" else "🔷 <b>SECONDARY · DON28</b>"
        strat = "DON20 · daily Donchian-20 breakout" if k == "DON20" else "DON28 · DON20 breakout + coin's 200-day SMA trend filter"
        why = f"Daily close {code(n['close'])} {'above the 20-day high' if sd == 1 else 'below the 20-day low'}" + (f", {smatxt}" if k == "DON28" else "")
        msgs.append(dict(k=k, kind="entry", symbol=n["symbol"], direction=n["direction"], day=n["signal_day"], id=n["id"], extra=[],
            line=f"🔷 <b>also DON28 ✓</b> ({smatxt}) · SECONDARY #{n['id']}",
            text="\n".join([hdr, "━━━━━━━━━━━━━━",
            f"{'🟢 <b>LONG</b>' if sd == 1 else '🔴 <b>SHORT</b>'}  <b>{esc(n['symbol'])}</b>  · crypto  #{n['id']}", "",
            f"📍 <b>Entry</b>   {code(n['entry'])}  <i>(market, daily close)</i>",
            f"🛑 <b>Stop</b>    {code(n['stop'])}  <i>(3×ATR20 = 1R, {100*r1/n['entry']:.2f}%)</i>",
            f"🎯 <b>Target</b>  <i>none – 3×ATR trailing stop</i>",
            f"⚖️ <b>R:R</b>     open-ended · optional 50% at 1.5R {code(n['entry'] + sd*1.5*r1)}",
            f"🧭 <b>Strategy</b> {strat}",
            f"🕒 {wat(now.isoformat())}", "",
            f"💡 {why}. Trail updates daily; EXIT is posted when the stop is hit.",
            "", "<i>Not financial advice.</i>"])))
    return [n for n in new_pos if "id" in n], blocked

def _trail_msg(k, trail, now, twins=()):
    from .telegram import esc, code
    hdr = "⭐ <b>PRIMARY · DON20 trailing stops</b>" if k == "DON20" else "🔷 <b>SECONDARY · DON28 trailing stops</b>"
    lines = [f"{hdr} – {now.strftime('%d %b')}", "━━━━━━━━━━━━━━"]; same = 0
    for p, old, new in trail:
        if (p["symbol"], p["direction"], p["signal_day"], round(float(new), 10)) in twins: same += 1; continue   # identical DON20 twin: listed there
        lines.append(f"{'🟢' if p['direction']=='long' else '🔴'} <b>{esc(p['symbol'])}</b> entry {code(p['entry'])} → 🛑 {code(new)}" + ("" if new != old else " <i>(unchanged)</i>"))
    if same and len(lines) > 2: lines.append(f"<i>+ {same} position(s) identical to DON20 (same entry day, same trail) – see the DON20 list.</i>")
    return lines   # only the 2 header lines => every DON28 trail mirrors DON20 => no separate message

def daily_run(universe, post=True, now=None):
    now = now or datetime.now(timezone.utc); t0 = time.time(); msgs = []
    ks = keys(); opn = {k: open_positions(k) for k in ks}
    syms = sorted(set(universe) | {p["symbol"] for k in ks for p in opn[k]})
    data = fetch_daily(syms); px = prices(); res = dict(day=now.strftime("%Y-%m-%d"), fetched=len(data), universe=len(universe))
    trails = {}
    for k in ks:
        trail, closed_today = _trail(k, opn[k], data, post, msgs)
        new_pos, blocked = _entries(k, universe, data, px, closed_today, now, msgs); trails[k] = trail
        p = "" if k == "DON20" else "don28_"
        res.update({p+"new": len(new_pos), p+"new_long": sum(n["direction"] == "long" for n in new_pos),
                    p+"new_short": sum(n["direction"] == "short" for n in new_pos), p+"trailed": len(trail), p+"closed": len(closed_today)})
        if k == "DON28": res["don28_blocked_by_sma"] = blocked
    from . import alerts
    if post and trails.get("DON20"):
        msgs.append(dict(k="DON20", kind="trail", symbol=None, direction=None, extra=[], text="\n".join(_trail_msg("DON20", trails["DON20"], now))))
    if post and trails.get("DON28"):
        tw = {(p["symbol"], p["direction"], p["signal_day"], round(float(n), 10)) for p, _, n in trails.get("DON20", [])} if alerts.should_push("DON20") else set()
        L = _trail_msg("DON28", trails["DON28"], now, tw)
        if len(L) > 2: msgs.append(dict(k="DON28", kind="trail", symbol=None, direction=None, extra=[], text="\n".join(L)))
    _dispatch(msgs, post)
    res["secs"] = round(time.time()-t0)
    STATE.update(last_run=now.isoformat(), last_result=res); STATE["errors"] = STATE["errors"][-20:]
    print(f"[don20] {res}", flush=True); return res, [m for m in msgs if m["kind"] == "entry"]

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
    for m in new: print(m["k"], m["direction"], m["symbol"], "#%s" % m["id"])
