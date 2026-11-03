"""Parity: live filter (app/candles21.check on live-sized 4H windows) vs the research filter (brk_refresh.py / filter_b.py on the
full history). BRK crypto: stop_variants_3r/out3y, variant 'cur'. PAT-TRIPLE forex: prev_oct30/out3y + out3y, variant 'live'.
Live windows: crypto = last 299 closed Binance 4H klines (close stamped xx:59:59.999 like Binance); forex = 60 days of Yahoo 1H
resampled like forex._h4. Prints mismatches; exit code 1 if any. One symbol at a time (low RAM)."""
import sys, os, glob, pickle
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE); sys.path.insert(0, os.path.join(HERE, "../.."))
import numpy as np, pandas as pd
from filter_b import pat_table, hit, rs, SV
from app import candles21 as K
H4, D1 = pd.Timedelta("4h"), pd.Timedelta("1D")

def research_keep(tabs, g, rules):
    tt = g.t.values.astype("datetime64[ns]").astype(np.int64); opp = np.where(g.direction.values == "long", "short", "long"); ok = np.ones(len(g), bool)
    for tf, lo in rules:
        op = np.where(opp == "short", hit(tabs[tf]["short"], tt, lo(tt)), hit(tabs[tf]["long"], tt, lo(tt))); ok &= ~op
    return ok

def run(strategy, market, files, variant, rules, tfs, base_of, live_h4):
    d = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    d = d[(d.strategy == strategy) & (d.variant == variant)].dropna(subset=["net_r"]).copy()
    d["t"] = pd.to_datetime(d.t, utc=True, format="mixed"); d = d.drop_duplicates(["symbol", "t", "direction"]).reset_index(drop=True)
    n = bad = blk = 0; mism = []
    for sym, g in d.groupby("symbol"):
        base = base_of(sym)
        tabs = {tf: pat_table(rs(base, tf)[lambda x: x.ct <= base.ct.iloc[-1]])["all"] for tf in tfs}
        keep = research_keep(tabs, g, rules)
        for (_, r), kp in zip(g.iterrows(), keep):
            h4 = live_h4(base, r.t)
            assert len(h4) and (h4.t.iloc[-1] + H4) == r.t, (sym, r.t)   # the signal's 4H candle is the last closed bar
            why = K.check(strategy, market, r.direction, h4, r.t); live_keep = why is None
            n += 1; blk += not kp
            if live_keep != kp: bad += 1; mism.append((sym, str(r.t), r.direction, kp, why))
        del base, tabs
    print(f"{strategy} {market}: {n} signals, research filtered {blk}, live filtered {blk + sum(1 if m[3] else -1 for m in mism)}, mismatches {bad}", flush=True)
    for m in mism[:20]: print("  MISMATCH", m)
    return bad

def c15(sym): return pd.read_pickle(f"{SV}/data/c15_{sym}.pkl")[["t", "o", "h", "l", "c", "v", "ct"]]
def brk_h4(base, t):
    x = rs(base, "4h"); x = x[x.ct <= t].tail(299).copy(); x["ct"] = x.t + H4 - pd.Timedelta(1, "ms"); return x.reset_index(drop=True)
_FX = {}
def fx_base(sym):
    if not _FX: _FX.update(pickle.load(open(f"{SV}/data/fx.pkl", "rb"))[0])
    b = _FX[sym][["t", "o", "h", "l", "c"]].dropna().copy(); b["v"] = 0.0; b["ct"] = b.t + pd.Timedelta("1h"); return b
def fx_h4(base, t):
    a = base[(base.t >= t - pd.Timedelta("60D")) & (base.ct <= t)].set_index("t")[["o", "h", "l", "c", "v"]]
    x = a.resample("4h", origin="epoch").agg({"o": "first", "h": "max", "l": "min", "c": "last", "v": "sum"}).dropna()
    x["t"] = x.index; x["ct"] = x.t + H4; return x[x.ct <= t].reset_index(drop=True)

if __name__ == "__main__":
    bad = run("BRK", "crypto", glob.glob(f"{SV}/out3y/*USDT.csv"), "cur",
              (("4h", lambda tt: tt - 2*H4.value), ("1D", lambda tt: tt - 3*D1.value + 1)), ("4h", "1D"), c15, brk_h4)
    for tag, files in (("prev_oct30", glob.glob(f"{SV}/prev_oct30/out3y/fx_*.csv")), ("out3y", glob.glob(f"{SV}/out3y/fx_*.csv"))):
        print("forex trades:", tag)
        bad += run("PAT-TRIPLE", "forex", files, "live", (("1D", lambda tt: tt - D1.value + 1),), ("1D",), fx_base, fx_h4)
    print("PARITY", "OK" if not bad else f"FAILED ({bad})"); sys.exit(1 if bad else 0)
