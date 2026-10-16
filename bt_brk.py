"""Research: backtest app/patterns_live.py (BRK + PAT-*) on 2y 4H data with the same series code the live scan uses."""
import pickle, glob, numpy as np, pandas as pd
from concurrent.futures import ProcessPoolExecutor
from app import patterns_live as P
import bt_retest_cup as b
T0=pd.Timestamp("2024-10-01",tz="UTC"); T1=pd.Timestamp("2026-10-01",tz="UTC"); SPLIT=pd.Timestamp("2025-10-01",tz="UTC")
def outc(d,k,e,s,dirn,R,cost):
    o=b.outcome(d.h.values,d.l.values,k,e,s,dirn,R); return None if o is None else o-cost/(abs(e-s)/e)
def run(job):
    sym,market,d,cost=job; rows=[]
    todo=[("BRK",)+P.brk_series(d,market)]
    for nm,v in P.PAT.items():
        if v[0]==market: todo.append((nm,)+P.pat_series(nm,d,market))
    for nm,dd,a,E in todo:
        for e in E:
            t=dd.t.iloc[e["k"]]
            if not(T0<=t<T1): continue
            rp=abs(e["entry"]-e["sl"])/e["entry"]
            if market=="crypto" and rp<.003: continue
            rows.append(dict(strat=nm,sym=sym,market=market,t=t,pat=e["pat"],r15=outc(dd,e["k"],e["entry"],e["sl"],e["dir"],1.5,cost),r3=outc(dd,e["k"],e["entry"],e["sl"],e["dir"],3.0,cost)))
    return rows
if __name__=="__main__":
    jobs=[]
    for f in sorted(glob.glob("bt_regime/data/*.pkl")):
        h4,_=pickle.load(open(f,"rb")); jobs.append((f.split("/")[-1][:-4],"crypto",h4[["t","o","h","l","c","v"]].copy(),.001))
    fx=pickle.load(open("bt_regime/fx_1h.pkl","rb"))
    for s,c in b.FX.items(): jobs.append((s,"forex",b.rs(fx[s][1][["t","o","h","l","c","v"]],"4h"),c))
    with ProcessPoolExecutor(8) as ex: A=pd.DataFrame([r for x in ex.map(run,jobs) for r in x])
    A=A.drop_duplicates(["strat","sym","t"]).reset_index(drop=True)   # live dedupe: one signal per symbol/strategy/bar
    A["half"]=np.where(A.t<SPLIT,"IS","OOS"); A.to_csv("bt_rc/live_bt.csv",index=False)
    def st(g):
        o={}
        for c,n in(("r15","1:1.5"),("r3","1:3")):
            x=g[c].dropna(); o[f"n {n}"]=len(x); o[f"win% {n}"]=round(100*(x>0).mean(),1) if len(x) else None; o[f"R/tr {n}"]=round(x.mean(),3) if len(x) else None
        return pd.Series(o)
    T=A.groupby(["strat","market","half"]).apply(st); print(T.to_string()); T.to_csv("bt_rc/live_bt_table.csv")
    B=A[A.strat=="BRK"]; print(B.assign(kind=np.where(B.pat=="HORIZ_LEVEL","horizontal","pattern")).groupby(["market","kind","half"]).apply(st).to_string())
    # trades per month (live replay rate)
    print((A.groupby("strat").size()/24).round(1).to_string())
