"""4H FVG bias -> tap -> first same-direction 5m FVG -> entry (see strategy-spec.md)."""
import numpy as np, pandas as pd
from . import config as C
from .forex import in_major_session

MIN_GAP_PCT = 0.0002  # 0.02% of price: noise floor [inference]

def fvgs(df):
    h, l = df.h.values, df.l.values; out = []
    for i in range(2, len(df)):
        if l[i] > h[i-2]: out.append(dict(i=i, dir="long", bottom=h[i-2], top=l[i]))
        elif h[i] < l[i-2]: out.append(dict(i=i, dir="short", bottom=h[i], top=l[i-2]))
    px = df.c.values
    return [g for g in out if (g["top"]-g["bottom"])/px[g["i"]] >= MIN_GAP_PCT]

def ema(s, n): return s.ewm(span=n, adjust=False).mean()
def rsi(s, n=14):
    d = s.diff(); u = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean(); v = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100/(1 + u/v.replace(0, np.nan))
def macd_hist(s):
    m = ema(s,12)-ema(s,26); return m - ema(m,9)
def pivots(df, k=3):
    H, L = [], []
    for i in range(k, len(df)-k):
        if df.h.iloc[i] == df.h.iloc[i-k:i+k+1].max(): H.append((i, df.h.iloc[i]))
        if df.l.iloc[i] == df.l.iloc[i-k:i+k+1].min(): L.append((i, df.l.iloc[i]))
    return H, L

def candle_pattern(df, direction):
    """Look at the last 3 candles of df for a pattern from the PDFs (Varsity + KSM candlestick sheet)."""
    if len(df) < 3: return None
    a, b, c = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    def body(x): return abs(x.c-x.o)
    def rng(x): return max(x.h-x.l, 1e-12)
    up = lambda x: x.c > x.o; dn = lambda x: x.c < x.o
    if direction == "long":
        if dn(b) and up(c) and c.c >= b.o and c.o <= b.c: return "bullish engulfing"
        if min(c.o,c.c)-c.l >= 2*body(c) and c.h-max(c.o,c.c) <= body(c)+1e-12: return "hammer"
        if dn(a) and body(b) < 0.3*body(a) and up(c) and c.c > (a.o+a.c)/2: return "morning star"
        if dn(a) and up(b) and b.c < a.o and b.o > a.c and up(c) and c.c > a.o: return "three inside up"
        if abs(b.l-c.l) <= 0.05*rng(c) and dn(b) and up(c): return "tweezer bottom"
        if body(c) <= 0.1*rng(c) and c.h-max(c.o,c.c) <= 0.1*rng(c): return "dragonfly doji"
    else:
        if up(b) and dn(c) and c.c <= b.o and c.o >= b.c: return "bearish engulfing"
        if c.h-max(c.o,c.c) >= 2*body(c) and min(c.o,c.c)-c.l <= body(c)+1e-12: return "shooting star"
        if up(a) and body(b) < 0.3*body(a) and dn(c) and c.c < (a.o+a.c)/2: return "evening star"
        if up(a) and dn(b) and b.c > a.o and b.o < a.c and dn(c) and c.c < a.o: return "three inside down"
        if abs(b.h-c.h) <= 0.05*rng(c) and up(b) and dn(c): return "tweezer top"
        if body(c) <= 0.1*rng(c) and min(c.o,c.c)-c.l <= 0.1*rng(c): return "gravestone doji"
    return None

