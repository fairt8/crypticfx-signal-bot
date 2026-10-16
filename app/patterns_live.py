"""PAT-* and BRK [EXPERIMENTAL – paper]: 4H chart-pattern retest/breakout signals.
Rules are the ones backtested in backtest-report-retest-cup.md (bt_retest_cup.py / bt_cup2.py) and backtest-report-brk.md.
The same scan_series() produces both the backtest trades and the live signals (live = entries on the last closed 4H bar).
Pattern detector copied verbatim from app/backtest_patterns.py (pivots k=3, equal tops within 0.5 ATR)."""
import numpy as np, pandas as pd
TOL = 0.5; SPAN = 150; WATCH = 24; NRT = 10
def line(p1, p2, x): return p1[1] + (p2[1]-p1[1])*(x-p1[0])/max(p2[0]-p1[0], 1)

def detect(Z, i, a, h1):
    """Return list of (name, dir, level_fn(x)->price, stop, height, key). Z = pivots confirmed by bar i."""
    out = []; n = len(Z)
    if n < 3: return out
    near = lambda x, y, t=TOL: abs(x-y) <= t*a
    p = Z[-5:] if n >= 5 else Z[-n:]
    t3 = Z[-3:]; key = Z[-1][0]
    if t3[0][0] < i - SPAN: return out
    a3, b3, c3 = t3
    # double top / bottom (and not triple)
    if a3[2]=="H" and near(a3[1], c3[1]) and min(a3[1],c3[1]) - b3[1] >= a and c3[0]-a3[0] >= 6:
        top = max(a3[1], c3[1]); out.append(("DOUBLE_TOP","short", lambda x, v=b3[1]: v, top+0.1*a, top-b3[1], key))
    if a3[2]=="L" and near(a3[1], c3[1]) and b3[1] - max(a3[1],c3[1]) >= a and c3[0]-a3[0] >= 6:
        bot = min(a3[1], c3[1]); out.append(("DOUBLE_BOTTOM","long", lambda x, v=b3[1]: v, bot-0.1*a, b3[1]-bot, key))
    if n >= 5 and Z[-5][0] >= i - SPAN:
        A, B, Cc, D, E = Z[-5:]
        if A[2]=="H":
            hs = (A[1], Cc[1], E[1])
            if max(hs)-min(hs) <= 2*TOL*a and min(hs)-max(B[1], D[1]) >= a:   # triple top
                out.append(("TRIPLE_TOP","short", lambda x, v=min(B[1],D[1]): v, max(hs)+0.1*a, max(hs)-min(B[1],D[1]), key))
            elif Cc[1] > max(A[1], E[1]) + TOL*a and near(A[1], E[1], 1.0) and min(A[1],E[1]) > max(B[1],D[1]):  # H&S
                out.append(("HEAD_SHOULDERS","short", lambda x, b=B, d=D: line(b, d, x), E[1]+0.1*a, Cc[1]-line(B, D, Cc[0]), key))
        else:
            ls = (A[1], Cc[1], E[1])
            if max(ls)-min(ls) <= 2*TOL*a and min(B[1],D[1]) - max(ls) >= a:
                out.append(("TRIPLE_BOTTOM","long", lambda x, v=max(B[1],D[1]): v, min(ls)-0.1*a, max(B[1],D[1])-min(ls), key))
            elif Cc[1] < min(A[1], E[1]) - TOL*a and near(A[1], E[1], 1.0) and max(A[1],E[1]) < min(B[1],D[1]):
                out.append(("INV_HEAD_SHOULDERS","long", lambda x, b=B, d=D: line(b, d, x), E[1]-0.1*a, line(B, D, Cc[0])-Cc[1], key))
    if n >= 4 and Z[-4][0] >= i - SPAN:
        A, B, Cc, D = Z[-4:]
        # cup & handle: H rim, L cup bottom, H rim, L handle (bullish); mirrored inverse
        if A[2]=="H":
            dep = min(A[1], Cc[1]) - B[1]; mid = (A[0]+Cc[0])/2
            if near(A[1], Cc[1], 1.0) and dep >= 2*a and Cc[0]-A[0] >= 15 and abs(B[0]-mid) <= (Cc[0]-A[0])/4 \
               and 0 < Cc[1]-D[1] <= 0.5*dep and D[0]-Cc[0] <= (Cc[0]-A[0])/2:
                out.append(("CUP_HANDLE","long", lambda x, v=max(A[1],Cc[1]): v, D[1]-0.1*a, dep, key))
            # ascending triangle: flat highs A,C ; rising lows (need earlier low) -> use B<D
            if near(A[1], Cc[1]) and D[1] > B[1] + TOL*a and Cc[1]-B[1] >= 1.5*a:
                out.append(("ASC_TRIANGLE","long", lambda x, v=max(A[1],Cc[1]): v, D[1]-0.1*a, max(A[1],Cc[1])-B[1], key))
            # rectangle: flat highs and flat lows
            if near(A[1], Cc[1]) and near(B[1], D[1]) and min(A[1],Cc[1])-max(B[1],D[1]) >= 1.5*a:
                hi, lo = max(A[1],Cc[1]), min(B[1],D[1])
                out.append(("RECTANGLE","long", lambda x, v=hi: v, lo-0.1*a, hi-lo, key))
                out.append(("RECTANGLE","short", lambda x, v=lo: v, hi+0.1*a, hi-lo, key))
            # descending triangle variant ending on L: flat lows B,D, falling highs A>C
            if near(B[1], D[1]) and A[1] > Cc[1] + TOL*a and Cc[1]-D[1] >= a:
                out.append(("DESC_TRIANGLE","short", lambda x, v=min(B[1],D[1]): v, Cc[1]+0.1*a, A[1]-min(B[1],D[1]), key))
            # wedges (A,C highs; B,D lows)
            dh, dl = Cc[1]-A[1], D[1]-B[1]
            if dh > 0 and dl > dh and dl > TOL*a:   # rising wedge -> bearish break of lower line
                out.append(("RISING_WEDGE","short", lambda x, b=B, d=D: line(b, d, x), Cc[1]+0.1*a, A[1]-B[1], key))
            if dl < 0 and dh < dl and -dh > TOL*a:  # falling wedge -> bullish break of upper line
                out.append(("FALLING_WEDGE","long", lambda x, p=A, q=Cc: line(p, q, x), D[1]-0.1*a, A[1]-B[1], key))
        else:   # A is L
            dep = B[1] - max(A[1], Cc[1]); mid = (A[0]+Cc[0])/2
            if near(A[1], Cc[1], 1.0) and dep >= 2*a and Cc[0]-A[0] >= 15 and abs(B[0]-mid) <= (Cc[0]-A[0])/4 \
               and 0 < D[1]-Cc[1] <= 0.5*dep and D[0]-Cc[0] <= (Cc[0]-A[0])/2:
                out.append(("INV_CUP_HANDLE","short", lambda x, v=min(A[1],Cc[1]): v, D[1]+0.1*a, dep, key))
            if near(A[1], Cc[1]) and D[1] < B[1] - TOL*a and B[1]-Cc[1] >= 1.5*a:
                out.append(("DESC_TRIANGLE","short", lambda x, v=min(A[1],Cc[1]): v, D[1]+0.1*a, B[1]-min(A[1],Cc[1]), key))
            if near(B[1], D[1]) and A[1] < Cc[1] - TOL*a and D[1]-Cc[1] >= a:
                out.append(("ASC_TRIANGLE","long", lambda x, v=max(B[1],D[1]): v, Cc[1]-0.1*a, max(B[1],D[1])-A[1], key))
            if near(A[1], Cc[1]) and near(B[1], D[1]) and min(B[1],D[1])-max(A[1],Cc[1]) >= 1.5*a:
                hi, lo = max(B[1],D[1]), min(A[1],Cc[1])
                out.append(("RECTANGLE","long", lambda x, v=hi: v, lo-0.1*a, hi-lo, key))
                out.append(("RECTANGLE","short", lambda x, v=lo: v, hi+0.1*a, hi-lo, key))
            dl, dh = Cc[1]-A[1], D[1]-B[1]
            if dl > 0 and dl > dh > 0 and dl > TOL*a:
                out.append(("RISING_WEDGE","short", lambda x, p=A, q=Cc: line(p, q, x), D[1]+0.1*a, B[1]-A[1], key))
            if dh < 0 and dl < 0 and dh < dl and -dh > TOL*a:
                out.append(("FALLING_WEDGE","long", lambda x, b=B, d=D: line(b, d, x), Cc[1]-0.1*a, B[1]-A[1], key))
    return out

