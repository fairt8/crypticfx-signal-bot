import json, numpy as np, pandas as pd
N, COST = 20, 0.001
syms = json.load(open("syms.json"))
def load(s):
    d = pd.read_csv(f"d1/{s}.csv"); d["t"] = pd.to_datetime(d.t, unit="ms", utc=True); return d.iloc[:-1].reset_index(drop=True)  # drop today's unclosed bar
btc = load("BTCUSDT"); ma = btc.c.rolling(200).mean(); sl = ma/ma.shift(20)-1
SEAS = pd.Series(np.where((btc.c>ma)&(sl>0),"bull",np.where((btc.c<ma)&(sl<0),"bear","range")), index=btc.t.dt.date); SEAS[ma.isna().values]="n/a"
def atr(d):
    tr = pd.concat([d.h-d.l,(d.h-d.c.shift()).abs(),(d.l-d.c.shift()).abs()],axis=1).max(axis=1); return tr.rolling(N).mean()
# variant: dict(k=init ATR mult, trail=('chand',m)|('dc',n)|None, tp=R|None, p50=R|None, tmax=days|None)
V = {
 "current (3xATR chandelier)": dict(),
 "fixed TP 1R": dict(tp=1.0), "fixed TP 1.5R": dict(tp=1.5), "fixed TP 2R": dict(tp=2.0), "fixed TP 3R": dict(tp=3.0),
 "50% at 1R + stop to BE": dict(p50=1.0),
 "50% at 1.5R + stop to BE": dict(p50=1.5),
 "2xATR chandelier trail": dict(trail=("chand",2.0)),
 "Donchian-10 exit": dict(trail=("dc",10)),
 "50% at 1R + BE + Donchian-10": dict(p50=1.0, trail=("dc",10)),
 "time exit 10 days": dict(tmax=10), "time exit 20 days": dict(tmax=20),
 "tighter: 1.5xATR stop + 1.5xATR trail": dict(k=1.5, trail=("chand",1.5)),
 "tighter: 2xATR stop + 2xATR trail": dict(k=2.0, trail=("chand",2.0)),
 "current exits + skip BTC 'range' season": dict(filt="norange"),
 "current exits + with-trend only (long in bull, short in bear)": dict(filt="trend"),
 "50% at 1.5R + BE + skip 'range'": dict(p50=1.5, filt="norange"),
}
def run(d, v):
    k = v.get("k",3.0); tr = v.get("trail",("chand",k)); A = atr(d).values
    o,h,l,c,qv,t = (d[x].values for x in "o h l c qv t".split()); out=[]; pos=None
    def fin(pos, x, i, status):
        sd=pos["sd"]; e=pos["e"]; R=pos["risk"]; legs=pos["legs"]+[(pos["w"],x)]
        g=sum(w*sd*(xx-e)/R for w,xx in legs); n=g-sum(w*COST*(e+xx)/R for w,xx in legs)
        out.append(dict(t=t[pos["i"]], exit=t[i], days=i-pos["i"], dir=pos["dir"], g=g, n=n, status=status, risk_pct=R/e))
    for i in range(N+2, len(d)):
        if pos:
            sd=pos["sd"]; st=pos["stop"]; hit=None
            if (sd==1 and l[i]<=st) or (sd==-1 and h[i]>=st): hit = min(st,o[i]) if sd==1 else max(st,o[i])
            if hit is not None: fin(pos,hit,i,"closed"); pos=None; continue
            e=pos["e"]; R=pos["risk"]
            if v.get("p50") and not pos["legs"]:
                lv=e+sd*v["p50"]*R
                if (sd==1 and h[i]>=lv) or (sd==-1 and l[i]<=lv):
                    x=max(lv,o[i]) if sd==1 else min(lv,o[i]); pos["legs"].append((0.5,x)); pos["w"]=0.5
                    pos["stop"]= max(pos["stop"],e) if sd==1 else min(pos["stop"],e)
            if v.get("tp"):
                lv=e+sd*v["tp"]*R
                if (sd==1 and h[i]>=lv) or (sd==-1 and l[i]<=lv):
                    fin(pos, max(lv,o[i]) if sd==1 else min(lv,o[i]), i, "closed"); pos=None; continue
            if v.get("tmax") and i-pos["i"]>=v["tmax"]: fin(pos,c[i],i,"closed"); pos=None; continue
            pos["best"]=max(pos["best"],c[i]) if sd==1 else min(pos["best"],c[i])
            if tr[0]=="chand": ns=pos["best"]-sd*tr[1]*A[i]
            else: ns=(l[i-tr[1]+1:i+1].min() if sd==1 else h[i-tr[1]+1:i+1].max())
            pos["stop"]=max(pos["stop"],ns) if sd==1 else min(pos["stop"],ns)
            continue
        a=A[i]
        if not a or a!=a or a<=0 or qv[i]<1e6: continue
        hi=h[i-N:i].max(); lo=l[i-N:i].min()
        side = 1 if c[i]>hi else (-1 if c[i]<lo else 0)
        if not side: continue
        if v.get('filt'):
            ss=SEAS.get(pd.Timestamp(t[i]).date(),'n/a')
            if v['filt']=='norange' and ss=='range': continue
            if v['filt']=='trend' and not ((side==1 and ss=='bull') or (side==-1 and ss=='bear')): continue
        e=c[i]; st=e-side*k*a
        if side==1 and st<=0: continue
        pos=dict(sd=side,dir="long" if side==1 else "short",e=e,risk=abs(e-st),stop=st,best=e,i=i,legs=[],w=1.0)
    if pos: fin(pos,c[-1],len(d)-1,"open")
    return out
