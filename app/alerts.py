"""Alert mode + 'profitable strategy' definition (shared by the bot, dashboard and mini app).

Profitable strategy (recomputed every scan and cached in the DB, so the set can change):
  * live: closed trades whose close time is in the last PROFIT_WINDOW_DAYS (default 30) days, net R after fees
    (same convention as the stats). If there are >= PROFIT_MIN_TRADES (default 10) such trades -> profitable = net R > 0.
  * otherwise fall back to the latest all-strategy backtest (app.backtest_all copy in the DB): profitable = backtest
    net R > 0 when it has >= PROFIT_MIN_TRADES trades.
  * otherwise 'not enough data' (not profitable for alerting).
Retired strategies are never profitable for alerting.

Alert mode (DB setting 'setting:alert_mode' in the kv table, shared by the VM, Render and GitHub Actions):
  primary            ⭐ PRIMARY signals only
  primary_secondary  ⭐ PRIMARY + 🔷 SECONDARY (default)
There are no other live tiers (user 2026-10-31: "No more normal signals only primary and secondary").
Retired strategies never create live signals. 💰 'profitable' is kept as an info badge / filter only."""
import json, os, time
from datetime import datetime, timezone, timedelta
from . import db, strategies as SG

WINDOW = int(os.getenv("PROFIT_WINDOW_DAYS", "30"))
MIN_N = int(os.getenv("PROFIT_MIN_TRADES", "10"))
MODES = ("primary", "primary_secondary")
ALIASES = {"prim": "primary", "primary_only": "primary", "only_primary": "primary",
           "both": "primary_secondary", "secondary": "primary_secondary", "all": "primary_secondary", "everything": "primary_secondary",
           "primary+secondary": "primary_secondary", "primary_and_secondary": "primary_secondary", "ps": "primary_secondary",
           # old modes (before 2026-10-31) -> both live tiers
           "profitable": "primary_secondary", "profit": "primary_secondary", "primary_or_profitable": "primary_secondary",
           "primary+profitable": "primary_secondary", "or": "primary_secondary"}
MODE_LABEL = {"primary": "⭐ PRIMARY only", "primary_secondary": "⭐ PRIMARY + 🔷 SECONDARY"}
TIERS = ("primary", "secondary", "profitable")   # /signals + API filters (profitable = 💰 info filter)
DEFAULT_MODE = "primary_secondary"
KEY_MODE, KEY_PROFIT, KEY_MUTED = "setting:alert_mode", "profitable:last", "alerts:muted"

def norm_mode(m):
    m = (m or "").strip().lower().replace(" ", "_"); m = ALIASES.get(m, m); return m if m in MODES else None
def get_mode():
    try: return norm_mode(db.kv_get(KEY_MODE)) or DEFAULT_MODE
    except Exception: return DEFAULT_MODE
def set_mode(m):
    m = norm_mode(m)
    if not m: raise ValueError("mode must be: primary (⭐ only) or both (⭐ PRIMARY + 🔷 SECONDARY)")
    db.kv_set(KEY_MODE, m); return m

MIGRATION_KEY = "migration:2026-10-31-two-tiers"
def apply_migrations():
    """One-time: store the old mode in the new two-tier form (primary stays primary, everything else -> primary_secondary)."""
    try:
        if not db.kv_get(MIGRATION_KEY):
            old = (db.kv_get(KEY_MODE) or "").strip().lower()
            set_mode("primary" if old == "primary" else "primary_secondary"); db.kv_set(MIGRATION_KEY, datetime.now(timezone.utc).isoformat())
    except Exception: pass