def analyze(symbol, market, h4, m5, extra=None):
    """Return a signal dict or None. extra: forex ranking info {priority, bias}."""
    if len(h4) < 60 or len(m5) < 60: return None
    gaps = fvgs(h4)
    if not gaps: return None
    g = gaps[-1]                                   # most recent 4H FVG [T]
    after = h4.iloc[g["i"]+1:]
    if g["dir"] == "long" and (after.c < g["bottom"]).any(): return None   # closed through -> invalid [I]
    if g["dir"] == "short" and (after.c > g["top"]).any(): return None
    formed = h4.ct.iloc[g["i"]]
    m = m5[m5.t >= formed].reset_index(drop=True)
    if m.empty: return None
    touch = (m.l <= g["top"]) if g["dir"] == "long" else (m.h >= g["bottom"])
    if not touch.any(): return None                 # must tap the 4H FVG [T]
    ti = int(touch.idxmax())
    ltf = [x for x in fvgs(m.iloc[ti:].reset_index(drop=True)) if x["dir"] == g["dir"]]
    ltf = [x for x in ltf if x["i"] >= 2]          # c1 at/after tap
    if not ltf: return None
    x = ltf[0]; xi = x["i"] + ti                    # FIRST same-direction 5m FVG after tap [T]
    if len(m) - 1 - xi > C.MAX_CONFIRM_AGE_BARS: return None   # stale
    three = m.iloc[xi-2:xi+1]; leg = m.iloc[ti:xi+1]            # leg = from 4H tap to 15m FVG completion
    swing = float(leg.l.min() if g["dir"] == "long" else leg.h.max())   # creator's plan: stop at the swing low/high
    if g["dir"] == "long":
        entry = x["top"]; sl = three.l.min() if C.FVG_STOP == "fvg" else swing; risk = entry - sl; tp = entry + C.RR*risk
    else:
        entry = x["bottom"]; sl = three.h.max() if C.FVG_STOP == "fvg" else swing; risk = sl - entry; tp = entry - C.RR*risk
    if risk <= 0: return None
    if risk/entry*100 < (C.MIN_STOP_PCT_CRYPTO if market == "crypto" else C.MIN_STOP_PCT_FOREX): return None
    conf_t = m.ct.iloc[xi]
    sc, why = score(g, h4, m.iloc[:xi+1], m5, market, conf_t, extra)
    return dict(symbol=symbol, market=market, direction=g["dir"], entry=float(entry), sl=float(sl), tp=float(tp),
        rr=C.RR, htf_top=float(g["top"]), htf_bottom=float(g["bottom"]), htf_time=str(h4.t.iloc[g["i"]]),
        tap_time=str(m.t.iloc[ti]), confirm_time=str(conf_t), price_now=float(m5.c.iloc[-1]),
        in_session=in_major_session(conf_t.to_pydatetime()), confidence=calibrate(sc, market), setup_score=sc,
        strategy="FVG", experimental=0, swing_sl=swing, fvg3_sl=float(three.l.min() if g["dir"]=="long" else three.h.max()),
        tap_to_confirm_bars=int(xi-ti),
        tags=["FVG"] + (["FVG+TREND"] if C.ENABLE_FVG_TREND and market in C.EXPERIMENTAL_MARKETS and any("EMA50/EMA200 trend aligned" in w for w in why) else []),
        reasons=why + [f"Raw setup score {sc}/95 -> calibrated win probability {calibrate(sc, market)}% (backtest)"])

def score(g, h4, mupto, m5, market, conf_t, extra):
    d = g["dir"]; s = 45; why = [f"Core: 4H FVG tapped + {C.LTF} FVG confirmation (+45)"]
    def add(pts, txt): nonlocal s; s += pts; why.append(f"{txt} ({pts:+d})")
    e50, e200 = ema(h4.c,50).iloc[-1], ema(h4.c,200 if len(h4)>=200 else 100).iloc[-1]
    if (e50 > e200) == (d == "long"): add(7, "4H EMA50/EMA200 trend aligned (Dow primary trend)")
    H, L = pivots(h4)
    if len(H) >= 2 and len(L) >= 2:
        upt = H[-1][1] > H[-2][1] and L[-1][1] > L[-2][1]; dnt = H[-1][1] < H[-2][1] and L[-1][1] < L[-2][1]
        if (upt and d=="long") or (dnt and d=="short"): add(7, "4H market structure HH/HL aligned")
        elif (upt and d=="short") or (dnt and d=="long"): add(-5, "4H structure against trade")
    lv = [p for _,p in H[-12:]+L[-12:]]; mid = (g["top"]+g["bottom"])/2
    if any(abs(p-mid)/mid < 0.004 or g["bottom"] <= p <= g["top"] for p in lv): add(6, "4H FVG at swing S/R level")
    r = rsi(mupto.c).iloc[-1]
    if (d=="long" and r < 70) or (d=="short" and r > 30): add(4, f"{C.LTF} RSI {r:.0f} not stretched")
    else: add(-4, f"{C.LTF} RSI {r:.0f} stretched")
    mh = macd_hist(mupto.c).iloc[-1]
    if (mh > 0) == (d=="long"): add(5, f"{C.LTF} MACD histogram agrees")
    cp = candle_pattern(mupto, d)
    if cp: add(6, f"Candlestick: {cp}")
    w = h4.iloc[-60:]; hi, lo = w.h.max(), w.l.min()
    if hi > lo:
        ret = (hi-mid)/(hi-lo) if d=="long" else (mid-lo)/(hi-lo)
        if 0.5 <= ret <= 0.786: add(6, f"FVG in Fib {ret*100:.0f}% retracement zone")
    if market == "crypto":
        v = mupto.v; 
        if len(v) > 21 and v.iloc[-2] > 1.5*v.iloc[-22:-2].mean(): add(5, "Volume spike on displacement candle")
    if in_major_session(conf_t.to_pydatetime()): add(8, "Entry in London/NY session")
    else: add(-10, "OUTSIDE major session (flagged)")
    if extra:
        if extra.get("priority"): add(5, "Priority pair (strongest per currency, active session)")
        if extra.get("bias") == d: add(5, "Currency-strength bias agrees")
        elif extra.get("bias"): add(-5, "Currency-strength bias disagrees")
    return int(max(5, min(95, s))), why

