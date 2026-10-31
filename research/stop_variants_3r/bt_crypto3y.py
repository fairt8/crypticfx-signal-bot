"""3-year crypto replay (bt_crypto.py generalised): every crypto strategy (FVG, FVG-D1, FVG-PLAN, FVG+TREND, CHK, BRK,
PAT-WEDGE, PAT-CUP, DON20) + MF-REJ and PAT-TRIPLE ported to crypto, with the live signal functions, on Binance 15m bulk
data (data/c15_<SYM>.pkl from fetch_crypto.py, Oct 2022 -> now; 1H/4H/1D resampled from 15m). Signals from T0=2023-10-01
(or listing + warm-up). Crypto ports: MF-REJ has no session filter (24/7: every UTC hour allowed, live 2-signals/day cap kept),
it is ATR-based (no pips) so parameters are unchanged; PAT-TRIPLE = pat_series(..., "crypto") (market only changes cup/brk rules).
Both use the crypto fee (0.10% round trip), the $1M/24h volume gate and skip stops < 0.3% like BRK/PAT. For each signal: current live outcome ("live") + 5 stop variants at a fixed 3R TP,
simulated on 15m bars. Writes out/<SYM>.csv (one row per signal x variant)."""
import sys, os, pickle, time
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.abspath(os.path.join(HERE, "../..")))
import numpy as np, pandas as pd
from app import config as C, strategy, outcomes
from app import patterns_live as P, don20 as D
from app.backtest_all import mtm
from engine import Candles, resample, run_variants
C.MIN_STOP_PCT_CRYPTO = 0.3
DATA = os.path.join(HERE, "data"); OUT = os.path.join(HERE, "out3y")
ONLY = set(filter(None, os.environ.get("ONLY", "").split(",")))
def want(nm): return not ONLY or nm in ONLY
OUT = os.path.join(HERE, os.environ.get("CRYOUT", "out3y"))
T0 = pd.Timestamp(os.environ.get("T0", "2023-10-01"), tz="UTC")
COST = 0.001; MINSTOP = 0.003; WARM = pd.Timedelta(days=12)
HZ = {"FVG": 400, "FVG-D1": 400, "FVG-PLAN": 400, "FVG+TREND": 400, "CHK": 400, "BRK": 180*16, "PAT-WEDGE": 180*16, "PAT-CUP": 180*16, "DON20": 10**9, "MF-REJ": 240*4, "PAT-TRIPLE": 180*16}

def rs(m, f):
    x = m.set_index("t").resample(f, origin="epoch").agg(dict(o="first", h="max", l="min", c="last", v="sum")).dropna()
    x["t"] = x.index; x["ct"] = x.t + pd.Timedelta(f); return x.reset_index(drop=True)

