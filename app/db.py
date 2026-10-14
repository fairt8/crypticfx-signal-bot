import sqlite3, json, os, socket, uuid
from datetime import datetime, timezone, timedelta
from . import config as C

PG = bool(C.DATABASE_URL)
if PG:
    import psycopg
    from psycopg.rows import dict_row

class _Conn:
    """Tiny adapter so the same SQL (with ? placeholders) runs on SQLite and Postgres."""
    def __init__(self):
        if PG: self.c = psycopg.connect(C.DATABASE_URL, row_factory=dict_row, autocommit=False, connect_timeout=15)
        else: self.c = sqlite3.connect(C.DB_PATH, check_same_thread=False, timeout=30); self.c.row_factory = sqlite3.Row
    def execute(self, sql, params=()):
        if PG: return self.c.execute(sql.replace("?", "%s"), params or None)
        return self.c.execute(sql, params)
    def __enter__(self): return self
    def __exit__(self, et, e, tb):
        (self.c.rollback if et else self.c.commit)(); self.c.close()
def conn(): return _Conn()

ID = "SERIAL PRIMARY KEY" if PG else "INTEGER PRIMARY KEY"
DDL = f"""CREATE TABLE IF NOT EXISTS signals(id {ID}, created_at TEXT, symbol TEXT, market TEXT,
          direction TEXT, entry REAL, sl REAL, tp REAL, rr REAL, confidence INTEGER, in_session INTEGER, reasons TEXT,
          htf_top REAL, htf_bottom REAL, htf_time TEXT, tap_time TEXT, confirm_time TEXT, price_at_signal REAL,
          status TEXT DEFAULT 'pending', filled_at TEXT, closed_at TEXT, result_r REAL, posted INTEGER DEFAULT 0,
          strategy TEXT DEFAULT 'FVG', tags TEXT DEFAULT 'FVG', experimental INTEGER DEFAULT 0,
          UNIQUE(symbol, confirm_time, strategy))"""
COLS = ["id","created_at","symbol","market","direction","entry","sl","tp","rr","confidence","in_session","reasons","htf_top",
        "htf_bottom","htf_time","tap_time","confirm_time","price_at_signal","status","filled_at","closed_at","result_r","posted",
        "strategy","tags","experimental"]
def init():
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)")
        if PG:
            c.execute(DDL); return
        exists = c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='signals'").fetchone()
        cols = [r[1] for r in c.execute("PRAGMA table_info(signals)")] if exists else []
        if exists and "strategy" not in cols:   # migrate v1 SQLite table (unique key widened to include strategy)
            c.execute("ALTER TABLE signals RENAME TO signals_v1"); c.execute(DDL)
            old = [x for x in COLS if x in cols]
            c.execute(f"INSERT INTO signals({','.join(old)}) SELECT {','.join(old)} FROM signals_v1"); c.execute("DROP TABLE signals_v1")
        else: c.execute(DDL)

# ---- key/value + leader lease (restart/multi-instance safety, works on both backends) ----
INSTANCE = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
def kv_get(k):
    with conn() as c:
        r = c.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return (r["v"] if PG else r[0]) if r else None
def kv_set(k, v):
    with conn() as c: c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))
def lease(name="scheduler", ttl_s=600):
    """Return True if this process holds (or just took) the named lease. Lease = 'owner|expires_iso' in kv, set atomically."""
    now = datetime.now(timezone.utc); exp = (now + timedelta(seconds=ttl_s)).isoformat(); key = "lease:" + name
    with conn() as c:
        c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO NOTHING", (key, "|1970-01-01T00:00:00+00:00"))
        cur = c.execute("UPDATE kv SET v=? WHERE k=? AND (v LIKE ? OR substr(v, instr(v,'|')+1) < ?)" if not PG else
                        "UPDATE kv SET v=%s WHERE k=%s AND (v LIKE %s OR split_part(v,'|',2) < %s)",
                        (f"{INSTANCE}|{exp}", key, INSTANCE + "|%", now.isoformat()))
        return cur.rowcount == 1