def mdd(df):
    eq = df.sort_values("exit").groupby(df.exit.dt.date).n.sum().cumsum(); return float((eq.cummax().clip(lower=0)-eq).max()) if len(eq) else 0
def stats(x):
    cl=x[x.status=="closed"]
    return dict(trades=len(cl), win=round(100*(cl.n>0).mean(),1) if len(cl) else None, net=round(cl.n.sum(),1), avg=round(cl.n.mean(),3) if len(cl) else None,
                mdd=round(mdd(cl),1), days=round(cl.days.mean(),1) if len(cl) else None, open_n=int((x.status=="open").sum()), open_mtm=round(x[x.status=="open"].n.sum(),1))
data={s:load(s) for s in syms}
T0=pd.Timestamp("2024-02-01")
res={}; allt={}
for name,v in V.items():
    rows=[]
    for s,d in data.items():
        if len(d)<60: continue
        for r in run(d,v):
            if pd.Timestamp(r["t"])>=T0: r["sym"]=s; rows.append(r)
    df=pd.DataFrame(rows); df["t"]=pd.to_datetime(df.t); df["exit"]=pd.to_datetime(df.exit); df["season"]=[SEAS.get(pd.Timestamp(x).date(),"n/a") for x in df.t]
    allt[name]=df
    res[name]=dict(all=stats(df), **{s:stats(df[df.season==s]) for s in ("bull","bear","range")}, long=stats(df[df.dir=="long"]), short=stats(df[df.dir=="short"]),
                   last120=stats(df[df.t>=df.t.max()-pd.Timedelta("120D")]))
json.dump(res,open("res.json","w"),indent=1,default=str)
cur=allt["current (3xATR chandelier)"]; cl=cur[cur.status=="closed"]
print("period", cur.t.min().date(), "->", cur.t.max().date(), "coins", len(data), "median risk %", round(100*cur.risk_pct.median(),1))
print("season days", SEAS.value_counts().to_dict())
for name,r in res.items():
    a=r["all"]; print(f"{name:42s} n={a['trades']:4d} win={a['win']}% net={a['net']:+7.1f} avg={a['avg']:+.3f} mdd={a['mdd']:5.1f} hold={a['days']}d open={a['open_n']}({a['open_mtm']:+.1f}) | bull {r['bull']['net']:+.1f}/{r['bull']['trades']} ({r['bull']['avg']}) bear {r['bear']['net']:+.1f}/{r['bear']['trades']} ({r['bear']['avg']}) range {r['range']['net']:+.1f}/{r['range']['trades']} | L {r['long']['net']:+.1f}/{r['long']['trades']} S {r['short']['net']:+.1f}/{r['short']['trades']} | 120d {r['last120']['net']:+.1f}/{r['last120']['trades']}")

print("BTC season last 10 days:", SEAS.iloc[-10:].to_dict())
print("\nfair comparison, only trades opened when a season is known (from ~Sep 2024):")
for name in V:
    df=allt[name]; x=df[df.season!="n/a"]; a=stats(x); print(f"{name:62s} n={a['trades']:4d} win={a['win']}% net={a['net']:+7.1f} avg={a['avg']:+.3f} mdd={a['mdd']:5.1f}")
print("\nby entry year (closed net R / trades):")
for name in ["current (3xATR chandelier)","fixed TP 2R","50% at 1.5R + stop to BE","time exit 20 days","current exits + skip BTC 'range' season","current exits + with-trend only (long in bull, short in bear)"]:
    df=allt[name]; cl=df[df.status=="closed"]; g=cl.groupby(cl.t.dt.year).n.agg(["sum","size"]).round(1)
    print(f"{name:62s}", " ".join(f"{y}: {r['sum']:+.1f}/{int(r['size'])}" for y,r in g.iterrows()))
json.dump({k:v for k,v in res.items()},open("res.json","w"),indent=1,default=str)
print("\ncurrent exits by initial stop distance (% of price):")
df=allt["current (3xATR chandelier)"]; cl=df[df.status=="closed"].copy()
cl["b"]=pd.cut(cl.risk_pct*100,[0,10,15,20,25,30,40,100])
print(cl.groupby("b",observed=True).n.agg(["size","sum","mean"]).round(3))