def run(sym):
    m = pd.read_pickle(f"{DATA}/c15_{sym}.pkl")
    h4 = rs(m, "4h"); d1 = rs(m, "1D"); now_ = m.ct.iloc[-1]
    h4 = h4[h4.ct <= now_].reset_index(drop=True); d1 = d1[d1.ct <= now_].reset_index(drop=True)
    T = m.t.values; H, L, Cc, V = m.h.values, m.l.values, m.c.values, m.v.values
    QV = pd.Series(V*Cc).rolling(96, min_periods=1).sum().values
    t0 = max(T0, m.t.iloc[0] + WARM); t0n = t0.tz_convert(None).to_datetime64()
    cnd = {"c30": Candles(resample(m, "30min")), "c60": Candles(resample(m, "1h"))}
    sigs = []   # dict(strategy, t, direction, entry, sl, limit, j0, live_status, live_r)
    def gate(j): return QV[j] >= C.MIN_CRYPTO_VOL_USD
    # ---- FVG family (15m)
    c4 = h4.ct.values; seen = set()
    for j in (range(400, len(m) - 1) if want("FVG") else []):
        if m.t.iloc[j] < t0 or not (L[j] > H[j-2] or H[j] < L[j-2]): continue
        now = m.ct.iloc[j]; k = np.searchsorted(c4, now.to_datetime64(), side="right")
        if k < 60: continue
        try: sig = strategy.analyze(sym, "crypto", h4.iloc[max(0, k-300):k].reset_index(drop=True), m.iloc[j-399:j+1].reset_index(drop=True))
        except Exception: continue
        if not sig or sig["confirm_time"] in seen or (sig.get("setup_score") or 0) < C.MIN_POST_SCORE: continue
        seen.add(sig["confirm_time"])
        if not gate(j): continue
        fut = m.iloc[j+1:j+401]; vs = [("FVG", sig)]
        if strategy.daily_bias(d1[d1.ct <= now], now) == sig["direction"]: vs.append(("FVG-D1", dict(sig, strategy="FVG-D1")))
        if any("EMA50/EMA200 trend aligned" in w for w in sig["reasons"]): vs.append(("FVG+TREND", dict(sig, strategy="FVG+TREND")))
        pv = strategy.plan_variant(sig)
        if pv: vs.append(("FVG-PLAN", pv))
        for nm, s in vs:
            st, _, _, r = outcomes.simulate(dict(s, status="pending", filled_at=None), fut)
            if st in ("pending", "expired"): continue      # live rule: never filled -> no trade
            if r is None: r = mtm(s, fut)                    # still open after 400 bars -> marked to market
            sigs.append(dict(strategy=nm, t=now, direction=s["direction"], entry=s["entry"], sl=s["sl"], limit=True, j0=j+1, live_status=st, live_r=r))
    # ---- CHK (1H, market entry)
    h1 = rs(m, "1h"); h1 = h1[h1.ct <= now_].reset_index(drop=True)
    ct15 = m.ct.values
    for i in (range(225, len(h1) - 1) if want("CHK") else []):
        if h1.t.iloc[i] < t0: continue
        now = h1.ct.iloc[i]
        try: sig = strategy.analyze_chk(sym, "crypto", h4[h4.ct <= now].tail(300).reset_index(drop=True), h1.iloc[i-260:i+1].reset_index(drop=True), max_age_min=10**8)
        except Exception: continue
        if not sig: continue
        s0 = int(np.searchsorted(ct15, now.to_datetime64(), side="right"))
        if s0 >= len(m) or not gate(s0-1): continue
        fut = m.iloc[s0:s0+400]; st, _, _, r = outcomes.simulate(sig, fut)
        sigs.append(dict(strategy="CHK", t=now, direction=sig["direction"], entry=sig["entry"], sl=sig["sl"], limit=False, j0=s0,
                         live_status=st, live_r=r if st in ("tp", "sl", "be") else mtm(sig, fut)))
    # ---- BRK / PAT-WEDGE / PAT-CUP (4H, market entry at the 4H close)
    todo = [("BRK",) + P.brk_series(h4, "crypto", levels=C.BRK_LEVELS)] + [(nm,) + P.pat_series(nm, h4, "crypto") for nm, v in P.PAT.items() if v[0] == "crypto" or nm == "PAT-TRIPLE"]
    todo = [x for x in todo if want(x[0])]
    for nm, dd, aa, E in todo:
        R = 3.0 if nm == "BRK" else P.PAT[nm][5]; seen = set()
        for e in E:
            ct = dd.t.iloc[e["k"]] + pd.Timedelta("4h")
            if ct < t0 or abs(e["entry"]-e["sl"])/e["entry"] < 0.003 or (e["k"], e["dir"]) in seen: continue
            seen.add((e["k"], e["dir"]))
            s0 = int(np.searchsorted(T, ct.to_datetime64(), side="left"))
            if s0 >= len(m) or not gate(max(s0-1, 0)): continue
            entry, sl = float(e["entry"]), float(e["sl"]); sd = 1 if e["dir"] == "long" else -1
            s = dict(direction=e["dir"], entry=entry, sl=sl, tp=entry + sd*R*abs(entry-sl), rr=R, confirm_time=str(ct), status="open", filled_at=str(ct), strategy=nm)
            fut = dd.iloc[e["k"]+1:e["k"]+181]; st, _, _, r = outcomes.simulate(s, fut)     # live/backtest_all: outcome on 4H bars
            sigs.append(dict(strategy=nm, t=ct, direction=e["dir"], entry=entry, sl=sl, limit=False, j0=s0, live_status=st,
                             live_r=r if st in ("tp", "sl", "be") else mtm(s, fut)))
    # ---- MF-REJ ported to crypto (1H flip-candle entry at market; 24/7 so every hour is an allowed "session")
    strategy.MF_SESSIONS_UTC["24h"] = (0, 24); strategy.MF_PAIRS[sym] = ["24h"]; day_n = {}
    for i in (range(300, len(h1) - 1) if want("MF-REJ") else []):
        ct = h1.ct.iloc[i]
        if h1.t.iloc[i] < t0: continue
        O_, C_ = h1.o.values, h1.c.values
        if not ((C_[i-1] < O_[i-1] and C_[i] > O_[i]) or (C_[i-1] > O_[i-1] and C_[i] < O_[i])): continue
        dk = h1.t.iloc[i].date()
        if day_n.get(dk, 0) >= 2: continue
        hh = h4[h4.ct <= ct]
        try: sig = strategy.analyze_mf(sym, hh.tail(400).reset_index(drop=True), h1.iloc[max(0, i-800):i+1].reset_index(drop=True),
                                       max_age_min=10**8, today_count=day_n.get(dk, 0), h4_long=hh.tail(2400).reset_index(drop=True))
        except Exception: continue
        if not sig or abs(sig["entry"]-sig["sl"])/sig["entry"] < MINSTOP: continue
        s0 = int(np.searchsorted(ct15, ct.to_datetime64(), side="right"))
        if s0 >= len(m) or not gate(s0-1): continue
        day_n[dk] = day_n.get(dk, 0) + 1
        fut = h1.iloc[i+1:i+241]; st, _, _, r = outcomes.simulate(sig, fut)
        sigs.append(dict(strategy="MF-REJ", t=ct, direction=sig["direction"], entry=sig["entry"], sl=sig["sl"], limit=False, j0=s0,
                         live_status=st, live_r=r if st in ("tp", "sl", "be") else mtm(sig, fut)))
    # ---- DON20 (daily). Every signal day is a candidate; one position per coin is enforced per variant in report.py.
    if want("DON20") and not D.is_stock(sym):
        A = D.atr(d1); pos = None
        for i in range(30, len(d1)):
            b = d1.iloc[i]
            if b.ct < t0: continue
            sg = D.signal(d1.iloc[:i+1])
            if not sg: continue
            side, a = sg; sd = 1 if side == "long" else -1; e = float(b.c); s0 = int(np.searchsorted(T, b.ct.to_datetime64(), side="left"))
            if s0 >= len(m) or not gate(max(s0-1, 0)): continue
            # live rule outcome: 3xATR chandelier on daily bars (as backtest_all.don20_replay), exit at stop or gapped open
            st_, best, stop, ex, xt = "open", e, e - sd*D.K*a, None, None
            for q in range(i+1, len(d1)):
                bq = d1.iloc[q]
                if (sd == 1 and bq.l <= stop) or (sd == -1 and bq.h >= stop):
                    ex = min(stop, bq.o) if sd == 1 else max(stop, bq.o); st_ = "closed"; xt = bq.ct; break
                best = max(best, bq.c) if sd == 1 else min(best, bq.c); ns = best - sd*D.K*float(A.iloc[q])
                stop = max(stop, ns) if sd == 1 else min(stop, ns)
            if ex is None: ex = float(d1.c.iloc[-1]); xt = d1.ct.iloc[-1]
            g, n = D._r(dict(direction=side, entry=e, init_stop=e - sd*D.K*a), ex)
            sigs.append(dict(strategy="DON20", t=b.ct, direction=side, entry=e, sl=e - sd*D.K*a, limit=False, j0=s0, live_status=st_, live_r=g,
                             live_net=n, live_exit_t=str(xt)))
    # ---- variants
    rows = []
    for k, s in enumerate(sigs):
        rf = abs(s["entry"] - s["sl"])/s["entry"]
        base = dict(sid=f"{os.environ.get('SIDP', '')}{sym}-{k}", strategy=s["strategy"], symbol=sym, t=str(s["t"]), direction=s["direction"])
        ln = s.get("live_net", s["live_r"] - COST/rf if s["live_r"] is not None else None)
        rows.append(dict(base, variant="live", status=s["live_status"], r=s["live_r"], net_r=ln, risk_pct=100*rf, floored=False,
                         fill_t=str(s["t"]), exit_t=s.get("live_exit_t", "")))
        end = len(T) if s["strategy"] == "DON20" else s["j0"] + HZ[s["strategy"]] + (192 if s["limit"] else 0)
        for v in run_variants(s, T, H, L, Cc, s["j0"], end, cnd, MINSTOP, COST): rows.append(dict(base, **v))
    return rows

def one(sym):
    f = f"{OUT}/{sym}.csv"
    if os.path.exists(f): return sym, "cached"
    t = time.time()
    try: rows = run(sym)
    except Exception as e: return sym, f"ERR {type(e).__name__}: {e}"
    pd.DataFrame(rows).to_csv(f, index=False); return sym, f"{len(rows)} rows {time.time()-t:.0f}s"

if __name__ == "__main__":
    import json
    from concurrent.futures import ProcessPoolExecutor
    os.makedirs(OUT, exist_ok=True); syms = json.load(open(f"{DATA}/syms50.json"))
    if os.environ.get("SKIPDONE"): syms = [x for x in syms if not os.path.exists(f"{OUT}/{x}.csv")]
    if len(sys.argv) > 1: syms = sys.argv[1:]
    with ProcessPoolExecutor(int(os.environ.get("W", "4"))) as ex:
        for s, msg in ex.map(one, syms): print(s, msg, flush=True)