def flags(h1, i, a):
    H, L, Cl = h1.h.values, h1.l.values, h1.c.values
    for f in range(5, 16):
        s = i - f; cs = slice(s+1, i+1)
        if s - 8 < 0: break
        hi, lo = H[cs].max(), L[cs].min()
        S, P = L[s-8:s+1].min(), H[s]
        if P - S >= 3*a and hi <= P + 0.2*a and lo >= P - 0.5*(P-S) and Cl[i] < Cl[s+1]:
            return [("BULL_FLAG","long", lambda x, v=hi: v, lo-0.1*a, P-S, ("BF", s))]
        S2, P2 = H[s-8:s+1].max(), L[s]
        if S2 - P2 >= 3*a and lo >= P2 - 0.2*a and hi <= P2 + 0.5*(S2-P2) and Cl[i] > Cl[s+1]:
            return [("BEAR_FLAG","short", lambda x, v=lo: v, hi+0.1*a, S2-P2, ("SF", s))]
    return []

# ---------------------------------------------------------------- helpers
FAM = {"DOUBLE_TOP":"DOUBLE","DOUBLE_BOTTOM":"DOUBLE","TRIPLE_TOP":"TRIPLE","TRIPLE_BOTTOM":"TRIPLE","ASC_TRIANGLE":"TRIANGLE",
       "DESC_TRIANGLE":"TRIANGLE","RISING_WEDGE":"WEDGE","FALLING_WEDGE":"WEDGE","BULL_FLAG":"FLAG","BEAR_FLAG":"FLAG","RECTANGLE":"HORIZ_SR",
       "CUP_HANDLE":"CUP","INV_CUP_HANDLE":"CUP"}
