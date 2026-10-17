"""Research only: MF-REJ with STRONG body-based S/R. Checkpoint per (tf,sym) in bt_mfs/ck/."""
import pickle, sys, numpy as np, pandas as pd
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
sys.path.insert(0,'.')
from app.backtest_mf import rs, atr, struct_bias, at, outcome
B=Path('bt_mfs'); CK=B/'ck'
FX1=pickle.load(open('bt_regime/fx_1h.pkl','rb'))
SESS={'Asian':(0,7),'London':(7,12),'NY':(12,17)}
SC={'London':{'GBP','EUR','CHF','XAU'},'NY':{'USD','CAD'},'Asian':{'JPY','AUD','NZD'}}
FIXED={'USDJPY':{'Asian','NY'},'GBPJPY':{'London','NY'},'EURJPY':{'Asian','London'},'EURUSD':{'London'},'XAUUSD':{'London','NY'}}
def sess(h):
    for k,(a,b) in SESS.items():
        if a<=h<b: return k
def body(x):
    y=x.copy(); y['h']=np.maximum(x.o,x.c); y['l']=np.minimum(x.o,x.c); return y
def pivots(x,k):
    """body swing extremes; returns (confirm_time ns, level) arrays (highs+lows mixed: S/R flip allowed)."""
    bh=np.maximum(x.o.values,x.c.values); bl=np.minimum(x.o.values,x.c.values); ct=x.ct.values; T=[];P=[]
    for j in range(k,len(x)-k):
        if bh[j]==bh[j-k:j+k+1].max(): T.append(ct[j+k]); P.append(bh[j])
        if bl[j]==bl[j-k:j+k+1].min(): T.append(ct[j+k]); P.append(bl[j])
    o=np.argsort(T,kind='stable'); return np.array(T)[o],np.array(P)[o]
def cluster(levels,anchor,tol):
    c=levels[np.abs(levels-anchor)<=tol]; 
    return (c.min(),c.max(),len(c)) if len(c) else (anchor,anchor,0)
def run(a):
    sym,tf,x,T0=a; f=CK/f'{tf}_{sym}.pkl'
    if f.exists(): return pickle.load(open(f,'rb'))
    h4=FX1[sym][0]; d1=rs(h4,'1D')
    bias={'wick':(struct_bias(d1,2),struct_bias(h4,2)),'body':(struct_bias(body(d1),2),struct_bias(body(h4),2))}
    dct,hct=d1.ct.values,h4.ct.values
    x=x.reset_index(drop=True); A=atr(x); O,H,L,Cl=x.o.values,x.h.values,x.l.values,x.c.values; ct=x.ct.values
    lt,lp=pivots(x,3); ht=[pivots(h4,2),pivots(d1,2)]
    look=np.timedelta64(30 if tf=='1h' else 15,'D'); hlook=[np.timedelta64(120,'D'),np.timedelta64(365,'D')]
    fx=not sym.startswith('XA'); cost=0.0005 if not fx else 0.0002 if 'USD' in sym else 0.0003
    b,q=sym[:3],sym[3:]; out=[]
    for i in range(30,len(x)-1):
        t=ct[i]
        if x.ct.iloc[i]<T0: continue
        a=A[i]
        if not a>0: continue
        flip_up=Cl[i-1]<O[i-1] and Cl[i]>O[i]; flip_dn=Cl[i-1]>O[i-1] and Cl[i]<O[i]
        if not(flip_up or flip_dn): continue
        et=x.t.iloc[i+1]; s=sess(et.hour)
        if s is None: continue
        bs={k:(at(dct,v[0],t),at(hct,v[1],t)) for k,v in bias.items()}
        bd={k:int(v[0]) if v[0]!=0 and v[0]==v[1] else 0 for k,v in bs.items()}
        d=1 if flip_up else -1
        if d not in bd.values(): continue
        m=(lt<=t)&(lt>t-look); LV=lp[m]
        HV=np.concatenate([p[(tt<=t)&(tt>t-hl)] for (tt,p),hl in zip(ht,hlook)])
        tol=0.25*a
        if d==1:
            lo=min(L[i-1],L[i]); cand=np.concatenate([LV,HV]); cand=cand[(cand>=lo-tol)&(cand<Cl[i])]
            cand=-np.sort(-cand)  # nearest below close first
        else:
            hi=max(H[i-1],H[i]); cand=np.concatenate([LV,HV]); cand=cand[(cand<=hi+tol)&(cand>Cl[i])]; cand=np.sort(cand)
        if not len(cand): continue
        zb,zt,n=cluster(LV,cand[0],tol); hb,htp,hn=cluster(HV,cand[0],tol)
        zlo,zhi=min(zb,hb) if n or hn else cand[0],max(zt,htp) if n or hn else cand[0]
        if hn==0: zlo,zhi=(zb,zt) if n else (cand[0],cand[0])
        else: zlo,zhi=(min(zb,hb),max(zt,htp)) if n else (hb,htp)
        # price must have reached zone and closed back out, without a body close through the far edge
        if d==1:
            if not(lo<=zhi+0.05*a and Cl[i]>zhi and min(O[i-1],Cl[i-1],O[i])>=zlo-tol): continue
        else:
            if not(hi>=zlo-0.05*a and Cl[i]<zlo and max(O[i-1],Cl[i-1],O[i])<=zhi+tol): continue
        entry=O[i+1]
        # opposing strong zone: nearest level beyond entry with >=2 LTF touches or HTF
        allv=np.concatenate([LV,HV]); opp=np.sort(allv[allv>entry])[:: 1] if d==1 else -np.sort(-allv[allv<entry])
        tz=None
        for p in opp:
            _,_,c1=cluster(LV,p,tol); _,_,c2=cluster(HV,p,tol)
            if c1>=2 or c2>=1: tz=cluster(np.concatenate([LV,HV]),p,tol)[0 if d==1 else 1]; break
        row=dict(tf=tf,symbol=sym,t=str(et),session=s,direction=d,bias_wick=bd['wick']==d,bias_body=bd['body']==d,
                 touches=n,htf=hn>0,zone_w=(zhi-zlo)/a,fixed=s in FIXED.get(sym,()),user=(b in SC[s])!=(q in SC[s]))
        for pad in (0.25,0.5):
            sl=zlo-pad*a if d==1 else zhi+pad*a
            if (sl-entry)*d>=0: row[f'cost_{pad}']=np.nan; continue
            res=outcome(d,entry,sl,tz,x,i+1,None); row[f'cost_{pad}']=cost*entry/abs(entry-sl)
            for k in ('1.5','3','zone'): row[f'r{pad}_{k}']=res.get(k)
        out.append(row)
    pickle.dump(out,open(f,'wb')); return out
if __name__=='__main__':
    m30=pickle.load(open('bt_mf30/fx_30m.pkl','rb'))
    jobs=[(s,'30m',x,x.ct.iloc[0]+pd.Timedelta('16D')) for s,x in m30.items() if s!='XAGUSD']
    jobs+=[(s,'1h',FX1[s][1],pd.Timestamp('2024-10-15',tz='UTC')) for s in FX1 if s!='XAGUSD']
    rows=[]
    with ProcessPoolExecutor(6) as ex:
        for j,r in zip(jobs,ex.map(run,jobs)): rows+=r; print(j[1],j[0],len(r),flush=True)
    pd.DataFrame(rows).to_csv(B/'trades.csv',index=False); print('saved',len(rows))
