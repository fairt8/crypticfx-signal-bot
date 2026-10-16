"""Research only: looser cup & handle scan (any left rim among K=5 pivots). Writes bt_rc/cup_<tf>_<sym>.pkl"""
import pickle, glob, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
import bt_retest_cup as b
def gen(d, a, market):
    H,L,Cl = d.h.values,d.l.values,d.c.values; K=5; out=[]; seen=set()
    piv = [(j,"H") for j in range(K,len(H)-K) if H[j]==H[j-K:j+K+1].max()] + [(j,"L") for j in range(K,len(H)-K) if L[j]==L[j-K:j+K+1].min()]
    lo_d, hi_d = (.12,.50) if market=="crypto" else (.015,.10)
    hp = [j for j,t in piv if t=="H"]; lp = [j for j,t in piv if t=="L"]
    for sg, rims, P in ((1, hp, H), (-1, lp, L)):
        for ci in rims:
            for ai in rims:
                w = ci-ai
                if w < 20 or w > 300: continue
                rimA, rimC = P[ai], P[ci]
                if sg==1:
                    seg = L[ai:ci+1]; bot = seg.min(); bi = ai+int(seg.argmin()); rim = max(rimA,rimC); dep = min(rimA,rimC)-bot
                    if H[ai+1:ci].max(initial=-np.inf) > min(rimA,rimC): continue   # no higher high inside cup
                else:
                    seg = H[ai:ci+1]; bot = seg.max(); bi = ai+int(seg.argmax()); rim = min(rimA,rimC); dep = bot-max(rimA,rimC)
                    if L[ai+1:ci].min(initial=np.inf) < max(rimA,rimC): continue
                if dep <= 0 or not (lo_d <= dep/rim <= hi_d) or abs(rimA-rimC) > 0.1*dep or abs(bi-(ai+ci)/2) > w/4: continue
                if (np.mean(seg <= bot+dep/3) if sg==1 else np.mean(seg >= bot-dep/3)) < .2: continue
                if ci in seen: break
                # handle: from ci, bars ci+3..ci+w/2 ; handle extreme stays within dep/3 of rim, no close beyond rim yet
                for i in range(ci+K, min(ci+w//2, len(H)-1)):
                    hx = L[ci+1:i+1].min() if sg==1 else H[ci+1:i+1].max()
                    if sg*(Cl[i]-rim) > 0 or abs(rim-hx) > dep/3: break
                    if abs(rim-hx) > 0.3*a[i] and i-ci >= 3:
                        out.append(("CUP_HANDLE" if sg==1 else "INV_CUP_HANDLE", "long" if sg==1 else "short", lambda x, v=rim: v, hx-sg*0.1*a[i], dep, ("C",ai,ci), i)); seen.add(ci); break
                if ci in seen: break
    return out
def run(args):
    sym, market, tf, d, cost = args; d = d.reset_index(drop=True); a = b.atr(d)
    st = [s for s in gen(d, a, market) if b.T0 <= d.t.iloc[s[6]] < b.T1 and not np.isnan(a[s[6]])]
    rows = b.sim(d, a, st, sym, market, tf, cost); pickle.dump(rows, open(f"bt_rc/cup_{tf}_{sym}.pkl","wb")); return sym, tf, len(rows)
if __name__ == "__main__":
    jobs=[]
    for f in sorted(glob.glob("bt_regime/data/*.pkl")):
        sym=f.split("/")[-1][:-4]; h4,m=pickle.load(open(f,"rb"))
        jobs.append((sym,"crypto","1H",b.rs(m,"1h"),.001)); jobs.append((sym,"crypto","4H",h4[["t","o","h","l","c","v"]],.001))
    fx=pickle.load(open("bt_regime/fx_1h.pkl","rb"))
    for s,c in b.FX.items():
        h=fx[s][1][["t","o","h","l","c","v"]]; jobs.append((s,"forex","1H",h,c)); jobs.append((s,"forex","4H",b.rs(h,"4h"),c))
    with ProcessPoolExecutor(8) as ex:
        for r in ex.map(run, jobs): print(*r, flush=True)