def calibrate(raw, market):
    """Map raw setup score to the win probability observed in the backtest (target = 3R before 1R stop)."""
    import math
    a, b = C.CALIB.get(market, C.CALIB["crypto"])
    return int(round(100/(1+math.exp(-(a+b*raw)))))


# ---------------- EXPERIMENTAL: Zerodha Varsity Grand Checklist (backtest-report-v2.md, "CHK") ----------------
def analyze_chk(symbol, market, h4, h1, max_age_min=60, sr_atr=0.5):
    """Evaluate the last closed 1H candle. Same rules as app/backtest2.chk_trades:
    1 candlestick pattern, 2 pattern low/high within 0.5 ATR of a confirmed pivot S/R, 3 volume > 20-bar avg (crypto),
    4 Dow: 4H EMA50>EMA200 & close>EMA50 (mirror short), 5 RSI/MACD as score only, 6 TP 3R. Entry = candle close (market)."""
    if h1 is None or len(h1) < 225 or len(h4) < 200: return None
    i = len(h1) - 1; b = h1.iloc[i]; now = h1.ct.iloc[i]
    if (pd.Timestamp.now(tz="UTC") - now) > pd.Timedelta(minutes=max_age_min): return None
    k4 = h4[h4.ct <= now]; e50, e200 = ema(k4.c,50).iloc[-1], ema(k4.c,200).iloc[-1]; c4 = k4.c.iloc[-1]
    up = e50 > e200 and c4 > e50; dn = e50 < e200 and c4 < e50
    if not (up or dn): return None
    d = "long" if up else "short"; why = ["Checklist 4: Dow/primary trend (4H EMA50 vs EMA200) " + ("up" if up else "down")]
    body = abs(b.c-b.o); rng = max(b.h-b.l, 1e-12)
    pat = candle_pattern(h1.iloc[:i+1], d)
    if not pat and body/rng >= 0.9 and ((b.c > b.o) == (d=="long")): pat = "marubozu"
    if not pat: return None
    why.append(f"Checklist 1: candlestick pattern = {pat}")
    if market == "crypto":
        if not (b.v > h1.v.rolling(20).mean().iloc[i]): return None
        why.append("Checklist 3: above-average volume")
    w = h1.iloc[i-2:i+1]; lo, hi = w.l.min(), w.h.max(); a = (h1.h-h1.l).rolling(14).mean().iloc[i]
    H, L, kk = h1.h.values, h1.l.values, 5
    piv = [j for j in range(i-200, i-kk) if (L[j] == L[j-kk:j+kk+1].min() if d=="long" else H[j] == H[j-kk:j+kk+1].max())]
    lv = [L[j] for j in piv] if d=="long" else [H[j] for j in piv]; ref = lo if d=="long" else hi
    dist = min([abs(ref-x)/a for x in lv], default=99)
    if dist > sr_atr: return None
    why.append(f"Checklist 2: stop at {'support' if d=='long' else 'resistance'} ({dist:.2f} ATR away)")
    entry = float(b.c); sl = float(lo if d=="long" else hi); risk = (entry-sl) if d=="long" else (sl-entry)
    if risk <= 0 or risk/entry*100 < (C.MIN_STOP_PCT_CRYPTO if market == "crypto" else C.MIN_STOP_PCT_FOREX): return None
    r_ = rsi(h1.c).iloc[i]; mh = macd_hist(h1.c).iloc[i]
    ind = int((r_ < 70) if d=="long" else (r_ > 30)) + int((mh > 0) == (d=="long"))
    why.append(f"Checklist 5: indicators confirming {ind}/2 (RSI {r_:.0f}, MACD hist {'+' if mh>0 else '-'})")
    why.append(f"Checklist 6: RR 1:{C.RR:g}. EXPERIMENTAL: backtest crypto −0.20R in-sample / +0.16R out-of-sample per trade (net)")
    tp = entry + C.RR*risk if d=="long" else entry - C.RR*risk
    return dict(symbol=symbol, market=market, direction=d, entry=entry, sl=sl, tp=float(tp), rr=C.RR,
        htf_top=float(hi), htf_bottom=float(lo), htf_time=str(h1.t.iloc[i]), tap_time=str(h1.t.iloc[i]), confirm_time=str(now),
        price_now=entry, in_session=in_major_session(now.to_pydatetime()), confidence=C.CHK_CONFIDENCE, setup_score=ind,
        strategy="CHK", tags=["CHK"], experimental=1, status="open", filled_at=str(now), reasons=why)

