"""Research only: breakout-then-retest vs immediate breakout, and cup & handle. Writes bt_rc/<tf>_<sym>.pkl"""
import pickle, glob, sys, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
from app.backtest_patterns import detect, flags
T0 = pd.Timestamp("2024-10-01", tz="UTC"); T1 = pd.Timestamp("2026-10-01", tz="UTC")
NAMES = {"DOUBLE_TOP","DOUBLE_BOTTOM","TRIPLE_TOP","TRIPLE_BOTTOM","BULL_FLAG","BEAR_FLAG","ASC_TRIANGLE","DESC_TRIANGLE","RISING_WEDGE","FALLING_WEDGE","RECTANGLE"}
FX = {"EURUSD":.0002,"GBPUSD":.0002,"USDJPY":.0002,"USDCHF":.0002,"AUDUSD":.0002,"USDCAD":.0002,"NZDUSD":.0002,"EURJPY":.0003,"GBPJPY":.0003,"XAUUSD":.0005}
WATCH = 24; NRT = 10; HOR = 400

def rs(df, rule):
    h = df.set_index("t").resample(rule, origin="epoch").agg({"o":"first","h":"max","l":"min","c":"last","v":"sum"}).dropna()
    h["t"] = h.index; return h.reset_index(drop=True)

def atr(d, n=14):
    pc = d.c.shift(); tr = np.maximum(d.h-d.l, np.maximum(abs(d.h-pc), abs(d.l-pc)))
    return tr.rolling(n).mean().values

def incr_pivots(H, L, K):
    """yield (i, Z snapshot changed) -- pivot at j confirmed at bar j+K; same alternation rule as backtest_patterns."""
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

def cups(Z, i, a, d, O, H, L, Cl, market):
    out = []
    if len(Z) < 4: return out
    A,B,Cc,D = Z[-4:]; w = Cc[0]-A[0]
    if w < 20 or w > 300 or D[0]-Cc[0] < 2 or D[0]-Cc[0] > w/2 or not (abs(A[1]-Cc[1]) <= 0.05*abs(A[1]-B[1])+0.5*a): return out
    lo_d, hi_d = (.12,.50) if market=="crypto" else (.015,.10)
    seg = slice(A[0], Cc[0]+1)
    if A[2]=="H":
        rim = max(A[1],Cc[1]); dep = min(A[1],Cc[1])-B[1]; pct = dep/rim
        if not (lo_d<=pct<=hi_d) or abs(B[0]-(A[0]+Cc[0])/2) > w/4: return out
        if np.mean(L[seg] <= B[1]+dep/3) < .2: return out          # rounded U, not V
        if rim-D[1] > dep/3 or rim-D[1] <= 0: return out           # handle < 1/3 depth, upper part
        out.append(("CUP_HANDLE","long", lambda x, v=rim: v, D[1]-0.1*a, dep, ("CUP",A[0]), D[0]))
    else:
        rim = min(A[1],Cc[1]); dep = B[1]-max(A[1],Cc[1]); pct = dep/rim
        if not (lo_d<=pct<=hi_d) or abs(B[0]-(A[0]+Cc[0])/2) > w/4: return out
        if np.mean(H[seg] >= B[1]-dep/3) < .2: return out
        if D[1]-rim > dep/3 or D[1]-rim <= 0: return out
        out.append(("INV_CUP_HANDLE","short", lambda x, v=rim: v, D[1]+0.1*a, dep, ("ICUP",A[0]), D[0]))
    return out

def outcome(H, L, k, e, s, dirn, R):
    risk = abs(e-s); tp = e+R*risk if dirn=="long" else e-R*risk
    for j in range(k+1, min(k+1+HOR, len(H))):
        if dirn=="long":
            if L[j] <= s: return -1.0
            if H[j] >= tp: return R
        else:
            if H[j] >= s: return -1.0
            if L[j] <= tp: return R
    return None

