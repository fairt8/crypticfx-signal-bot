"""Download 1H CNH pairs (yfinance, 730d) and run the strong-zone MF-REJ backtest with 0.03% cost."""
import pickle, sys, warnings, pandas as pd, yfinance as yf
warnings.filterwarnings('ignore'); sys.path.insert(0,'bt_mfs'); sys.path.insert(0,'.')
import run
TK={'USDCNH':'CNH=X','EURCNH':'EURCNH=X','GBPCNH':'GBPCNH=X','CHFCNH':'CHFCNH=X','CADCNH':'CADCNH=X','AUDCNH':'AUDCNH=X','NZDCNH':'NZDCNH=X','CNHJPY':'CNHJPY=X'}
END=pd.Timestamp('2026-10-15 09:00',tz='UTC'); AGG={'o':'first','h':'max','l':'min','c':'last','v':'sum'}
D={}
for p,t in TK.items():
    a=yf.download(t,interval='1h',period='730d',progress=False,auto_adjust=False)
    a.columns=[c[0] if isinstance(c,tuple) else c for c in a.columns]
    a=a.dropna(subset=['Open','High','Low','Close']).rename(columns={'Open':'o','High':'h','Low':'l','Close':'c','Volume':'v'})[['o','h','l','c','v']]
    a.index=pd.to_datetime(a.index,utc=True)
    h4=a.resample('4h',origin='epoch').agg(AGG).dropna()
    def fin(x,f):
        x=x.copy(); x['t']=x.index; x['ct']=x.t+pd.Timedelta(f); return x[x.ct<=END].reset_index(drop=True)
    D[p]=(fin(h4,'4h'),fin(a,'1h')); print(p,len(D[p][1]),D[p][1].t.iloc[0],D[p][1].t.iloc[-1],flush=True)
pickle.dump(D,open('bt_mfs/cnh_1h.pkl','wb'))
run.FX1.update(D)
for p in ['USDCNH','EURCNH','GBPCNH','CHFCNH','CADCNH']:
    f=run.CK/f'1h_{p}.pkl'; f.unlink(missing_ok=True)
    r=run.run((p,'1h',D[p][1],pd.Timestamp('2024-10-15',tz='UTC')))
    for x in r:   # run() charges 0.02% to USD pairs; CNH pairs are 0.03%
        for pad in (0.25,0.5):
            if x.get(f'cost_{pad}')==x.get(f'cost_{pad}') and 'USD' in p: x[f'cost_{pad}']*=1.5
    pickle.dump(r,open(f,'wb')); print(p,len(r),flush=True)