def watch_info(symbol, market, h4, ltf):
    """For summaries only (does NOT create signals): most recent unfilled 4H FVG aligned with the 4H EMA trend,
    and how far the current price is from it."""
    if len(h4) < 200 or len(ltf) < 5: return None
    gaps = fvgs(h4)
    if not gaps: return None
    g = gaps[-1]; after = h4.iloc[g["i"]+1:]
    if g["dir"] == "long" and (after.c < g["bottom"]).any(): return None
    if g["dir"] == "short" and (after.c > g["top"]).any(): return None
    e50, e200 = ema(h4.c,50).iloc[-1], ema(h4.c,200).iloc[-1]
    if (e50 > e200) != (g["dir"] == "long"): return None
    px = float(ltf.c.iloc[-1]); formed = h4.ct.iloc[g["i"]]; m = ltf[ltf.t >= formed]
    tapped = bool(((m.l <= g["top"]) if g["dir"] == "long" else (m.h >= g["bottom"])).any()) if len(m) else False
    if g["bottom"] <= px <= g["top"]: dist = 0.0
    else: dist = (px - g["top"])/px if g["dir"] == "long" else (g["bottom"] - px)/px
    if dist < 0: return None   # price already beyond the far side (moving away) – not a pending setup
    return dict(symbol=symbol, market=market, direction=g["dir"], top=float(g["top"]), bottom=float(g["bottom"]),
                price=px, dist_pct=round(100*dist, 3), tapped=tapped)


# ---------------- EXPERIMENTAL: creator's PDF plan variant ("FVG-PLAN", backtest3) ----------------
PLAN_MAX_TAP_TO_CONFIRM = 16   # "price should quickly shoot off" -> 15m FVG within 16 bars (4h) of the tap; chosen in-sample
def plan_variant(sig):
    """Same setup as FVG, but stop at the swing low/high of the leg (creator plan) and the quick-reaction rule."""
    if not sig or sig.get("tap_to_confirm_bars", 99) > PLAN_MAX_TAP_TO_CONFIRM: return None
    e, sl = sig["entry"], sig["swing_sl"]; d = sig["direction"]
    risk = (e - sl) if d == "long" else (sl - e)
    if risk <= 0 or risk/e*100 < (C.MIN_STOP_PCT_CRYPTO if sig["market"] == "crypto" else C.MIN_STOP_PCT_FOREX): return None
    p = dict(sig); p.update(strategy="FVG-PLAN", tags=["FVG-PLAN"], experimental=1, sl=float(sl),
        tp=float(e + C.RR*risk if d == "long" else e - C.RR*risk),
        reasons=sig["reasons"] + [f"PLAN: stop at swing {'low' if d=='long' else 'high'} of the leg, 15m FVG {sig['tap_to_confirm_bars']} bars after tap. EXPERIMENTAL (backtest crypto −0.08R IS / +0.00R OOS net)"])
    return p


