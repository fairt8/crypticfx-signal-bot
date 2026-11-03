"""DON28 vs DON20 over 3+ years (monthly routine; backtest only, nothing live).
DON20 = live entry rules (daily close beyond the prior 20D high/low, $1M daily quote volume) + live exits (3xATR20 stop,
3xATR chandelier trail, no TP), fees 0.1%/side. DON28 = DON20 + coin's own 200D SMA (longs only above it, shorts only below;
no filter while the SMA is unknown, as filters.py 'coin_ma'). Universe: today's top-N Binance USDT coins (stablecoins / stock
tokens excluded) + BTC, daily klines from data-api.binance.vision (2 pages, ~2021-05 ->). Entries from T0 (default 2023-10-01).
Live impact: open DON20 positions from the bot DB (read-only; URL read from ../../.neon_url, never printed)."""
import sys, os, json, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
import numpy as np, pandas as pd, requests
N, COST, K = 20, 0.001, 3.0
T0 = pd.Timestamp(os.environ.get("T0", "2023-10-01")); NC = int(os.environ.get("NCOINS", "130"))
B = "https://data-api.binance.vision/api/v3"; D = f"{HERE}/d1x3"
SKIP = {"UUSDT", "RWUSDUSDT", "USDEUSDT", "USD1USDT", "FDUSDUSDT", "USDCUSDT", "TUSDUSDT", "EURUSDT", "XUSDUSDT", "BFUSDUSDT", "PAXGUSDT", "XAUTUSDT"}
COLS = "t o h l c v ct qv n tb tq i".split()
def get(s, **kw):
    for k in range(3):
        try:
            r = requests.get(B + "/klines", params=dict(symbol=s, interval="1d", limit=1000, **kw), timeout=30).json()
            if isinstance(r, list): return pd.DataFrame(r, columns=COLS)[["t", "o", "h", "l", "c", "qv"]].astype(float)
        except Exception: time.sleep(1 + k)
    return pd.DataFrame(columns=["t", "o", "h", "l", "c", "qv"])
def fetch(s):
    f = f"{D}/{s}.csv"
    if os.path.exists(f) and time.time() - os.path.getmtime(f) < 6*3600: return
    a = get(s)
    if not len(a): return
    b = get(s, endTime=int(a.t.min()) - 1)
    pd.concat([b, a]).drop_duplicates("t").sort_values("t").to_csv(f, index=False)
def load(s):
    d = pd.read_csv(f"{D}/{s}.csv"); d["t"] = pd.to_datetime(d.t, unit="ms")
    d = d[d.t + pd.Timedelta("1D") <= pd.Timestamp.now(tz="UTC").tz_convert(None)].reset_index(drop=True)   # completed days only
    tr = pd.concat([d.h-d.l, (d.h-d.c.shift()).abs(), (d.l-d.c.shift()).abs()], axis=1).max(axis=1); d["atr"] = tr.rolling(N).mean()
    ma = d.c.rolling(200).mean(); d["cma"] = np.where(ma.isna(), 0, np.where(d.c > ma, 1, -1)); return d
def run(d, filt):
    A = d.atr.values; o, h, l, c, qv, cma = (d[x].values for x in "o h l c qv cma".split()); t = d.t.values; out = []; pos = None
    def fin(p, x, i, st):
        g = p["sd"]*(x-p["e"])/p["risk"]; out.append(dict(t=t[p["i"]], exit=t[i], dir=p["sd"], n=g - COST*(p["e"]+x)/p["risk"], status=st))
    for i in range(N+2, len(d)):
        if pos:
            sd, stp = pos["sd"], pos["stop"]
            if (sd == 1 and l[i] <= stp) or (sd == -1 and h[i] >= stp): fin(pos, min(stp, o[i]) if sd == 1 else max(stp, o[i]), i, "closed"); pos = None; continue
            pos["best"] = max(pos["best"], c[i]) if sd == 1 else min(pos["best"], c[i]); ns = pos["best"]-sd*K*A[i]
            pos["stop"] = max(stp, ns) if sd == 1 else min(stp, ns); continue
        if pd.Timestamp(t[i]) < T0: continue
        a = A[i]
        if not a or a != a or a <= 0 or qv[i] < 1e6: continue
        side = 1 if c[i] > h[i-N:i].max() else (-1 if c[i] < l[i-N:i].min() else 0)
        if not side or (filt and cma[i] and cma[i] != side): continue
        e = c[i]; st = e - side*K*a
        if side == 1 and st <= 0: continue
        pos = dict(sd=side, e=e, risk=abs(e-st), stop=st, best=e, i=i)
    if pos: fin(pos, c[-1], len(d)-1, "open")
    return out
