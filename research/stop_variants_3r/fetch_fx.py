"""Forex 1H history from Dukascopy's free public datafeed (BID hourly candles, one LZMA .bi5 file per pair-month), Sep 2022 ->
last full month, then Yahoo 1H (what live uses) appended after the last Dukascopy bar. Weekend/holiday filler bars (flat, zero
volume) dropped; volume set to 0 like Yahoo FX. GBPCNH isn't on Dukascopy -> GBPUSD*USDCNH; XAUAUD = XAUUSD/AUDUSD (as live).
Saves data/fx3y.pkl (git-ignored)."""
import sys, os, lzma, struct, time, pickle, urllib.request, math
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
from concurrent.futures import ThreadPoolExecutor
import numpy as np, pandas as pd
PAIRS = ['USDJPY','GBPJPY','EURUSD','XAUUSD','AUDUSD','NZDUSD','EURAUD','EURCAD','EURNZD','GBPNZD','AUDCAD','NZDCAD','CADCHF',
         'GBPUSD','USDCHF','USDCAD','EURJPY','USDCNH']
START = pd.Period("2022-09", "M")
def get(p, m):
    u = f"https://datafeed.dukascopy.com/datafeed/{p}/{m.year}/{m.month-1:02d}/BID_candles_hour_1.bi5"
    cf = f"{HERE}/data/duka/{p}_{m}.bi5"     # per-file cache so an interrupted fetch resumes
    for k in range(12):
        try:
            if os.path.exists(cf): b = open(cf, "rb").read()
            else:
                b = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"}), timeout=40).read()
                open(cf + ".tmp", "wb").write(b); os.replace(cf + ".tmp", cf)
            r = lzma.decompress(b) if b else b""; base = pd.Timestamp(m.start_time, tz="UTC")
            a = np.array([struct.unpack(">5if", r[i:i+24]) for i in range(0, len(r), 24)])
            if not len(a): return p, m, None
            return p, m, pd.DataFrame(dict(t=base + pd.to_timedelta(a[:, 0], unit="s"), o=a[:, 1], c=a[:, 2], l=a[:, 3], h=a[:, 4], vol=a[:, 5]))
        except urllib.error.HTTPError as e:
            if e.code == 404: open(cf, "wb").close(); return p, m, None
        except Exception: pass
        time.sleep(3 + 3*k)
    return p, m, "FAIL"
if __name__ == "__main__":
    yfx, _ = pickle.load(open(f"{HERE}/data/fx.pkl", "rb"))
    import yfinance as yf
    from app import forex
    end = pd.Timestamp.now().to_period("M") - 1; jobs = [(p, m) for p in PAIRS for m in pd.period_range(START, end, freq="M")]
    parts = {p: [] for p in PAIRS}; fails = []
    os.makedirs(f"{HERE}/data/duka", exist_ok=True)
    with ThreadPoolExecutor(int(os.environ.get("TH", "16"))) as ex:
        for p, m, d in ex.map(lambda a: get(*a), jobs):
            if isinstance(d, str): fails.append((p, str(m)))
            nd = len(os.listdir(f"{HERE}/data/duka"))
            if nd % 50 == 0: print("files", nd, flush=True)
            elif d is not None: parts[p].append(d)
    print("failed months:", fails, flush=True)
    raw = {}
    for p in PAIRS:
        d = pd.concat(parts[p]).sort_values("t").reset_index(drop=True)
        d = d[~((d.vol == 0) & (d.o == d.h) & (d.l == d.h) & (d.c == d.h))]
        y = yfx.get(p)
        if y is None:   # USDCNH: get Yahoo tail directly
            y = forex.YFinanceProvider()._norm(yf.download("CNH=X", interval="1h", period="60d", progress=False, auto_adjust=False))
            y = y.copy(); y["t"] = y.index; y = y.reset_index(drop=True)
        ref = float(y.c.median()); sc = 10 ** round(math.log10(float(d.c.median()) / ref)) if ref > 0 else 1
        for k in "ohlc": d[k] = d[k] / sc
        y = y[y.t > d.t.iloc[-1]][["t", "o", "h", "l", "c"]]
        d = pd.concat([d[["t", "o", "h", "l", "c"]], y]).reset_index(drop=True); d["v"] = 0.0
        d["ct"] = d.t + pd.Timedelta("1h"); raw[p] = d[d.ct <= pd.Timestamp.now(tz="UTC")].reset_index(drop=True)
        print(p, len(raw[p]), raw[p].t.iloc[0], "->", raw[p].t.iloc[-1], f"scale {sc}", flush=True)
    def comb(a, b, op):
        m = a.merge(b, on="t", suffixes=("a", "b"))
        out = pd.DataFrame({"t": m.t})
        for k in "oc": out[k] = op(m[k+"a"], m[k+"b"])
        hh = op(m.ha, m.hb) if op is np.multiply else op(m.ha, m.lb); ll = op(m.la, m.lb) if op is np.multiply else op(m.la, m.hb)
        out["h"] = np.maximum.reduce([hh, out.o, out.c]); out["l"] = np.minimum.reduce([ll, out.o, out.c]); out["v"] = 0.0
        out["ct"] = out.t + pd.Timedelta("1h"); return out.reset_index(drop=True)
    fx = {p: raw[p] for p in PAIRS if p != "USDCNH"}
    fx["GBPCNH"] = comb(raw["GBPUSD"], raw["USDCNH"], np.multiply); fx["XAUAUD"] = comb(raw["XAUUSD"], raw["AUDUSD"], np.divide)
    for p in ("GBPCNH", "XAUAUD"): print(p, len(fx[p]), fx[p].t.iloc[0], "->", fx[p].t.iloc[-1])
    pickle.dump(fx, open(f"{HERE}/data/fx3y.pkl", "wb"))