# ---------------- EXPERIMENTAL: FVG-D1 tag (daily structure bias "B", backtest bt_d1) ----------------
def daily_bias(d1, now=None, k=2):
    """Daily market structure from confirmed pivots (k=2) on completed daily candles:
    last two swing highs AND lows rising -> 'long'; both falling -> 'short'; else ''."""
    if d1 is None or len(d1) < 60: return ""
    now = now or pd.Timestamp.now(tz="UTC"); x = d1[d1.ct <= now].reset_index(drop=True)
    H, L = [], []
    for j in range(k, len(x)-k):
        if x.h.iloc[j] == x.h.iloc[j-k:j+k+1].max(): H.append(x.h.iloc[j])
        if x.l.iloc[j] == x.l.iloc[j-k:j+k+1].min(): L.append(x.l.iloc[j])
    if len(H) < 2 or len(L) < 2: return ""
    if H[-1] > H[-2] and L[-1] > L[-2]: return "long"
    if H[-1] < H[-2] and L[-1] < L[-2]: return "short"
    return ""


# ---------------- EXPERIMENTAL: Market Fluidity zone rejection "MF-REJ" (backtest-report-mf.md, app/backtest_mf.py) ----------------
MF_SESSIONS_UTC = {"Asian": (0, 7), "London": (7, 12), "NY": (12, 17)}   # UTC hours [start, end)
# User's handwritten sheet: pair -> sessions it may signal in (edit here)
MF_PAIRS = {"USDJPY": ["Asian", "NY"], "GBPJPY": ["London", "NY"], "EURJPY": ["Asian", "London"],
            "EURUSD": ["London"], "XAUUSD": ["London", "NY"]}
MF_CONFIDENCE = 55   # backtest win rate of strong-zone MF-REJ at the next-zone TP (65 trades, 2y 1H)
def mf_session(symbol, t):
    h = t.hour
    for s in MF_PAIRS.get(symbol, []):
        a, b = MF_SESSIONS_UTC[s]
        if a <= h < b: return s
    return None
def mf_current_session(t):
    for s, (a, b) in MF_SESSIONS_UTC.items():
        if a <= t.hour < b: return s
    return None
def mf_strong_pair(strength, universe, t):
    """Dynamic 'strong pair' for the session open at t: strongest currency vs weakest (metals excluded), if that pair
    exists in the universe and is not already in MF_PAIRS. Returns (pair, session) or (None, session)."""
    sess = mf_current_session(t); cur = {k: v for k, v in (strength or {}).items() if k not in ("XAU", "XAG")}
    if not sess or len(cur) < 2: return None, sess
    hi = max(cur, key=cur.get); lo = min(cur, key=cur.get)
    for p in (hi+lo, lo+hi):
        if p in universe and p not in MF_PAIRS: return p, sess
    return None, sess
