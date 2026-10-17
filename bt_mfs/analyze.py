import pandas as pd, numpy as np, matplotlib; matplotlib.use('Agg'); import matplotlib.pyplot as plt
d=pd.read_csv('bt_mfs/trades.csv'); d['t']=pd.to_datetime(d.t,utc=True)
o=pd.read_csv('bt_mf30/trades.csv'); o['t']=pd.to_datetime(o.t,utc=True)
Y1=pd.Timestamp('2025-10-15',tz='UTC')
DEF={'T2':lambda x:x.touches>=2,'T3':lambda x:x.touches>=3,'HTF':lambda x:x.htf,'T2|HTF':lambda x:(x.touches>=2)|x.htf,'T3|HTF':lambda x:(x.touches>=3)|x.htf}
UNI={'fixed':lambda x:x.fixed,'all LDN/NY':lambda x:x.session.isin(['London','NY']),'sess-ccy':lambda x:x.user}
def space(x,gap):  # one trade per symbol per variant within gap bars
    x=x.sort_values('t'); keep=[]; last={}
    for i,r in zip(x.index,zip(x.symbol,x.t)):
        if r[0] in last and r[1]-last[r[0]]<gap: continue
        last[r[0]]=r[1]; keep.append(i)
    return x.loc[keep]
def st(n,w):
    n=n.dropna(); return (len(n),(w.loc[n.index]>0).mean()*100 if len(n) else np.nan,n.mean() if len(n) else np.nan,n.sum())
rows=[];curves={}
for tf in ['1h','30m']:
    gap=pd.Timedelta('2h') if tf=='1h' else pd.Timedelta('2h')
    for bias in ['wick','body']:
        for dn,df in DEF.items():
            for un,uf in UNI.items():
                x=d[(d.tf==tf)&d['bias_'+bias]]; x=x[df(x)&uf(x)]; x=space(x,gap)
                for pad in (0.25,0.5):
                    for k in ('1.5','3','zone'):
                        n=x[f'r{pad}_{k}']-x[f'cost_{pad}']; w=x[f'r{pad}_{k}']
                        a=st(n,w); y1=st(n[x.t<Y1],w); y2=st(n[x.t>=Y1],w)
                        rr=dict(tf=tf,bias=bias,strong=dn,universe=un,pad=pad,target=k,n=a[0],win=a[1],rtr=a[2],tot=a[3],y1n=y1[0],y1=y1[2],y2n=y2[0],y2=y2[2])
                        for s in ['Asian','London','NY']:
                            z=st(n[x.session==s],w); rr[s]=f"{z[0]}/{z[2]:+.2f}" if z[0] else '-'
                        rows.append(rr)
                        if tf=='1h' and pad==0.5 and k=='3' and bias=='body' and un=='fixed': curves[dn]=(x.t,n.fillna(0))
R=pd.DataFrame(rows); R.to_csv('bt_mfs/summary.csv',index=False)
# old wick-based
OLD=[]
for tf in ['1h','30m']:
    for un,c in [('fixed','fixed'),('sess-ccy','user')]:
        x=o[(o.tf==tf)&o[c]]
        for k in ('1.5','3','zone'):
            n=x['r_'+k]-x.cost_r; a=st(n,x['r_'+k]); y1=st(n[x.t<Y1],x['r_'+k]); y2=st(n[x.t>=Y1],x['r_'+k])
            OLD.append(dict(tf=tf,universe=un,target=k,n=a[0],win=a[1],rtr=a[2],tot=a[3],y1n=y1[0],y1=y1[2],y2n=y2[0],y2=y2[2]))
