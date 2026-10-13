"""Migrate signals.db -> Neon over HTTPS (/sql endpoint) when port 5432 is blocked. Never prints the connection string."""
import os, sys, json, sqlite3, urllib.parse, requests
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, BASE)
url = open(os.path.join(BASE, ".neon_url")).read().strip()
os.environ["DATABASE_URL"] = url            # makes app.db build its Postgres DDL (SERIAL id) -> identical schema
from app import db
host = urllib.parse.urlparse(url).hostname
H = {"Neon-Connection-String": url, "Content-Type": "application/json"}
def q(query, params=None):
    r = requests.post(f"https://{host}/sql", headers=H, json={"query": query, "params": params or []}, timeout=60)
    if r.status_code != 200: raise SystemExit(f"neon error {r.status_code}: {r.text[:300]}")
    return r.json()
def tx(queries):
    r = requests.post(f"https://{host}/sql", headers=H, json={"queries": queries}, timeout=120)
    if r.status_code != 200: raise SystemExit(f"neon tx error {r.status_code}: {r.text[:300]}")
    return r.json()
def pg(sql): return sql.replace("?", "$%d") if False else sql
def numbered(sql):   # ? -> $1..$n
    out, n = "", 0
    for ch in sql:
        if ch == "?": n += 1; out += f"${n}"
        else: out += ch
    return out
src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "signals.db")
tx([{"query": "CREATE TABLE IF NOT EXISTS kv(k TEXT PRIMARY KEY, v TEXT)", "params": []}, {"query": db.DDL, "params": []}])
s = sqlite3.connect(src); s.row_factory = sqlite3.Row
cols = [r[1] for r in s.execute("PRAGMA table_info(signals)")]; use = [c for c in db.COLS if c in cols]
rows = s.execute(f"SELECT {','.join(use)} FROM signals ORDER BY id").fetchall()
ins = numbered(f"INSERT INTO signals({','.join(use)}) VALUES({','.join('?'*len(use))}) ON CONFLICT DO NOTHING")
inserted = 0
for i in range(0, len(rows), 50):
    res = tx([{"query": ins, "params": [r[k] for k in use]} for r in rows[i:i+50]])
    inserted += sum(x.get("rowCount") or 0 for x in res.get("results", []))
q("SELECT setval(pg_get_serial_sequence('signals','id'), COALESCE((SELECT MAX(id) FROM signals),1))")
kv_n = 0
if s.execute("SELECT name FROM sqlite_master WHERE name='kv'").fetchone():
    kvs = s.execute("SELECT k, v FROM kv WHERE k NOT LIKE 'lease:%'").fetchall()
    if kvs: tx([{"query": "INSERT INTO kv(k,v) VALUES($1,$2) ON CONFLICT(k) DO NOTHING", "params": [k, v]} for k, v in kvs]); kv_n = len(kvs)
src_ids = [r["id"] for r in rows]
cnt = q("SELECT COUNT(*) AS n, MIN(id) AS lo, MAX(id) AS hi FROM signals")["rows"][0]
missing = q("SELECT COUNT(*) AS n FROM unnest($1::int[]) AS t(id) WHERE id NOT IN (SELECT id FROM signals)", ["{" + ",".join(map(str, src_ids)) + "}"])["rows"][0]["n"]
sch = q("SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_name='signals' ORDER BY ordinal_position")["rows"]
uq = q("SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conrelid='signals'::regclass")["rows"]
kvc = q("SELECT COUNT(*) AS n FROM kv")["rows"][0]["n"]
print(json.dumps(dict(sqlite_rows=len(rows), inserted_now=inserted, neon_rows=int(cnt["n"]), id_range=[cnt["lo"], cnt["hi"]],
    source_ids_missing_in_neon=int(missing), kv_copied=kv_n, neon_kv_rows=int(kvc),
    columns=[c["column_name"] for c in sch], expected_columns=db.COLS, constraints=[u["d"] for u in uq],
    id_default=sch[0]["column_default"]), indent=1))
