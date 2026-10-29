"""FVG-PLAN v2 research backtest (no live change). See README.md for the rules and results.
Per coin (15m + 4h Binance spot, data/ from fetch.py):
  A) BASELINE: current live FVG-PLAN replayed exactly like app/backtest_all (strategy.analyze on every completed 15m FVG,
     setup_score >= 70, strategy.plan_variant, outcomes.simulate on the next 400 15m bars, 48h limit expiry), plus
     single-step add-on features recorded at the confirm bar (4H bias, recent liquidity sweep) and alternative TPs.
  B) V2 (the 6-step plan): 4H bias -> 15m equal highs/lows -> sweep (wick through, close back inside) against the bias ->
     first 15m FVG in the bias direction within 16 bars -> limit entry at FVG / OB / OTE -> SL beyond sweep wick + 0.1 ATR ->
     TP at opposing liquidity (EQH/EQL, 4H swing, unfilled 4H FVG) or fixed 2R / 3R.
Writes out/<SYM>_base.csv and out/<SYM>_v2.csv. Costs are applied in report.py (0.10% round trip / stop distance)."""
import sys, os, pickle, json, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import numpy as np, pandas as pd
from app import config as C, strategy, outcomes
from app.forex import in_major_session
C.MIN_STOP_PCT_CRYPTO = 0.3
WARM = pd.Timedelta(days=12)      # skip the first 12 days of 15m data (indicator / 4H window warm-up)
CONF_BARS = 16                    # 15m FVG must complete within 16 bars (4h) of the sweep (same quick-reaction rule as FVG-PLAN)
FUT = 400                         # bars to follow a trade (same as backtest_all)
TOLS = (0.0005, 0.001, 0.002)     # equal-level tolerance (fraction of price)
LOOK15, LOOK1H = 480, 960         # liquidity lookback in 15m bars: 5 days of 15m pivots, 10 days of 1H pivots
EXPIRY = pd.Timedelta("48h")

def piv(h, l, k=3):
    s = pd.Series(h); t = pd.Series(l)
    ph = (s == s.rolling(2*k+1, center=True).max()).values; pl = (t == t.rolling(2*k+1, center=True).min()).values
    return ph, pl
def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h-l, np.maximum(abs(h-pc), abs(l-pc))); return pd.Series(tr).rolling(n, min_periods=1).mean().values

def sim(d, entry, sl, tp, x, T, H, L, Cc):
    """numpy twin of outcomes.simulate for a non-PTP strategy: limit fill within 48h, same-bar SL wins, unresolved -> marked to market.
    Returns (status, r) with r gross R."""
    sd = 1 if d == "long" else -1; risk = abs(entry - sl); t0 = T[x+1] if x+1 < len(T) else None
    if t0 is None: return "nodata", None
    end = min(len(T), x+1+FUT); filled = False
    for b in range(x+1, end):
        if not filled:
            if (L[b] <= entry) if sd == 1 else (H[b] >= entry): filled = True
            elif T[b] - t0 > EXPIRY: return "expired", None
            else: continue
        if (L[b] <= sl) if sd == 1 else (H[b] >= sl): return "sl", -1.0
        if (H[b] >= tp) if sd == 1 else (L[b] <= tp): return "tp", (tp-entry)*sd/risk
    if not filled: return "expired", None
    return "open", (Cc[end-1]-entry)*sd/risk