def compute():
    """Per active strategy: live window stats, backtest fallback, verdict."""
    from . import trades, webapp
    since = datetime.now(timezone.utc) - timedelta(days=WINDOW)
    rows = trades._sig_rows("WHERE 1=1") + trades._don_rows()
    try: bt = (webapp.latest_backtest() or {}).get("strategies", {})
    except Exception: bt = {}
    out = {}
    for k in SG.STATUS:
        st = SG.status(k)
        cl = [r for r in rows if r["strategy"] == k and r.get("net_r") is not None and trades._in(r.get("closed_at") or r.get("created_at"), since)]
        net = round(sum(r["net_r"] for r in cl), 2); n = len(cl)
        d = dict(status=st, label=SG.label(k), live_n=n, live_net_r=net, window_days=WINDOW, min_trades=MIN_N)
        b = (bt.get(k) or {}).get("total") or {}
        if st == "retired": d.update(source="retired", profitable=False, verdict="🗄 retired")
        elif n >= MIN_N: d.update(source="live", profitable=net > 0, verdict=("💰 profitable" if net > 0 else "📉 not profitable") + f" (live {WINDOW}d: {net:+.2f}R, {n} trades)")
        elif (b.get("n") or 0) >= MIN_N:
            p = (b.get("net_r") or 0) > 0
            d.update(source="backtest", profitable=p, backtest_n=b.get("n"), backtest_net_r=b.get("net_r"),
                     verdict=("💰 profitable" if p else "📉 not profitable") + f" (backtest: {b.get('net_r', 0):+.1f}R, {b.get('n')} trades; live only {n})")
        else: d.update(source="none", profitable=None, verdict=f"⚪ not enough data ({n} live closed in {WINDOW}d, need {MIN_N})")
        out[k] = d
    return out

def refresh():
    """Called at the end of every scan: recompute and cache in the DB (Render + GitHub Actions share it)."""
    t = compute(); db.kv_set(KEY_PROFIT, json.dumps(dict(at=datetime.now(timezone.utc).isoformat(), table=t))); _C.update(t=time.time(), v=t); return t
_C = {"t": 0, "v": None}
def table(max_age_s=1800):
    if _C["v"] is not None and time.time() - _C["t"] < 120: return _C["v"]
    try:
        raw = db.kv_get(KEY_PROFIT)
        if raw:
            d = json.loads(raw)
            if datetime.now(timezone.utc) - datetime.fromisoformat(d["at"]) < timedelta(seconds=max_age_s):
                _C.update(t=time.time(), v=d["table"]); return d["table"]
    except Exception: pass
    return refresh()
def computed_at():
    try: return json.loads(db.kv_get(KEY_PROFIT) or "{}").get("at")
    except Exception: return None
def profitable_set(): return {k for k, v in table().items() if v.get("profitable")}
def badge(k):
    v = table().get(k) or {}
    return "💰" if v.get("profitable") else ""

def in_tier(k, tier):
    if not tier: return SG.status(k) in SG.TIERS
    if tier == "profitable": return k in profitable_set()
    return SG.status(k) == tier

def should_push(k, mode=None):
    mode = mode or get_mode(); st = SG.status(k)
    if mode == "primary": return st == "primary"
    return st in SG.TIERS   # primary_secondary

def mute(rows):
    """Record signals that were saved but not pushed (for the summary)."""
    try:
        cur = json.loads(db.kv_get(KEY_MUTED) or "[]")
        now = datetime.now(timezone.utc).isoformat()
        cur += [dict(t=now, symbol=r.get("symbol"), strategy=r.get("strategy")) for r in rows]
        db.kv_set(KEY_MUTED, json.dumps(cur[-300:]))
    except Exception: pass
def muted_since(hours):
    try:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [m for m in json.loads(db.kv_get(KEY_MUTED) or "[]") if datetime.fromisoformat(m["t"]) >= since]
    except Exception: return []

def filter_push(rows, key=lambda r: SG.eff(r.get("strategy"), r.get("tags"))):
    """Split rows into (push, muted) by the current alert mode; muted ones are recorded."""
    mode = get_mode()
    push = [r for r in rows if should_push(key(r), mode)]; muted = [r for r in rows if r not in push]
    if muted: mute(muted)
    return push, muted

def state():
    t = table()
    return dict(mode=get_mode(), mode_label=MODE_LABEL[get_mode()], modes=list(MODES), mode_labels=MODE_LABEL,
                profitable=sorted(k for k, v in t.items() if v.get("profitable")), table=t, computed_at=computed_at(),
                definition=f"Profitable = live closed net R after fees over the last {WINDOW} days > 0 with at least {MIN_N} closed trades; "
                           f"if fewer live trades, the latest backtest (>= {MIN_N} trades, net R > 0); otherwise 'not enough data'. Recomputed every scan.")
