"""Synthetic XAUGBP / XAUEUR 1H = XAUUSD (GC=F) / GBPUSD|EURUSD on common timestamps; wide (conservative) highs/lows.
Strong-zone MF-REJ backtest (cost 0.05%: run() charges XA* symbols 0.05%)."""
import pickle, sys, warnings, pandas as pd, numpy as np
warnings.filterwarnings('ignore'); sys.path.insert(0,'bt_mfs'); sys.path.insert(0,'.')
import run
AGG={'o':'first','h':'max','l':'min','c':'last','v':'sum'}
def synth(g, f):
    g=g.set_index('t'); f=f.set_index('t'); i=g.index.intersection(f.index); g,f=g.loc[i],f.loc[i]
    x=pd.DataFrame({'o':g.o/f.o,'c':g.c/f.c,'h':g.h/f.l,'l':g.l/f.h,'v':g.v})
    x['h']=np.maximum(x.h,np.maximum(x.o,x.c)); x['l']=np.minimum(x.l,np.minimum(x.o,x.c)); return x
def fin(x,fr):
    x=x.copy(); x['t']=x.index; x['ct']=x.t+pd.Timedelta(fr); return x.reset_index(drop=True)
D={}
for p,q in [('XAUGBP','GBPUSD'),('XAUEUR','EURUSD')]:
    a=synth(run.FX1['XAUUSD'][1],run.FX1[q][1])
    D[p]=(fin(a.resample('4h',origin='epoch').agg(AGG).dropna(),'4h'),fin(a,'1h')); print(p,len(a),a.index[0],a.index[-1])
    f=run.CK/f'1h_{p}.pkl'; f.unlink(missing_ok=True); r=run.run((p,'1h',D[p][1],pd.Timestamp('2024-10-15',tz='UTC'))) if run.FX1.update({p:D[p]}) is None else None
    print(p,len(r))
pickle.dump(D,open('bt_mfs/xau_cross_1h.pkl','wb'))