class Coin:
    def __init__(s, sym):
        h4, m, d1 = pickle.load(open(f"data/{sym}.pkl", "rb"))
        s.sym, s.h4, s.m = sym, h4, m
        s.T = m.t.values; s.CT = m.ct.values; s.O, s.H, s.L, s.Cc, s.V = (m[k].values for k in "ohlcv")
        s.A = atr(s.H, s.L, s.Cc); s.QV = pd.Series(s.V*s.Cc).rolling(96, min_periods=1).sum().values   # ~24h quote volume
        s.t0 = m.t.iloc[0] + WARM
        # 15m pivots (k=3), usable from bar p+4
        ph, pl = piv(s.H, s.L); s.p15h = np.where(ph)[0]; s.p15l = np.where(pl)[0]
        # 1H pivots mapped to 15m indices
        h1 = m.set_index("t").resample("1h", origin="epoch").agg(dict(o="first", h="max", l="min", c="last")).dropna()
        a, b = piv(h1.h.values, h1.l.values); ht = h1.index.values
        i_end = np.searchsorted(s.T, ht + np.timedelta64(1, "h")) - 1        # last 15m bar of that hour
        known = np.searchsorted(s.T, ht + np.timedelta64(4, "h"))            # first 15m bar after hour q+3 closes
        s.p1h = (h1.h.values[a], i_end[a], known[a]); s.p1l = (h1.l.values[b], i_end[b], known[b])
        # 4H: bias series (known at each 4H close)
        c4 = h4.c.values; s.ct4 = (h4.t + pd.Timedelta("4h")).values; s.h4h, s.h4l = h4.h.values, h4.l.values
        e50 = pd.Series(c4).ewm(span=50, adjust=False).mean().values
        s.bias_ema = np.where((c4 > e50) & (e50 > np.r_[e50[:5], e50[:-5]]), 1, np.where((c4 < e50) & (e50 < np.r_[e50[:5], e50[:-5]]), -1, 0))
        a4, b4 = piv(s.h4h, s.h4l); s.piv4h = np.where(a4)[0]; s.piv4l = np.where(b4)[0]
        bias = np.zeros(len(h4), int); HH, LL = [], []; ia = ib = 0
        for k in range(len(h4)):
            while ia < len(s.piv4h) and s.piv4h[ia] + 3 <= k: HH.append(s.h4h[s.piv4h[ia]]); ia += 1
            while ib < len(s.piv4l) and s.piv4l[ib] + 3 <= k: LL.append(s.h4l[s.piv4l[ib]]); ib += 1
            if len(HH) >= 2 and len(LL) >= 2:
                if HH[-1] > HH[-2] and LL[-1] > LL[-2]: bias[k] = 1
                elif HH[-1] < HH[-2] and LL[-1] < LL[-2]: bias[k] = -1
        s.bias_st = bias
        s.idx4 = np.searchsorted(s.T, s.ct4)     # first 15m bar after each 4H close
        # 4H FVGs (dir, k, bottom, top)
        s.g4 = [(1, i, s.h4h[i-2], s.h4l[i]) for i in range(2, len(h4)) if s.h4l[i] > s.h4h[i-2]] + \
               [(-1, i, s.h4h[i], s.h4l[i-2]) for i in range(2, len(h4)) if s.h4h[i] < s.h4l[i-2]]
        s.c4 = c4
    def k4(s, j):   # last 4H bar closed at/before the close of 15m bar j
        return int(np.searchsorted(s.ct4, s.CT[j], side="right")) - 1
    # ---------- liquidity ----------
    def pivots_at(s, j, src, side):
        """confirmed pivots usable at bar j: (level, end_idx)"""
        if src == "15m":
            p = s.p15l if side == "low" else s.p15h; p = p[(p + 4 <= j) & (p >= j - LOOK15)]
            return (s.L[p] if side == "low" else s.H[p]), p
        lv, ie, kn = s.p1l if side == "low" else s.p1h; m = (kn <= j) & (ie >= j - LOOK1H)
        return lv[m], ie[m]
    def eq_levels(s, j, src, side, tol, upto=None):
        """untouched equal-low (side='low') / equal-high levels known at bar j (untouched through bar upto-1, default j-1)."""
        upto = j if upto is None else upto
        lv, ie = s.pivots_at(j, src, side); out = []
        if len(lv) < 2: return out
        o = np.argsort(lv); lv, ie = lv[o], ie[o]
        for a in range(len(lv) - 1):
            b = a + 1
            if abs(lv[b] - lv[a]) > tol * lv[a]: continue
            grp = [a, b]
            L = min(lv[a], lv[b]) if side == "low" else max(lv[a], lv[b]); first = min(ie[a], ie[b])
            if first + 1 >= upto: continue
            seg = s.L[first+1:upto] if side == "low" else s.H[first+1:upto]
            if (side == "low" and seg.min() < L) or (side == "high" and seg.max() > L): continue
            out.append(L)
        return out
    def sweeps(s, src, tol):
        """bars j where the wick took an untouched EQL (long setup) / EQH (short setup) and closed back inside."""
        ev = []
        for j in range(max(1, int(np.searchsorted(s.T, np.datetime64(s.t0.tz_convert(None))))), len(s.T) - 2):
            lo = s.eq_levels(j, src, "low", tol); lv = [L for L in lo if s.L[j] < L < s.Cc[j]]
            if lv: ev.append((j, 1, min(lv)))
            hi = s.eq_levels(j, src, "high", tol); hv = [L for L in hi if s.Cc[j] < L < s.H[j]]
            if hv: ev.append((j, -1, max(hv)))
        return ev
    def any_swing_sweep(s, j, sd):
        """looser: wick through ANY untouched 15m swing low/high (last 5 days) and close back inside."""
        lv, ie = s.pivots_at(j, "15m", "low" if sd == 1 else "high")
        for L, e in zip(lv, ie):
            if e + 1 >= j: continue
            seg = s.L[e+1:j] if sd == 1 else s.H[e+1:j]
            if sd == 1 and seg.min() >= L and s.L[j] < L < s.Cc[j]: return True
            if sd == -1 and seg.max() <= L and s.Cc[j] < L < s.H[j]: return True
        return False
    def unfilled4(s, k, x, d, typ):
        """4H FVGs formed in the last 60 4H bars, known at 4H bar k. typ='zone': same-direction, not closed through (4H close);
        typ='target': opposite-direction, price has not traded into it yet (checked on 15m up to bar x)."""
        out = []
        for gd, i, bot, top in s.g4:
            if i > k or i < k - 60: continue
            st = s.idx4[i]
            if typ == "zone" and gd == d:
                cc = s.c4[i+1:k+1]
                if (d == 1 and (cc < bot).any()) or (d == -1 and (cc > top).any()): continue
                out.append((bot, top))
            elif typ == "target" and gd == -d:
                if d == 1 and s.H[st:x+1].max(initial=-np.inf) < bot: out.append(bot)
                if d == -1 and s.L[st:x+1].min(initial=np.inf) > top: out.append(top)
        return out
    def swings4(s, k, x, d):
        """untouched confirmed 4H swing highs (d=1) / lows (d=-1) of the last 60 4H bars -> HTF liquidity targets."""
        p = s.piv4h if d == 1 else s.piv4l; p = p[(p + 3 <= k) & (p >= k - 60)]; out = []
        for i in p:
            st = s.idx4[i]
            if d == 1 and s.H[st:x+1].max(initial=-np.inf) < s.h4h[i]: out.append(s.h4h[i])
            if d == -1 and s.L[st:x+1].min(initial=np.inf) > s.h4l[i]: out.append(s.h4l[i])
        return out
    def liq_tp(s, d, entry, sl, x, k, tol, src, htf_only):
        risk = abs(entry - sl); c = s.swings4(k, x, d) + s.unfilled4(k, x, d, "target")
        if not htf_only: c += s.eq_levels(x + 1, src, "high" if d == 1 else "low", tol)
        r = sorted(((t - entry) * d / risk, t) for t in c)
        for rr, t in r:
            if rr >= 1.0: return (t, rr) if rr <= 10 else (None, None)
        return None, None

