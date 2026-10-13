import pandas as pd, numpy as np, sys
df = pd.read_csv("backtest_trades.csv"); df["confirm_time"]=pd.to_datetime(df.confirm_time); df=df.sort_values("confirm_time")
fx_start = df[df.market=="forex"].confirm_time.min()
def summ(d):
    c = d[d.status.isin(["tp","sl"])]
    if len(c)==0: return dict(signals=len(d), trades=0)
    eq = c.net_r.cumsum(); dd = (eq.cummax().clip(lower=0)-eq).max()
    return dict(signals=len(d), trades=len(c), unfilled=int((d.status=="expired").sum()), open_end=int((d.status.isin(["open","pending"])).sum()),
        win=round(100*(c.status=="tp").mean(),1), gross_exp=round(c.gross_r.mean(),3), net_exp=round(c.net_r.mean(),3),
        net_total=round(c.net_r.sum(),1), maxdd_r=round(dd,1), med_risk=round(100*c.risk_pct.median(),3))
def tbl(groups):
    return pd.DataFrame({k: summ(v) for k,v in groups}).T
out=[]
P=lambda t,x: out.append(f"\n### {t}\n\n"+x.to_markdown()+"\n")
P("Overall by market", tbl([("all",df)]+list(df.groupby("market"))))
df["bucket"]=pd.cut(df.confidence,[0,54,64,74,100],labels=["<55","55-64","65-74","75+"])
for m in ["crypto","forex"]:
    d=df[df.market==m]
    P(f"{m}: by confidence bucket", tbl(d.groupby("bucket",observed=True)))
    P(f"{m}: in vs outside London/NY session", tbl(d.groupby("in_session")))
    P(f"{m}: long vs short", tbl(d.groupby("direction")))
    P(f"{m}: minimum stop distance filter", tbl([(f">={x}%", d[d.risk_pct>=x/100]) for x in (0,0.3,0.5,1.0)]))
# factor-level check: win rate with/without each reason
c=df[df.status.isin(["tp","sl"])].copy(); c["w"]=(c.status=="tp")
facs={"trend EMA":"EMA50/EMA200","HH/HL aligned":"structure HH/HL aligned","structure against":"structure against","S/R":"swing S/R",
 "RSI ok":"not stretched","MACD":"MACD histogram agrees","candle":"Candlestick","Fib":"Fib","volume":"Volume spike","session":"Entry in London/NY",
 "priority":"Priority pair","bias agrees":"bias agrees"}
rows={}
for k,v in facs.items():
    h=c.reasons.str.contains(v,regex=False)
    rows[k]=dict(n_with=int(h.sum()),win_with=round(100*c.w[h].mean(),1) if h.any() else None,n_without=int((~h).sum()),win_without=round(100*c.w[~h].mean(),1) if (~h).any() else None)
P("Win rate with / without each confluence factor (closed trades, all markets)", pd.DataFrame(rows).T)
open("bt_tables.md","w").write("".join(out)); print("".join(out)); print("fx 15m data from", fx_start)