def sim(d, a, setups, sym, market, tf, cost):
    O,H,L,Cl = d.o.values,d.h.values,d.l.values,d.c.values; T = d.t.values; rows = []
    for (name, dirn, lvl, stop, height, key, i) in setups:
        sg = 1 if dirn=="long" else -1; b = None
        for j in range(i+1, min(i+1+WATCH, len(Cl))):
            if sg*(stop-L[j] if sg==1 else H[j]-stop) >= 0 and ((sg==1 and L[j]<=stop) or (sg==-1 and H[j]>=stop)): break
            if sg*(Cl[j]-lvl(j)) > 0: b = j; break
        if b is None: continue
        ents = [("immediate", b, Cl[b], stop)]
        # retest: touch broken level within NRT bars, then confirming close in breakout direction
        touch = None; ext = H[b] if sg==1 else L[b]
        for j in range(b+1, min(b+1+NRT, len(Cl))):
            lv = lvl(j); aj = a[j]
            if (sg==1 and Cl[j] < lv-0.5*aj) or (sg==-1 and Cl[j] > lv+0.5*aj): break   # failed breakout
            if touch is None and ((sg==1 and L[j] <= lv) or (sg==-1 and H[j] >= lv)): touch = j
            if touch is not None and sg*(Cl[j]-O[j]) > 0 and sg*(Cl[j]-lv) > 0:
                sw = L[touch:j+1].min() if sg==1 else H[touch:j+1].max()
                ents.append(("retest_swing", j, Cl[j], sw-sg*0.1*aj))
                ents.append(("retest_lvl", j, Cl[j], lv-sg*0.5*aj)); break
        for et, k, e, s in ents:
            if sg*(e-s) <= 0: continue
            rp = abs(e-s)/e
            if market=="crypto" and rp < .003: continue
            cR = cost/rp; r = dict(t=pd.Timestamp(T[k]).tz_localize("UTC") if pd.Timestamp(T[k]).tzinfo is None else pd.Timestamp(T[k]), sym=sym, market=market, tf=tf, pat=name, dir=dirn, entry=et, risk=rp)
            for R, nm in ((1.5,"r15"),(3.0,"r3"),(max(height/abs(e-s),0.5),"rmm")):
                o = outcome(H, L, k, e, s, dirn, R); r[nm] = None if o is None else o-cR
            rows.append(r)
    return rows

def run(args):
    sym, market, tf, d, cost = args
    d = d.reset_index(drop=True); a = atr(d); H,L,Cl,O = d.h.values,d.l.values,d.c.values,d.o.values
    seen = set(); setups = []
    ev3 = incr_pivots(H, L, 3); ev5 = incr_pivots(H, L, 5)
    for i in range(30, len(d)):
        if d.t.iloc[i] < T0 or d.t.iloc[i] >= T1 or np.isnan(a[i]): continue
        cand = []
        if i in ev3: cand += [c+(i,) for c in detect(ev3[i], i, a[i], None) if c[0] in NAMES]
        cand += [c+(i,) for c in flags(d, i, a[i])]
        if i in ev5: cand += [c[:6]+(i,) for c in cups(ev5[i], i, a[i], d, O, H, L, Cl, market)]
        for c in cand:
            kk = (c[0], c[1], c[5])
            if kk in seen: continue
            seen.add(kk); setups.append(c)
    rows = sim(d, a, setups, sym, market, tf, cost)
    pickle.dump(rows, open(f"bt_rc/{tf}_{sym}.pkl","wb")); return sym, tf, len(rows)

if __name__ == "__main__":
    jobs = []
    for f in sorted(glob.glob("bt_regime/data/*.pkl")):
        sym = f.split("/")[-1][:-4]; h4, m = pickle.load(open(f,"rb"))
        jobs.append((sym,"crypto","1H",rs(m,"1h"),.001)); jobs.append((sym,"crypto","4H",h4[["t","o","h","l","c","v"]],.001))
    fx = pickle.load(open("bt_regime/fx_1h.pkl","rb"))
    for s,c in FX.items():
        h = fx[s][1][["t","o","h","l","c","v"]]; jobs.append((s,"forex","1H",h,c)); jobs.append((s,"forex","4H",rs(h,"4h"),c))
    with ProcessPoolExecutor(8) as ex:
        for r in ex.map(run, jobs): print(*r, flush=True)
    print("DONE")