OLD=pd.DataFrame(OLD)
f=lambda v:'-' if pd.isna(v) else f'{v:+.2f}'
L=['# MF-REJ with STRONG body-based S/R — backtest (research only)\n',
'Data: forex 28 + XAUUSD. 1H: 2024-10-15 → 2026-10-15 (Y1 = to 2025-10-15, Y2 = after). 30m: ~2026-08-08 → 2026-10-15 (~2 months). Costs 0.02% USD majors, 0.03% crosses, 0.05% XAU, netted in R. Stop+target in same bar = loss. Max hold as in app/backtest_mf.py.',
'Levels: 7-bar swing body extremes (max/min of open,close) from the last 30d (1H) / 15d (30m), plus 4H (120d) and Daily (365d) body swings; clustered within 0.25 ATR into zones. Entry: price tags the zone, flip candle closes back out of the zone in bias direction, no body close through the far edge, market at next open. Stop = far edge of zone + pad×ATR. "zone" target = next strong opposing zone (≥2 touches or HTF), needs ≥0.5R. Bias: Daily & 4H structure agree (wick = current live, body = body-based pivots). One trade per symbol per 2h.\n',
'## Old wick-based MF-REJ (bt_mf30 results)\n','|TF|Universe|Target|Trades|Win%|Net R/tr|Total R|Y1 R/tr (n)|Y2 R/tr (n)|','|-|-|-|-|-|-|-|-|-|']
for r in OLD.itertuples(): L.append(f'|{r.tf}|{r.universe}|{r.target}|{r.n}|{r.win:.0f}|{f(r.rtr)}|{r.tot:+.1f}|{f(r.y1)} ({r.y1n})|{f(r.y2)} ({r.y2n})|')
H='|Bias|Strong|Universe|Pad|Target|Trades|Win%|Net R/tr|Total R|Y1 R/tr (n)|Y2 R/tr (n)|Asian n/Rtr|London|NY|'
for tf in ['1h','30m']:
    L+=[f'\n## Strong-S/R results, {tf}\n',H,'|'+'-|'*14]
    for r in R[R.tf==tf].itertuples(): L.append(f'|{r.bias}|{r.strong}|{r.universe}|{r.pad}|{r.target}|{r.n}|{r.win:.0f}|{f(r.rtr)}|{r.tot:+.1f}|{f(r.y1)} ({r.y1n})|{f(r.y2)} ({r.y2n})|{r.Asian}|{r.London}|{r.NY}|')
G=R[(R.tf=='1h')&(R.y1>0)&(R.y2>0)&(R.y1n>=50)&(R.y2n>=50)]
L+=['\n## 1H variants net positive in BOTH years with ≥50 trades each year\n',G.to_markdown(index=False) if len(G) else 'None.']
open('backtest-report-mf-strong.md','w').write('\n'.join(L)+'\n')
fig,ax=plt.subplots(1,2,figsize=(14,5))
for dn,(t,n) in curves.items(): ax[0].plot(t.values,n.cumsum().values,label='strong '+dn)
x=o[(o.tf=='1h')&o.fixed].sort_values('t'); ax[0].plot(x.t,(x.r_3-x.cost_r).fillna(0).cumsum(),'k--',label='old wick-based')
ax[0].set_title('1H fixed session map, 1:3, body bias, pad 0.5: cumulative net R'); ax[0].legend(fontsize=7); ax[0].axhline(0,c='k',lw=.5)
s=R[(R.tf=='1h')&(R.universe=='fixed')&(R.pad==0.5)&(R.bias=='body')].pivot(index='strong',columns='target',values='rtr')
s.plot.bar(ax=ax[1]); ax[1].set_title('1H fixed map, body bias, pad 0.5: net R/trade'); ax[1].axhline(0,c='k',lw=.5)
plt.tight_layout(); plt.savefig('mf_strong_chart.png',dpi=110)
print(OLD.to_string()); print(R[R.tf=='1h'].sort_values('rtr',ascending=False).head(15).to_string()); print('BOTH',len(G)); print(G.to_string())
print(R[(R.tf=='1h')].groupby(['strong','target']).rtr.mean().unstack().round(2)); print(R[R.tf=='30m'].groupby(['strong','target']).rtr.mean().unstack().round(2))
