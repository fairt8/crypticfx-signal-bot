"""Copy signals (and kv) from a SQLite file into Postgres (e.g. Neon). Idempotent: existing ids/keys are skipped.
Usage: DATABASE_URL=postgresql://... python scripts/migrate_sqlite_to_pg.py [signals.db]"""
import os, sys, sqlite3
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import config as C
assert C.DATABASE_URL, "set DATABASE_URL"
from app import db
src = sys.argv[1] if len(sys.argv) > 1 else "signals.db"
db.init()   # creates tables in Postgres
s = sqlite3.connect(src); s.row_factory = sqlite3.Row
cols = [r[1] for r in s.execute("PRAGMA table_info(signals)")]
use = [c for c in db.COLS if c in cols]
rows = s.execute(f"SELECT {','.join(use)} FROM signals ORDER BY id").fetchall()
n = 0
with db.conn() as c:
    for r in rows:
        cur = c.execute(f"INSERT INTO signals({','.join(use)}) VALUES({','.join('?'*len(use))}) ON CONFLICT DO NOTHING", tuple(r[k] for k in use))
        n += cur.rowcount
    c.execute("SELECT setval(pg_get_serial_sequence('signals','id'), COALESCE((SELECT MAX(id) FROM signals),1))")
    if s.execute("SELECT name FROM sqlite_master WHERE name='kv'").fetchone():
        for k, v in s.execute("SELECT k, v FROM kv WHERE k NOT LIKE 'lease:%'"):
            c.execute("INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO NOTHING", (k, v))
print(f"source rows: {len(rows)}, inserted: {n}")
with db.conn() as c: print("postgres signals now:", c.execute("SELECT COUNT(*) AS n FROM signals").fetchone()["n"])