def analyze_mf(symbol, h4, h1, max_age_min=90, today_count=0, strong_session=None, h4_long=None):
    """MF-REJ, strong body-based S/R (bt_mfs/run.py best variant: body Daily+4H bias, zone = body swing levels clustered
    within 0.25 ATR, strong = 2+ touches OR 4H/Daily level, 1H flip-close entry at market, stop = far zone edge + 0.5 ATR,
    TP = next strong opposing zone, only if >= 0.5R)."""
    from . import mf as B
    if (symbol not in MF_PAIRS and not strong_session) or h1 is None or len(h1) < 60 or len(h4) < 30 or today_count >= 2: return None
    x = h1.reset_index(drop=True); i = len(x) - 1; ct = x.ct.iloc[i]
    if (pd.Timestamp.now(tz="UTC") - ct) > pd.Timedelta(minutes=max_age_min): return None
    sess = mf_session(symbol, ct)
    if strong_session and mf_current_session(ct) == strong_session: sess = strong_session
    if not sess: return None
    O, H, L, Cl = x.o.values, x.h.values, x.l.values, x.c.values
    flip_up = Cl[i-1] < O[i-1] and Cl[i] > O[i]; flip_dn = Cl[i-1] > O[i-1] and Cl[i] < O[i]
    if not (flip_up or flip_dn): return None
    d = 1 if flip_up else -1
    hh = h4_long if h4_long is not None and len(h4_long) >= len(h4) else h4
    t = ct.to_datetime64()
    hh = hh[hh.ct.values <= t].reset_index(drop=True)
    d1 = B.rs(hh[["t","o","h","l","c","v","ct"]], "1D")
    bD, b4 = B.struct_bias(B.body(d1), 2), B.struct_bias(B.body(hh), 2)
    bd, bb = B.at(d1.ct.values, bD, t), B.at(hh.ct.values, b4, t)
    if bd == 0 or bd != bb or int(bd) != d: return None
    A = B.atr(x); a = A[i]
    if not a > 0: return None
    lt, lp = B.pivots(x, 3); (t4, p4), (td, pdd) = B.pivots(hh, 2), B.pivots(d1, 2)
    LV = lp[(lt <= t) & (lt > t - np.timedelta64(30, "D"))]
    HV = np.concatenate([p4[(t4 <= t) & (t4 > t - np.timedelta64(120, "D"))], pdd[(td <= t) & (td > t - np.timedelta64(365, "D"))]])
    tol = 0.25*a; allv = np.concatenate([LV, HV])
    if d == 1:
        lo = min(L[i-1], L[i]); cand = allv[(allv >= lo-tol) & (allv < Cl[i])]; cand = -np.sort(-cand)
    else:
        hi = max(H[i-1], H[i]); cand = allv[(allv <= hi+tol) & (allv > Cl[i])]; cand = np.sort(cand)
    if not len(cand): return None
    zb, zt, n = B.cluster(LV, cand[0], tol); hb, htp, hn = B.cluster(HV, cand[0], tol)
    if hn == 0: zlo, zhi = (zb, zt) if n else (cand[0], cand[0])
    else: zlo, zhi = (min(zb, hb), max(zt, htp)) if n else (hb, htp)
    if not (n >= 2 or hn > 0): return None   # strong zone only
    if d == 1:
        if not (lo <= zhi+0.05*a and Cl[i] > zhi and min(O[i-1], Cl[i-1], O[i]) >= zlo-tol): return None
    else:
        if not (hi >= zlo-0.05*a and Cl[i] < zlo and max(O[i-1], Cl[i-1], O[i]) <= zhi+tol): return None
    entry = float(Cl[i])   # market at next open ≈ this close
    sl = float(zlo - 0.5*a if d == 1 else zhi + 0.5*a); risk = (entry - sl)*d
    if risk <= 0: return None
    opp = np.sort(allv[allv > entry]) if d == 1 else -np.sort(-allv[allv < entry]); tz = None
    for p in opp:
        if B.cluster(LV, p, tol)[2] >= 2 or B.cluster(HV, p, tol)[2] >= 1:
            tz = B.cluster(allv, p, tol)[0 if d == 1 else 1]; break
    if tz is None: return None
    rr = float((tz - entry)*d/risk)
    if rr < 0.5: return None
    dr = "long" if d == 1 else "short"
    why = ["MF-REJ [EXPERIMENTAL – paper test]",
           (f"Session: {sess} – strong pair of {sess} (strongest vs weakest currency, 24h strength)" if symbol not in MF_PAIRS
            else f"Session: {sess} ({symbol} allowed in {', '.join(MF_PAIRS[symbol])})"),
           f"Daily and 4H body structure both {'up (HH+HL)' if d == 1 else 'down (LH+LL)'}",
           f"Strong {'support' if d == 1 else 'resistance'} zone {zlo:.5g}–{zhi:.5g} (body levels; {n} 1H touches{', 4H/Daily level' if hn else ''}); 1H candle closed flipped {dr}",
           f"Stop beyond the far zone edge + 0.5 ATR; TP = next strong {'resistance' if d == 1 else 'support'} zone {tz:.5g} ({rr:.2f}R)",
           "Backtest (2y, 1H, strong zones, next-zone TP): ~55% win, ≈ break-even (-0.04R/trade). Stats tracked on the next-zone TP"]
    return dict(symbol=symbol, market="forex", direction=dr, entry=entry, sl=sl, tp=float(tz), rr=round(rr, 2),
        htf_top=float(zhi), htf_bottom=float(zlo), htf_time=str(x.t.iloc[i]), tap_time=str(x.t.iloc[i]), confirm_time=str(ct),
        price_now=entry, in_session=True, confidence=MF_CONFIDENCE, setup_score=None, session=sess,
        strategy="MF-REJ", tags=["MF-REJ"], experimental=1, status="open", filled_at=str(ct), reasons=why)
