import glob, pickle, json, numpy as np, pandas as pd, matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
R="bt_regime"
A=[]
for f in glob.glob("bt_rc/*.pkl"):
    rows=pickle.load(open(f,"rb"))
    if "/cup_" not in f: rows=[r for r in rows if "CUP" not in r["pat"]]
    A+=rows
A=pd.DataFrame(A); A["t"]=pd.to_datetime(A.t,utc=True)
A["fam"]=A.pat.replace({"DOUBLE_TOP":"DOUBLE","DOUBLE_BOTTOM":"DOUBLE","TRIPLE_TOP":"TRIPLE","TRIPLE_BOTTOM":"TRIPLE","ASC_TRIANGLE":"TRIANGLE","DESC_TRIANGLE":"TRIANGLE","RISING_WEDGE":"WEDGE","FALLING_WEDGE":"WEDGE","BULL_FLAG":"FLAG","BEAR_FLAG":"FLAG","RECTANGLE":"HORIZ_SR","CUP_HANDLE":"CUP","INV_CUP_HANDLE":"CUP"})
A["half"]=np.where(A.t<pd.Timestamp("2025-10-01",tz="UTC"),"IS","OOS")
# regimes (same ex-ante weekly labels as backtest-report-regimes.md)
_,m=pickle.load(open(f"{R}/data/BTCUSDT.pkl","rb"))
w=m.set_index("t").resample("W-MON",label="left",closed="left").agg({"c":"last","qv":"sum"})
w["ma20"]=w.c.rolling(20).mean(); w["ret4"]=w.c.pct_change(4); w["vmed"]=w.qv.rolling(26).median()
w["trend"]=np.where((w.c>w.ma20)&(w.ret4>.05),"bull",np.where((w.c<w.ma20)&(w.ret4<-.05),"bear","sideways"))
w["vol"]=np.where(w.qv>w.vmed,"high-vol","low-vol"); lab=w[["trend","vol"]].shift(1)
fx=pickle.load(open(f"{R}/fx_1h.pkl","rb"))
wr=lambda h,f: getattr(h.set_index("t")[f].resample("W-MON",label="left",closed="left"),{"h":"max","l":"min","c":"last"}[f])()
rng=pd.concat({k:(wr(h,"h")-wr(h,"l"))/wr(h,"c") for k,(_,h) in fx.items() if k not in("XAUUSD","XAGUSD")},axis=1).median(axis=1)
fl=pd.DataFrame({"fxvol":np.where(rng>rng.rolling(26,min_periods=8).median(),"high-ATR","low-ATR")},index=rng.index).shift(1)
wk=A.t.dt.floor("D")-pd.to_timedelta(A.t.dt.weekday,unit="D")
A["trend"]=lab.trend.reindex(wk).values; A["vol"]=lab.vol.reindex(wk).values; A["fxvol"]=fl.fxvol.reindex(wk).values
A.loc[A.market=="forex",["trend","vol"]]=None; A.loc[A.market=="crypto","fxvol"]=None
A.to_csv("bt_rc/trades.csv",index=False)
def st(g):
    o={}
    for c,nm in(("r15","1:1.5"),("r3","1:3"),("rmm","MM")):
        x=g[c].dropna(); o[f"n {nm}"]=len(x); o[f"win% {nm}"]=round(100*(x>0).mean(),1) if len(x) else np.nan; o[f"R/tr {nm}"]=round(x.mean(),3) if len(x) else np.nan
    return pd.Series(o)
keys=["fam","market","tf","entry"]
T=A.groupby(keys+["half"]).apply(st).unstack("half"); T.columns=[f"{b} {a}" for a,b in T.columns]
ALL=A.groupby(keys).apply(st)
P=[]
for k,row in T.iterrows():
    for nm in("1:1.5","1:3","MM"):
        ok=row[f"IS n {nm}"]>=50 and row[f"OOS n {nm}"]>=50 and row[f"IS R/tr {nm}"]>0 and row[f"OOS R/tr {nm}"]>0
        P.append(dict(zip(keys,k),target=nm,IS_n=row[f"IS n {nm}"],IS_win=row[f"IS win% {nm}"],IS_R=row[f"IS R/tr {nm}"],OOS_n=row[f"OOS n {nm}"],OOS_win=row[f"OOS win% {nm}"],OOS_R=row[f"OOS R/tr {nm}"],PASS=ok))
P=pd.DataFrame(P)
G=[]
for k,g in A.groupby(keys):
    for col in("trend","vol","fxvol"):
        for v,gg in g.dropna(subset=[col]).groupby(col):
            s=st(gg); G.append(dict(zip(keys,k),regime=f"{col}={v}",**s.to_dict()))
G=pd.DataFrame(G)
# entry comparison by market/tf/entry (all families excl cup) and cup
cmp=A.assign(grp=np.where(A.fam=="CUP","CUP","breakout pats")).groupby(["grp","market","tf","entry","half"]).apply(st)
with open("backtest-report-retest-cup.md","w") as f:
    f.write("# Breakout-then-retest and cup & handle backtest (research only, live bot unchanged)\n\n")
    f.write(f"Total resolved trade rows: {len(A)}. Period 2024-10-01 to 2026-09-30. IS = Oct 2024-Sep 2025, OOS = Oct 2025-Sep 2026.\n\n")
    f.write(open("bt_rc/method.md").read())
    f.write("\n## PASS list (positive R/trade in IS and OOS, n>=50 each)\n\n"); pp=P[P.PASS]
    f.write(pp.to_markdown(index=False) if len(pp) else "**None.**\n"); f.write("\n\n## Headline: immediate vs retest, all breakout patterns pooled\n\n")
    f.write(cmp.to_markdown()); f.write("\n\n## Family x market x TF x entry, IS vs OOS\n\n"); f.write(P.to_markdown(index=False))
    f.write("\n\n## Full-period totals\n\n"); f.write(ALL.to_markdown()); f.write("\n\n## Regime splits (full period)\n\n"); f.write(G.to_markdown(index=False))
P.to_csv("bt_rc/pass.csv",index=False); G.to_csv("bt_rc/regimes.csv",index=False); cmp.to_csv("bt_rc/cmp.csv")
# chart
fig,ax=plt.subplots(1,2,figsize=(14,6))
c2=ALL.reset_index(); c2["lab"]=c2.fam+" "+c2.market+" "+c2.tf
for e,off,col in(("immediate",-.27,"tab:gray"),("retest_swing",0,"tab:blue"),("retest_lvl",.27,"tab:orange")):
    s=c2[c2.entry==e].set_index("lab")
    labs=sorted(c2.lab.unique()); y=np.arange(len(labs))
    ax[0].barh(y+off,s.reindex(labs)["R/tr 1:1.5"],height=.27,color=col,label=e)
    ax[1].barh(y+off,s.reindex(labs)["win% 1:1.5"],height=.27,color=col,label=e)
for a_ in ax: a_.set_yticks(y); a_.set_yticklabels(labs,fontsize=7); a_.invert_yaxis()
ax[0].axvline(0,color="k"); ax[0].set_title("Net R/trade at 1:1.5 (after costs)"); ax[1].axvline(50,color="r",ls="--"); ax[1].set_title("Win % at 1:1.5")
ax[0].legend(fontsize=8); plt.tight_layout(); plt.savefig("retest_cup_chart.png",dpi=110)
print(pp.to_string() if len(pp) else "NO PASS")
print(cmp.to_string())
best=P.sort_values("OOS_R",ascending=False).head(15); print(best.to_string())
