"""MF-REJ pair expansion: one-home-currency rule over FOREX_30, live strong-zone rules (body bias, T2|HTF, pad 0.5, next-zone TP>=0.5R), 2/day cap per pair."""
import pickle, sys, glob, numpy as np, pandas as pd
sys.path.insert(0,'.')
from app.forex import FOREX_30
HOME={'Asian':{'JPY','AUD','NZD','CNH'},'London':{'GBP','EUR','CHF'},'NY':{'USD','CAD'}}
FIXED={'USDJPY':['Asian','NY'],'GBPJPY':['London','NY'],'EURUSD':['London'],'XAUUSD':['London']}   # user 2026-10-17: EURJPY and XAUUSD NY removed
BLOCK={('EURJPY','Asian'),('EURJPY','London'),('EURJPY','NY'),('XAUUSD','NY')}
def one_home(p,s):
    b,q=p[:3],p[3:]; h=HOME[s]
    return ((b in h)+(q in h))==1   # metals (XAU/XAG) have no home of their own -> session decided by USD
CNH=['USDCNH','EURCNH','GBPCNH','CHFCNH','CADCNH','AUDCNH','NZDCNH','CNHJPY']   # yfinance 1H available (bt_mfs/cnh.py)
XAUX=['XAUGBP','XAUEUR']   # synthetic (bt_mfs/xau_cross.py)
cand=[(p,s) for p in FOREX_30+CNH+XAUX if p not in FIXED for s in HOME if one_home(p,s) and (p,s) not in BLOCK]
rows=[]
for f in glob.glob('bt_mfs/ck/1h_*.pkl'): rows+=pickle.load(open(f,'rb'))
d=pd.DataFrame(rows); d['t']=pd.to_datetime(d.t,utc=True)
d=d[d.bias_body&((d.touches>=2)|d.htf)].copy()
d['net']=d['r0.5_zone']-d['cost_0.5']; d=d[d['r0.5_zone'].notna()]
Y1=pd.Timestamp('2025-10-15',tz='UTC')
def capped(x):   # live: max 2 MF-REJ per pair per UTC day
    x=x.sort_values('t'); return x[x.groupby(x.t.dt.date).cumcount()<2]
def st(x):
    return len(x),(x['r0.5_zone']>0).mean()*100 if len(x) else np.nan,x.net.sum(),x.net.mean() if len(x) else np.nan
out=[]
allowed={**FIXED}; 
for p,s in cand: allowed.setdefault(p,[]).append(s)
for p,ss in allowed.items():
    x=capped(d[(d.symbol==p)&d.session.isin(ss)])
    for s in ss:
        y=x[x.session==s]; a=st(y); y1=st(y[y.t<Y1]); y2=st(y[y.t>=Y1])
        out.append(dict(pair=p,session=s,fixed=p in FIXED,n=a[0],win=a[1],R=a[2],rtr=a[3],y1n=y1[0],y1w=y1[1],y1R=y1[2],y2n=y2[0],y2w=y2[1],y2R=y2[2]))
R=pd.DataFrame(out)
R['keep']=R.fixed|((R.rtr.fillna(-9)>=-0.05)&~((R.y1R<0)&(R.y2R<0))&(R.n>0))
R.to_csv('bt_mfs/expand.csv',index=False)
pd.set_option('display.width',250); print(R.round(2).to_string())
k=R[R.keep]; print('kept',len(k),'trades/2y',k.n.sum(),'per month',k.n.sum()/24, 'netR',k.R.sum())
# portfolio sim: per pair 2/day across kept sessions, overall cap 4 per scan (~per hour bar)
K={}
for r in k.itertuples(): K.setdefault(r.pair,[]).append(r.session)
z=pd.concat([capped(d[(d.symbol==p)&d.session.isin(ss)]) for p,ss in K.items()])
z=z.sort_values('t'); z=z[z.groupby('t').cumcount()<4]
for nm,y in [('all',z),('Y1',z[z.t<Y1]),('Y2',z[z.t>=Y1])]: print(nm,st(y))
