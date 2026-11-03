"""Incremental refresh (monthly routine): append new Binance 15m bars (daily/monthly bulk files) to every cached data/c15_<SYM>.pkl
for the same universe (data/syms50.json), and merge a fresh Yahoo 1H/30m pull into data/fx.pkl (old history kept). No keys."""
import sys, os, pickle, json
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
import pandas as pd
from fetch_crypto import get, parse, B
def crypto(sym):
    f = f"{HERE}/data/c15_{sym}.pkl"; d = pd.read_pickle(f); now = pd.Timestamp.now(tz="UTC")
    last = d.t.iloc[-1]; parts = []
    for day in pd.date_range((last + pd.Timedelta("15min")).normalize().tz_convert(None), (now - pd.Timedelta("1D")).normalize().tz_convert(None), freq="D"):
        b = get(f"{B}/daily/klines/{sym}/15m/{sym}-15m-{day:%Y-%m-%d}.zip")
        if b: parts.append(parse(b))
    if not parts: return sym, "no new"
    n = pd.concat(parts); n["ct"] = n.t + pd.Timedelta("15min")
    m = pd.concat([d, n]).drop_duplicates("t").sort_values("t").reset_index(drop=True)
    m["t"] = pd.to_datetime(m.t, utc=True); m["ct"] = pd.to_datetime(m.ct, utc=True)
    m = m[m.ct <= now].reset_index(drop=True); m.to_pickle(f); return sym, f"+{len(m)-len(d)} bars -> {m.t.iloc[-1]}"
def fx():
    from app import config as C, strategy
    from app.backtest_all import fx_data
    from bt_fx import fx30
    f = f"{HERE}/data/fx.pkl"; old, o30 = pickle.load(open(f, "rb"))
    pairs = list(dict.fromkeys(list(strategy.MF_PAIRS) + C.PAT_FX)); new = fx_data(pairs); n30 = fx30(pairs)
    def mg(a, b):
        if b is None or not len(b): return a
        if a is None or not len(a): return b
        return pd.concat([a, b]).drop_duplicates("t", keep="last").sort_values("t").reset_index(drop=True)
    out = {p: mg(old.get(p), new.get(p)) for p in set(old) | set(new)}; out30 = {p: mg(o30.get(p), n30.get(p)) for p in set(o30) | set(n30)}
    pickle.dump((out, out30), open(f, "wb"))
    for p in sorted(out): print(p, out[p].t.iloc[0], "->", out[p].t.iloc[-1], "30m", len(out30.get(p, [])), flush=True)
if __name__ == "__main__":
    from concurrent.futures import ThreadPoolExecutor
    if "fx" not in sys.argv[1:]:
        syms = json.load(open(f"{HERE}/data/syms50.json"))
        with ThreadPoolExecutor(6) as ex:
            for s, msg in ex.map(crypto, syms): print(s, msg, flush=True)
    if "crypto" not in sys.argv[1:]: fx()