def gate(co, x): return co.QV[x] >= C.MIN_CRYPTO_VOL_USD

def run_v2(co):
    rows = []
    for src in ("15m", "1h"):
        for tol in TOLS:
            for (s_, sd, lvl) in co.sweeps(src, tol):
                # confirmation: first 15m FVG in direction sd with c1 >= sweep bar, completed within CONF_BARS, sweep extreme not broken
                ext = co.L[s_] if sd == 1 else co.H[s_]; x = None
                for j in range(s_ + 2, min(s_ + 2 + CONF_BARS, len(co.T) - 1)):
                    if (sd == 1 and co.L[j] < ext) or (sd == -1 and co.H[j] > ext): break
                    if sd == 1 and co.L[j] > co.H[j-2] and (co.L[j]-co.H[j-2])/co.Cc[j] >= strategy.MIN_GAP_PCT: x = j; break
                    if sd == -1 and co.H[j] < co.L[j-2] and (co.L[j-2]-co.H[j])/co.Cc[j] >= strategy.MIN_GAP_PCT: x = j; break
                if x is None or not gate(co, x): continue
                k = co.k4(x); ks = co.k4(s_)
                if k < 60: continue
                sl = ext - sd * 0.1 * co.A[s_]
                fvg_e = co.L[x] if sd == 1 else co.H[x]           # near edge of the 15m FVG (same as live FVG entry)
                ob = [i for i in range(s_, x - 1) if (co.Cc[i] < co.O[i]) == (sd == 1)]   # last opposite-colour candle before displacement
                ob_e = (co.H[ob[-1]] if sd == 1 else co.L[ob[-1]]) if ob else fvg_e
                hi = co.H[s_:x+1].max(); lo = co.L[s_:x+1].min()
                leg = hi - lo
                ote62 = hi - 0.62 * leg if sd == 1 else lo + 0.62 * leg; ote705 = hi - 0.705 * leg if sd == 1 else lo + 0.705 * leg
                zone = co.unfilled4(ks, s_, sd, "zone"); in_zone = any(co.L[s_] <= t and co.H[s_] >= b for b, t in zone)
                feat = dict(sym=co.sym, src=src, tol=tol, sweep_t=str(co.T[s_]), t=str(co.CT[x]), dir="long" if sd == 1 else "short",
                            bias_st=int(co.bias_st[ks]) * sd, bias_ema=int(co.bias_ema[ks]) * sd, in_zone=int(in_zone),
                            sess=int(in_major_session(pd.Timestamp(co.CT[x]).tz_localize("UTC").to_pydatetime())))
                for en, e in (("fvg", fvg_e), ("ob", ob_e), ("ote62", ote62), ("ote705", ote705)):
                    risk = (e - sl) * sd
                    if risk <= 0 or risk / e * 100 < C.MIN_STOP_PCT_CRYPTO: continue
                    for tpn in ("liq", "htf", "2R", "3R"):
                        if tpn in ("2R", "3R"): rr = float(tpn[0]); tp = e + sd * rr * risk
                        else:
                            tp, rr = co.liq_tp(sd, e, sl, x, k, tol, src, tpn == "htf")
                            if tp is None: continue
                        st, r = sim("long" if sd == 1 else "short", e, sl, tp, x, co.T, co.H, co.L, co.Cc)
                        if r is None: continue
                        rows.append(dict(feat, entry=en, tp=tpn, rr=round(rr, 2), status=st, r=r, rf=risk / e))
    return rows