def insert(s):
    with conn() as c:
        cur = c.execute("""INSERT INTO signals(created_at,symbol,market,direction,entry,sl,tp,rr,confidence,in_session,
          reasons,htf_top,htf_bottom,htf_time,tap_time,confirm_time,price_at_signal,strategy,tags,experimental,status,filled_at)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol, confirm_time, strategy) DO NOTHING RETURNING id""",
          (datetime.now(timezone.utc).isoformat(), s["symbol"], s["market"], s["direction"], s["entry"], s["sl"], s["tp"], s["rr"],
           s["confidence"], int(s["in_session"]), json.dumps(s["reasons"]), s["htf_top"], s["htf_bottom"], s["htf_time"],
           s["tap_time"], s["confirm_time"], s["price_now"], s.get("strategy","FVG"), ",".join(s.get("tags",["FVG"])),
           int(s.get("experimental",0)), s.get("status","pending"), s.get("filled_at")))
        r = cur.fetchone()
        return (r["id"] if PG else r[0]) if r else None
def recent(days=30, limit=500):
    since = (datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
    with conn() as c:
        return [row(r) for r in c.execute("SELECT * FROM signals WHERE created_at>=? ORDER BY id DESC LIMIT ?", (since, limit))]
def get(i):
    with conn() as c:
        r = c.execute("SELECT * FROM signals WHERE id=?", (i,)).fetchone(); return row(r) if r else None
def open_signals():
    with conn() as c: return [row(r) for r in c.execute("SELECT * FROM signals WHERE status IN ('pending','open')")]
def update(i, **kw):
    with conn() as c: c.execute(f"UPDATE signals SET {','.join(k+'=?' for k in kw)} WHERE id=?", (*kw.values(), i))
def row(r):
    d = dict(r); d["reasons"] = json.loads(d["reasons"] or "[]"); d["tags"] = (d.get("tags") or "FVG").split(",")
    d["net_r"] = net_r(d) if d.get("result_r") is not None else None; return d
COST = {"crypto": 0.001, "forex": 0.0002, "metal": 0.0005}   # same round-trip cost assumptions as the backtests
def net_r(r):
    if r["result_r"] is None: return None
    risk = abs(r["entry"]-r["sl"])/r["entry"]; k = "metal" if r["symbol"] in ("XAUUSD","XAGUSD") else r["market"]
    return r["result_r"] - (COST[k]/risk if risk > 0 else 0)
STRATS = {"FVG": "FVG (live)", "FVG+TREND": "FVG + 4H trend [EXPERIMENTAL]", "CHK": "Varsity checklist [EXPERIMENTAL]", "FVG-PLAN": "FVG creator plan, swing stop [EXPERIMENTAL]"}
def by_strategy(days=60):
    rs = recent(days, 20000); out = {}
    for k, label in STRATS.items():
        sub = [r for r in rs if k in r["tags"]]; cl = [r for r in sub if r["status"] in ("tp","sl")]
        w = sum(r["status"]=="tp" for r in cl); nets = [net_r(r) for r in cl]
        out[k] = dict(label=label, signals=len(sub), closed=len(cl), open=sum(r["status"] in ("open","pending") for r in sub),
            win_rate=round(100*w/len(cl),1) if cl else None, gross_r=round(sum(r["result_r"] for r in cl),2),
            net_r=round(sum(nets),2), net_per_trade=round(sum(nets)/len(cl),3) if cl else None)
    return out
def stats(days=30):
    rs = recent(days, 10000); closed = [r for r in rs if r["status"] in ("tp","sl")]
    w = sum(r["status"]=="tp" for r in closed)
    return dict(total=len(rs), tp=w, sl=len(closed)-w, open=sum(r["status"]=="open" for r in rs),
        pending=sum(r["status"]=="pending" for r in rs), expired=sum(r["status"]=="expired" for r in rs),
        win_rate=round(100*w/len(closed),1) if closed else None, net_r=round(sum(r["result_r"] or 0 for r in closed),2))

def release_lease(name="scheduler"):
    """Give the lease up on shutdown so a redeployed instance can take over immediately."""
    try:
        with conn() as c:
            c.execute("UPDATE kv SET v=? WHERE k=? AND v LIKE ?" if not PG else "UPDATE kv SET v=%s WHERE k=%s AND v LIKE %s",
                      ("|1970-01-01T00:00:00+00:00", "lease:" + name, INSTANCE + "|%"))
    except Exception: pass