NICE = {k: k.replace("_", " ").title().replace("Inv ", "Inverse ") for k in FAM}
def atr(d, n=14):
    pc = d.c.shift(); tr = np.maximum(d.h-d.l, np.maximum(abs(d.h-pc), abs(d.l-pc)))
    return tr.rolling(n).mean().values

def incr_pivots(H, L, K):
    Z = []; ev = {}
    for i in range(2*K, len(H)):
        j = i-K; ch = False
        for typ, v, ok in (("H", H[j], H[j]==H[j-K:j+K+1].max()), ("L", L[j], L[j]==L[j-K:j+K+1].min())):
            if not ok: continue
            p = (j, v, typ)
            if Z and Z[-1][2]==typ:
                if (typ=="H" and v>=Z[-1][1]) or (typ=="L" and v<=Z[-1][1]): Z[-1]=p; ch=True
            else: Z.append(p); ch=True
        if ch: ev[i] = list(Z)
    return ev

def cup_setups(d, a, market):
    """Cup & handle (bt_cup2.py): K=5 rims, depth 12-50% crypto (1.5-10% forex), rounded U, handle < 1/3 depth."""
    H,L,Cl = d.h.values,d.l.values,d.c.values; K=5; out=[]; seen=set()
    lo_d, hi_d = (.12,.50) if market=="crypto" else (.015,.10)
    hp = [j for j in range(K,len(H)-K) if H[j]==H[j-K:j+K+1].max()]; lp = [j for j in range(K,len(H)-K) if L[j]==L[j-K:j+K+1].min()]
    for sg, rims, P in ((1, hp, H), (-1, lp, L)):
        for ci in rims:
            for ai in rims:
                w = ci-ai
                if w < 20 or w > 300: continue
                rimA, rimC = P[ai], P[ci]
                if sg==1:
                    seg = L[ai:ci+1]; bot = seg.min(); bi = ai+int(seg.argmin()); rim = max(rimA,rimC); dep = min(rimA,rimC)-bot
                    if H[ai+1:ci].max(initial=-np.inf) > min(rimA,rimC): continue
                else:
                    seg = H[ai:ci+1]; bot = seg.max(); bi = ai+int(seg.argmax()); rim = min(rimA,rimC); dep = bot-max(rimA,rimC)
                    if L[ai+1:ci].min(initial=np.inf) < max(rimA,rimC): continue
                if dep <= 0 or not (lo_d <= dep/rim <= hi_d) or abs(rimA-rimC) > 0.1*dep or abs(bi-(ai+ci)/2) > w/4: continue
                if (np.mean(seg <= bot+dep/3) if sg==1 else np.mean(seg >= bot-dep/3)) < .2: continue
                if ci in seen: break
                for i in range(ci+K, min(ci+w//2, len(H)-1)):
                    hx = L[ci+1:i+1].min() if sg==1 else H[ci+1:i+1].max()
                    if sg*(Cl[i]-rim) > 0 or abs(rim-hx) > dep/3: break
                    if abs(rim-hx) > 0.3*a[i] and i-ci >= 3 and not np.isnan(a[i]):
                        out.append(("CUP_HANDLE" if sg==1 else "INV_CUP_HANDLE", "long" if sg==1 else "short", lambda x, v=rim: v, hx-sg*0.1*a[i], dep, ("C",ai,ci), i)); seen.add(ci); break
                if ci in seen: break
    return out

def pattern_setups(d, a, names=None, cups=False, market="crypto"):
    H, L = d.h.values, d.l.values; ev = incr_pivots(H, L, 3); seen = set(); out = []
    for i in range(30, len(d)):
        if np.isnan(a[i]): continue
        cand = []
        if i in ev: cand += [c+(i,) for c in detect(ev[i], i, a[i], None)]
        cand += [c+(i,) for c in flags(d, i, a[i])]
        for c in cand:
            if names and c[0] not in names: continue
            kk = (c[0], c[1], c[5])
            if kk in seen: continue
            seen.add(kk); out.append(c)
    if cups: out += cup_setups(d, a, market)
    return out

def entries(d, a, setups, mode, stop_mode, brk_filter=None):
    """Same entry logic as bt_retest_cup.sim. mode immediate|retest; stop_mode pattern|swing|lvl. Returns list of dicts (k = entry bar)."""
    O,H,L,Cl = d.o.values,d.h.values,d.l.values,d.c.values; out = []
    for (name, dirn, lvl, stop, height, key, i) in setups:
        sg = 1 if dirn=="long" else -1; b = None
        for j in range(i+1, min(i+1+WATCH, len(Cl))):
            if (sg==1 and L[j]<=stop) or (sg==-1 and H[j]>=stop): break
            if sg*(Cl[j]-lvl(j)) > 0: b = j; break
        if b is None: continue
        if brk_filter is not None and not brk_filter(b, sg): continue
        if mode == "immediate":
            s = stop if stop_mode == "pattern" else lvl(b)-sg*0.5*a[b]
            out.append(dict(pat=name, dir=dirn, k=b, entry=Cl[b], sl=s, level=lvl(b), height=height, brk=b)); continue
        touch = None
        for j in range(b+1, min(b+1+NRT, len(Cl))):
            lv = lvl(j); aj = a[j]
            if (sg==1 and Cl[j] < lv-0.5*aj) or (sg==-1 and Cl[j] > lv+0.5*aj): break
            if touch is None and ((sg==1 and L[j] <= lv) or (sg==-1 and H[j] >= lv)): touch = j
            if touch is not None and sg*(Cl[j]-O[j]) > 0 and sg*(Cl[j]-lv) > 0:
                sw = L[touch:j+1].min() if sg==1 else H[touch:j+1].max()
                s = sw-sg*0.1*aj if stop_mode == "swing" else lv-sg*0.5*aj
                out.append(dict(pat=name, dir=dirn, k=j, entry=Cl[j], sl=s, level=lv, height=height, brk=b)); break
    return [e for e in out if (e["entry"]-e["sl"])*(1 if e["dir"]=="long" else -1) > 0]

# ---------------------------------------------------------------- strategies
WEDGES = {"RISING_WEDGE","FALLING_WEDGE"}; TRIPLES = {"TRIPLE_TOP","TRIPLE_BOTTOM"}
BRK_NAMES = {"DOUBLE_TOP","DOUBLE_BOTTOM","TRIPLE_TOP","TRIPLE_BOTTOM","BULL_FLAG","BEAR_FLAG","ASC_TRIANGLE","DESC_TRIANGLE","RISING_WEDGE","FALLING_WEDGE","RECTANGLE"}
# strategy -> (market, pattern names, cups, entry mode, stop mode, tracked R, backtest win%, backtest note)
PAT = {
 "PAT-WEDGE":  ("crypto", WEDGES, False, "retest", "lvl",   3.0, 27, "2y 4H backtest (one signal per coin/bar): 1,598 trades, 27% win at 1:3, IS -0.02R / OOS +0.11R per trade net"),
 "PAT-TRIPLE": ("forex",  TRIPLES, False, "retest", "lvl",  1.5, 54, "2y 4H backtest: 125 trades, 54% win at 1:1.5, IS +0.10R / OOS +0.37R per trade net (small sample)"),
 "PAT-CUP":    ("crypto", set(), True,  "retest", "swing", 3.0, 28, "2y 4H backtest: 69 trades, 28% win at 1:3, IS +0.30R / OOS -0.16R per trade net (tiny sample)"),
}
def pat_series(name, d, market):
    mk, names, cups, mode, stop_mode, R, conf, note = PAT[name]
    d = d.reset_index(drop=True); a = atr(d)
    st = pattern_setups(d, a, names or {"__none__"}, cups=cups, market=market)
    return d, a, entries(d, a, st, mode, stop_mode)


def brk_series(d, market, look=250):
    """BRK: fresh 4H close beyond a strong horizontal body S/R level (2+ body-pivot touches within 0.25 ATR, mf.py zone logic)
    or beyond a pattern neckline/trendline. Filters: volume > 20-bar avg (skipped when the feed has no volume, e.g. Yahoo FX),
    close in the outer 30% of the candle. Entry: crypto immediate (breakout close), forex retest (touch + confirming close).
    Stop = level -/+ 0.5 ATR."""
    d = d.reset_index(drop=True); a = atr(d); O,H,L,Cl,V = d.o.values,d.h.values,d.l.values,d.c.values,d.v.values
    vavg = pd.Series(V).rolling(20).mean().shift(1).values; novol = np.nansum(V) == 0
    def filt(b, sg):
        rng = H[b]-L[b]
        if rng <= 0: return False
        outer = (Cl[b]-L[b])/rng >= 0.7 if sg == 1 else (H[b]-Cl[b])/rng >= 0.7
        return outer and (novol or (vavg[b] > 0 and V[b] > vavg[b]))
    mode = "immediate" if market == "crypto" else "retest"
    # horizontal levels as setups: level detected at bar i-1 (known before the breakout bar i)
    bh = np.maximum(O, Cl); bl = np.minimum(O, Cl); K = 2; piv = []
    for j in range(K, len(d)-K):
        if bh[j] == bh[j-K:j+K+1].max(): piv.append((j+K, bh[j]))
        if bl[j] == bl[j-K:j+K+1].min(): piv.append((j+K, bl[j]))
    piv.sort(); pt = np.array([p[0] for p in piv]); pp = np.array([p[1] for p in piv]); setups = []
    for i in range(30, len(d)):
        if np.isnan(a[i]) or not len(pt): continue
        m = (pt <= i-1) & (pt > i-1-look); lv = pp[m]
        if len(lv) < 2: continue
        tol = 0.25*a[i]
        for sg in (1, -1):
            cr = lv[(lv > Cl[i-1]) & (lv < Cl[i])] if sg == 1 else lv[(lv < Cl[i-1]) & (lv > Cl[i])]
            if not len(cr): continue
            c0 = cr.max() if sg == 1 else cr.min()   # outermost level crossed
            cl = lv[np.abs(lv-c0) <= tol]
            if len(cl) < 2: continue
            z = cl.max() if sg == 1 else cl.min()
            if sg*(Cl[i]-z) <= 0: continue
            setups.append(("HORIZ_LEVEL", "long" if sg == 1 else "short", lambda x, v=z: v, z-sg*1e9, 0.0, ("HL", i, sg), i-1))
    setups += pattern_setups(d, a, BRK_NAMES)
    E = entries(d, a, setups, mode, "lvl", brk_filter=filt)
    best = {}
    for e in E: best.setdefault((e["k"], e["dir"]), e)   # one BRK per bar/direction
    return d, a, sorted(best.values(), key=lambda e: e["k"])

# ---------------------------------------------------------------- live
BRK_CONF = {"crypto": 27, "forex": 25}   # backtest win% at the tracked 1:3 target (backtest-report-brk.md)
BRK_NOTE = {"crypto": "2y 4H backtest: 17,264 trades, 27% win at 1:3, IS +0.05R / OOS -0.02R per trade net (≈ break-even)",
            "forex": "2y 4H backtest: 2,893 trades, 25% win at 1:3, IS -0.06R / OOS -0.09R per trade net (losing)"}
STALE = pd.Timedelta("4h30min")   # only the last closed 4H bar is evaluated
def _sig(strategy, symbol, market, d, a, e, R, conf, note, why):
    k = e["k"]; sd = 1 if e["dir"] == "long" else -1; entry = float(e["entry"]); sl = float(e["sl"]); risk = abs(entry-sl)
    ct = d.ct.iloc[k] if "ct" in d else d.t.iloc[k] + pd.Timedelta("4h")
    return dict(symbol=symbol, market=market, direction=e["dir"], entry=entry, sl=sl, tp=entry+sd*R*risk, rr=R,
        htf_top=float(max(e["level"], entry)), htf_bottom=float(min(e["level"], entry)), htf_time=str(d.t.iloc[e["brk"]]),
        tap_time=str(d.t.iloc[k]), confirm_time=str(ct), price_now=entry, in_session=True, confidence=conf, setup_score=None,
        strategy=strategy, tags=[strategy], experimental=1, status="open", filled_at=str(ct),
        reasons=[f"{strategy} [EXPERIMENTAL – paper]"] + why + [f"TP1 1:1.5 = {entry+sd*1.5*risk:.6g} · TP2 1:3 = {entry+sd*3*risk:.6g}; tracked target: 1:{R:g}", note])
def _fresh(d, k, now):
    ct = d.ct.iloc[k] if "ct" in d else d.t.iloc[k] + pd.Timedelta("4h")
    return k == len(d)-1 and ct <= now and now - ct <= STALE
def live_pat(symbol, market, h4, now=None, names=None):
    now = now or pd.Timestamp.now(tz="UTC"); out = []
    if h4 is None or len(h4) < 60: return out
    for nm, v in PAT.items():
        if v[0] != market or (names and nm not in names): continue
        d, a, E = pat_series(nm, h4, market)
        for e in E:
            if not _fresh(d, e["k"], now): continue
            if market == "crypto" and abs(e["entry"]-e["sl"])/e["entry"] < 0.003: continue
            mode = "retest of the broken level + confirming 4H close"
            stop = "level ∓ 0.5 ATR" if v[4] == "lvl" else "beyond the retest swing + 0.1 ATR"
            why = [f"4H {NICE.get(e['pat'], e['pat'])}: broke {'above' if e['dir']=='long' else 'below'} {e['level']:.6g}, entry on {mode}", f"Stop: {stop}"]
            out.append(_sig(nm, symbol, market, d, a, e, v[5], v[6], v[7], why))
    return out
def live_brk(symbol, market, h4, now=None):
    now = now or pd.Timestamp.now(tz="UTC")
    if h4 is None or len(h4) < 60: return []
    d, a, E = brk_series(h4, market); out = []
    for e in E:
        if not _fresh(d, e["k"], now): continue
        if market == "crypto" and abs(e["entry"]-e["sl"])/e["entry"] < 0.003: continue
        what = "strong horizontal S/R (2+ body touches)" if e["pat"] == "HORIZ_LEVEL" else f"{NICE.get(e['pat'], e['pat'])} neckline/trendline"
        why = [f"4H close {'above' if e['dir']=='long' else 'below'} {what} at {e['level']:.6g}, volume above 20-bar avg, close in outer 30% of candle",
               "Entry: " + ("immediate (breakout close)" if market == "crypto" else "retest of the level + confirming 4H close"), "Stop: level ∓ 0.5 ATR"]
        out.append(_sig("BRK", symbol, market, d, a, e, 3.0, BRK_CONF[market], BRK_NOTE[market], why))
    return out[-1:]
