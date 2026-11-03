"""Per-calendar-year net R / trades / win% per strategy+variant, from out3y CSVs (same load() as report3y)."""
import json, os
from report3y import load, ORDER
from report import VN
HERE=os.path.dirname(os.path.abspath(__file__))
d=load(); d["yr"]=d.t.dt.year
R=json.load(open(f"{HERE}/results3y.json"))["results"]
L=["# Per-year results, 3-year backtest (net R after fees; trades; win %)","",
f"Crypto {d[d.market=='crypto'].t.min():%Y-%m-%d}→{d[d.market=='crypto'].t.max():%Y-%m-%d}; forex {d[d.market=='forex'].t.min():%Y-%m-%d}→{d[d.market=='forex'].t.max():%Y-%m-%d}. 2023 = Oct–Dec only. Same trade set as results3y.md.","",
"| Strategy | Variant | 2023 | 2024 | 2025 | 2026 | Total |","|-|-|-|-|-|-|-|"]
for s,m in ORDER:
  g0=d[(d.strategy==s)&(d.market==m)]
  for v,gv in g0.groupby("variant",sort=False):
    c=[]
    for y in (2023,2024,2025,2026):
      g=gv[gv.yr==y]
      c.append("—" if len(g)==0 else f"{g.net_r.sum():+.1f}R ({len(g)}, {100*(g.net_r>0).mean():.0f}%)")
    c.append(f"**{gv.net_r.sum():+.1f}R** ({len(gv)}, {100*(gv.net_r>0).mean():.0f}%)")
    L.append(f"| {s} {m} | {VN.get(v,v)} | "+" | ".join(c)+" |")
open(f"{HERE}/per_year.md","w").write("\n".join(L)+"\n"); print("\n".join(L))