def run_base(co):
    m, h4 = co.m, co.h4; rows = []; c4 = h4.ct.values; seen = set()
    j0 = int(np.searchsorted(co.T, np.datetime64(co.t0.tz_convert(None))))
    for j in range(max(400, j0), len(m) - 1):
        if not (co.L[j] > co.H[j-2] or co.H[j] < co.L[j-2]): continue
        now = m.ct.iloc[j]; k = np.searchsorted(c4, now.to_datetime64(), side="right")
        if k < 60: continue
        try: sig = strategy.analyze(co.sym, "crypto", h4.iloc[max(0, k-300):k].reset_index(drop=True), m.iloc[j-399:j+1].reset_index(drop=True))
        except Exception: continue
        if not sig or sig["confirm_time"] in seen or (sig.get("setup_score") or 0) < C.MIN_POST_SCORE: continue
        seen.add(sig["confirm_time"])
        pv = strategy.plan_variant(sig)
        if not pv or not gate(co, j): continue
        sd = 1 if pv["direction"] == "long" else -1; e, sl = pv["entry"], pv["sl"]; risk = abs(e - sl); kk = co.k4(j)
        fut = m.iloc[j+1:j+1+FUT]
        st, _, _, r = outcomes.simulate(dict(pv, status="pending", filled_at=None), fut)
        if st in ("pending", "expired") or r is None and st != "open": continue
        if st == "open": r = (fut.c.iloc[-1] - e) * sd / risk
        ws = range(max(0, j - CONF_BARS - 2), j - 1)
        sw = {f"sweep_{src}_{tol}": int(any(any((co.L[b] < L < co.Cc[b]) if sd == 1 else (co.Cc[b] < L < co.H[b])
                                                for L in co.eq_levels(b, src, "low" if sd == 1 else "high", tol)) for b in ws))
              for src in ("15m", "1h") for tol in (0.001,)}
        sw["sweep_swing"] = int(any(co.any_swing_sweep(b, sd) for b in ws))
        row = dict(sym=co.sym, t=str(now), dir=pv["direction"], status=st, r=r, rf=risk / e, score=sig["setup_score"],
                   bias_st=int(co.bias_st[kk]) * sd, bias_ema=int(co.bias_ema[kk]) * sd, sess=int(sig["in_session"]), **sw)
        for nm, tp in (("2R", e + sd * 2 * risk),):
            s2, r2 = sim(pv["direction"], e, sl, tp, j, co.T, co.H, co.L, co.Cc); row["r_2R"] = r2
        tp, rr = co.liq_tp(sd, e, sl, j, kk, 0.001, "15m", False)
        row["r_liq"] = sim(pv["direction"], e, sl, tp, j, co.T, co.H, co.L, co.Cc)[1] if tp is not None else None
        row["r_3R_np"] = sim(pv["direction"], e, sl, pv["tp"], j, co.T, co.H, co.L, co.Cc)[1]   # check numpy sim == outcomes.simulate
        rows.append(row)
    return rows

def one(sym):
    t = time.time(); os.makedirs("out", exist_ok=True)
    try:
        co = Coin(sym)
        if len(co.T) < 3000: return sym, "short history"
        if not os.path.exists(f"out/{sym}_base.csv"): pd.DataFrame(run_base(co)).to_csv(f"out/{sym}_base.csv", index=False)
        if not os.path.exists(f"out/{sym}_v2.csv"): pd.DataFrame(run_v2(co)).to_csv(f"out/{sym}_v2.csv", index=False)
    except Exception as e:
        import traceback; traceback.print_exc(); return sym, f"err {e}"
    return sym, f"ok {time.time()-t:.0f}s"

if __name__ == "__main__":
    from concurrent.futures import ProcessPoolExecutor
    syms = sys.argv[1:] or json.load(open("data/syms.json"))
    with ProcessPoolExecutor(int(os.environ.get("W", "4"))) as ex:
        for s, msg in ex.map(one, syms): print(s, msg, flush=True)
