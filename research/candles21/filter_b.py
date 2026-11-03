"""B) Candlestick filter on existing strategies. Baseline trades = stop_variants_3r/prev_oct30/out3y (the 3-year run the
results3y.md / per_year.md tables came from; DON20 one-position-per-coin rule re-applied AFTER filtering).
Patterns are detected on the strategy's signal timeframe (FVG family 15m, CHK / MF-REJ 1h, BRK / PAT 4h, DON20 1D) and on
the next-higher timeframe ('htf': 15m->1h, 1h->4h, 4h->1D, 1D->none). Only completed candles at or before the signal
time t are used (no look-ahead). Filters (k = how many candles back besides the entry candle):
  req_k   keep only trades with a same-direction pattern completing on the entry candle or the previous k candles
  blk_k   drop trades with an opposite-direction pattern there
  set S   'all' = every detector incl. relaxed '~' gap versions; 'top' = families chosen in part A (TOP below)."""
import sys, os, glob, json, pickle
HERE = os.path.dirname(os.path.abspath(__file__)); SV = os.path.join(HERE, "../stop_variants_3r")
sys.path.insert(0, HERE); import numpy as np, pandas as pd
from patterns import F, detect, signals, base_name
from bt_standalone import rs
STRATS = [("DON20", "crypto", "live"), ("MF-REJ", "forex", "live"), ("PAT-TRIPLE", "forex", "live"), ("PAT-WEDGE", "crypto", "w1.5"),
          ("BRK", "crypto", "cur"), ("CHK", "crypto", "live"), ("FVG-D1", "crypto", "live"), ("FVG-PLAN", "crypto", "w1.5"),
          ("PAT-TRIPLE", "crypto", "w2"), ("FVG+TREND", "crypto", "c60"),
          # robustness only (same filters on sibling stop variants; not used for picking)
          ("BRK", "crypto", "live"), ("BRK", "crypto", "w1.5"), ("BRK", "crypto", "w2"), ("PAT-TRIPLE", "forex", "cur"), ("PAT-TRIPLE", "forex", "w1.5")]
TFS = {"DON20": "1D", "MF-REJ": "1h", "PAT-TRIPLE": "4h", "PAT-WEDGE": "4h", "BRK": "4h", "CHK": "1h", "FVG-D1": "15min", "FVG-PLAN": "15min", "FVG+TREND": "15min"}
HTF = {"15min": "1h", "1h": "4h", "4h": "1D", "1D": None}
TOP = set(json.load(open(f"{HERE}/top_families.json"))) if os.path.exists(f"{HERE}/top_families.json") else set()

def load():
    d = pd.concat([pd.read_csv(f) for f in glob.glob(f"{SV}/prev_oct30/out3y/*.csv")], ignore_index=True)
    d["market"] = np.where(d.symbol.str.endswith("USDT"), "crypto", "forex")
    m = np.zeros(len(d), bool)
    for s, mk, v in STRATS: m |= (d.strategy == s) & (d.market == mk) & (d.variant == v)
    d = d[m].dropna(subset=["net_r"]).copy(); d["t"] = pd.to_datetime(d.t, utc=True, format="mixed"); return d.reset_index(drop=True)

def one_pos(g):
    keep, last = [], None
    for i, r in g.sort_values("t").iterrows():
        ft = pd.Timestamp(r.fill_t) if isinstance(r.fill_t, str) and r.fill_t else r.t
        if ft.tzinfo is None: ft = ft.tz_localize("UTC")
        if last is not None and ft <= last: continue
        keep.append(i); xt = pd.Timestamp(r.exit_t) if isinstance(r.exit_t, str) and r.exit_t else ft
        last = xt.tz_localize("UTC") if xt.tzinfo is None else xt
    return keep

def pat_table(x):
    """-> dict set -> dir -> sorted array of completion close-times (ns)."""
    x = x.reset_index(drop=True); s = F(x); sg = signals(s, detect(s)); ct = x.ct.values.astype("datetime64[ns]").astype(np.int64)
    out = {S: {"long": [], "short": []} for S in ("all", "top")}
    for nm, d, i, f in sg:
        out["all"][d].append(ct[i])
        if base_name(nm) in TOP: out["top"][d].append(ct[i])
    return {S: {d: np.unique(np.array(v, np.int64)) for d, v in dd.items()} for S, dd in out.items()}

def hit(arr, t, lo):
    if not len(arr): return np.zeros(len(t), bool)
    j = np.searchsorted(arr, t, side="right") - 1; ok = j >= 0
    return ok & (arr[np.clip(j, 0, None)] >= lo)

if __name__ == "__main__":
    d = load(); print("rows", len(d), flush=True)
    tfs_needed = sorted({TFS[s] for s, _, _ in STRATS} | {HTF[TFS[s]] for s, _, _ in STRATS if HTF[TFS[s]]})
    fx = pickle.load(open(f"{SV}/data/fx.pkl", "rb"))[0]
    cols = {}
    for sym, g in d.groupby("symbol"):
        if sym.endswith("USDT"):
            base = pd.read_pickle(f"{SV}/data/c15_{sym}.pkl")[["t", "o", "h", "l", "c", "v", "ct"]]
        else:
            base = fx[sym][["t", "o", "h", "l", "c"]].dropna().copy(); base["v"] = 0.0; base["ct"] = base.t + pd.Timedelta("1h")
        tabs = {}
        for tf in tfs_needed:
            if tf == "15min" and not sym.endswith("USDT"): continue
            x = base if (tf == "15min" or (tf == "1h" and not sym.endswith("USDT"))) else rs(base, tf)
            tabs[tf] = pat_table(x[x.ct <= base.ct.iloc[-1]])
        t = g.t.values.astype("datetime64[ns]").astype(np.int64)
        for strat, gg in g.groupby("strategy"):
            idx = gg.index.values; tt = gg.t.values.astype("datetime64[ns]").astype(np.int64)
            sd = gg.direction.values; opp = np.where(sd == "long", "short", "long")
            for lvl, tf in (("sig", TFS[strat]), ("htf", HTF[TFS[strat]])):
                if tf is None or tf not in tabs: continue
                step = pd.Timedelta(tf).value
                for S in ("all", "top"):
                    tb = tabs[tf][S]
                    for k in (0, 2):
                        # signal tf: the entry candle (closes at t) and k earlier ones; htf: the last 1+k completed htf candles
                        lo = tt - k*step if lvl == "sig" else tt - (k+1)*step + 1
                        same = np.where(sd == "long", hit(tb["long"], tt, lo), hit(tb["short"], tt, lo))
                        op = np.where(sd == "long", hit(tb["short"], tt, lo), hit(tb["long"], tt, lo))
                        cols.setdefault(f"req_{lvl}_{S}_{k}", {}).update(dict(zip(idx, same)))
                        cols.setdefault(f"blk_{lvl}_{S}_{k}", {}).update(dict(zip(idx, ~op)))
        print(sym, len(g), flush=True); del base, tabs
    for c, mp in cols.items(): d[c] = pd.Series(mp).reindex(d.index).fillna(True if c.startswith("blk") else False).astype(bool)
    d.drop(columns=[c for c in d.columns if c in ("sid",)]).to_pickle(f"{HERE}/out/filter_b_rows.pkl"); print("saved")