def stats(x):
    if not len(x): return dict(n=0)
    x = x.sort_values("exit"); eq = x.n.cumsum(); dd = float((eq.cummax() - eq).max())
    return dict(n=len(x), win=round(100*(x.n > 0).mean(), 1), net=round(x.n.sum(), 1), avg=round(x.n.mean(), 3), mdd=round(dd, 1))
if __name__ == "__main__":
    from app import binance, don20
    os.makedirs(D, exist_ok=True)
    syms = [s for s in binance.top_usdt_symbols(NC + 40) if not don20.is_stock(s) and s not in SKIP][:NC]
    if "BTCUSDT" not in syms: syms.append("BTCUSDT")
    # live open DON20 positions (read-only)
    live = []
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(open(os.path.join(HERE, "../../.neon_url")).read().strip(), row_factory=dict_row, connect_timeout=10) as cn:
            live = cn.execute("SELECT symbol, direction, signal_day, entry, init_stop FROM don20 WHERE status='open'").fetchall()
    except Exception as e: print("live DB read failed:", type(e).__name__, "-> using the bot's public /api/don20", flush=True)
    if not live:
        try: live = [r for r in requests.get("http://127.0.0.1:8100/api/don20", timeout=30).json() if r["status"] == "open"]
        except Exception as e: print("live API read failed:", type(e).__name__)
    for s in dict.fromkeys(syms + [r["symbol"] for r in live]): fetch(s)
    T = {"DON20": [], "DON28": []}; feats = {}
    for s in syms:
        if not os.path.exists(f"{D}/{s}.csv"): continue
        d = load(s); feats[s] = d
        for k, f in (("DON20", False), ("DON28", True)): T[k] += [dict(r, sym=s) for r in run(d, f)]
    end = max(d.t.max() for d in feats.values()); L120 = end - pd.Timedelta(days=120); res = {}
    for k in T:
        x = pd.DataFrame(T[k]); x["t"] = pd.to_datetime(x.t)
        r = stats(x) | {"closed_net": round(x[x.status == "closed"].n.sum(), 1), "open": int((x.status == "open").sum()), "open_r": round(x[x.status == "open"].n.sum(), 1)}
        r["years"] = {int(y): stats(g) for y, g in x.groupby(x.t.dt.year)}
        r["last12m"] = stats(x[x.t >= end - pd.DateOffset(years=1)]); r["last120d"] = stats(x[x.t >= L120]); res[k] = r
    # live impact
    blk = []; unk = 0
    for p in live:
        d = feats.get(p["symbol"])
        if d is None and os.path.exists(f"{D}/{p['symbol']}.csv"): d = load(p["symbol"])
        sd = 1 if p["direction"] == "long" else -1
        if d is None: unk += 1; continue
        day = pd.Timestamp(str(p["signal_day"])[:10]); m = d[d.t <= day]
        if not len(m): unk += 1; continue
        cm = int(m.cma.iloc[-1]); now_r = sd*(float(d.c.iloc[-1]) - p["entry"])/abs(p["entry"] - p["init_stop"]) if p["init_stop"] else 0
        if cm and cm != sd: blk.append(dict(symbol=p["symbol"], dir=p["direction"], day=str(day.date()), now_r=round(now_r, 2)))
    lv = dict(open=len(live), blocked=len(blk), blocked_now_r=round(sum(b["now_r"] for b in blk), 2), unknown=unk)
    json.dump(dict(period=f"{T0.date()} -> {end.date()}", coins=len(feats), results=res, live=lv, blocked=blk), open(f"{HERE}/don28_3y.json", "w"), indent=1)
    print(json.dumps(dict(period=f"{T0.date()} -> {end.date()}", coins=len(feats), live=lv), indent=1))
    for k, r in res.items():
        print(k, {a: r[a] for a in ("n", "win", "net", "avg", "mdd", "closed_net", "open", "open_r")}, "| 12m", r["last12m"], "| 120d", r["last120d"])
        print("   years", {y: (v["n"], v.get("net")) for y, v in r["years"].items()})
