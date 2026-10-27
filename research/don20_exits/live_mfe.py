import json, pandas as pd
from app import don20 as D, binance
rows = D._rows("SELECT * FROM don20 ORDER BY id")
px = D.prices(); out = []
for p in rows:
    try:
        d = binance.klines(p["symbol"], "1d", 40)
    except Exception: continue
    sd = 1 if p["direction"] == "long" else -1; risk = abs(p["entry"] - p["init_stop"])
    o = pd.Timestamp(p["opened_at"]); end = pd.Timestamp(p["closed_at"]) if p["closed_at"] else None
    w = d[(d.ct > o)]
    if end is not None: w = w[w.t <= end]
    if not len(w): mfe = mae = 0.0
    else:
        mfe = sd*((w.h.max() if sd == 1 else w.l.min()) - p["entry"])/risk
        mae = sd*((w.l.min() if sd == 1 else w.h.max()) - p["entry"])/risk
    cur = px.get(p["symbol"]); g = n = None
    if p["status"] == "open" and cur: g, n = D._r(p, cur)
    out.append(dict(id=p["id"], sym=p["symbol"], dir=p["direction"], day=p["signal_day"], status=p["status"], risk_pct=round(100*risk/p["entry"], 2),
                    mfe=round(mfe, 2), mae=round(mae, 2), now_g=None if g is None else round(g, 2), now_n=None if n is None else round(n, 2),
                    net_r=p["net_r"], days=len(w)))
print(json.dumps(out))
