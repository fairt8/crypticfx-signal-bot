# extend daily history back (one more 1000-bar page) for the bt universe + live DON20 symbols, so 200D trends are known from Feb 2024
import requests, pandas as pd, os, json
B = "https://data-api.binance.vision/api/v3"
syms = json.load(open("syms.json")); live = sorted({r["sym"] for r in json.load(open("live.json"))})
os.makedirs("d1x", exist_ok=True)
C = "t o h l c v ct qv n tb tq i".split()
def get(s, **kw):
    r = requests.get(B + "/klines", params=dict(symbol=s, interval="1d", limit=1000, **kw), timeout=30).json()
    if not isinstance(r, list): return pd.DataFrame(columns=["t","o","h","l","c","qv"])
    return pd.DataFrame(r, columns=C)[["t","o","h","l","c","qv"]].astype(float)
for s in dict.fromkeys(syms + live):
    f = f"d1x/{s}.csv"
    if os.path.exists(f): continue
    cur = pd.read_csv(f"d1/{s}.csv") if os.path.exists(f"d1/{s}.csv") else get(s)
    if not len(cur): print("skip", s); continue
    old = get(s, endTime=int(cur.t.min()) - 1)
    pd.concat([old, cur]).drop_duplicates("t").sort_values("t").to_csv(f, index=False)
json.dump(live, open("live_syms.json", "w")); print("done", len(os.listdir("d1x")))
