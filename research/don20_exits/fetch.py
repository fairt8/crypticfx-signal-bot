import requests, pandas as pd, os, json, sys
sys.path.insert(0, "/workspace/signal-bot")
from app.don20 import is_stock
B = "https://data-api.binance.vision/api/v3"
t = requests.get(B + "/ticker/24hr", timeout=30).json()
STABLE = {"USDC","FDUSD","TUSD","USDP","DAI","EUR","AEUR","USDE","XUSD","BFUSD","RLUSD","USD1","PAXG","WBTC","WBETH","BUSD","EURI","U"}
u = [x for x in t if x["symbol"].endswith("USDT") and x["symbol"][:-4] not in STABLE and not is_stock(x["symbol"]) and float(x["quoteVolume"]) > 1e6]
u.sort(key=lambda x: -float(x["quoteVolume"])); syms = [x["symbol"] for x in u[:int(sys.argv[1])]]
if "BTCUSDT" not in syms: syms.append("BTCUSDT")
os.makedirs("d1", exist_ok=True)
for s in syms:
    f = f"d1/{s}.csv"
    if os.path.exists(f): continue
    r = requests.get(B + "/klines", params=dict(symbol=s, interval="1d", limit=1000), timeout=30).json()
    d = pd.DataFrame(r, columns="t o h l c v ct qv n tb tq i".split())[["t","o","h","l","c","qv"]].astype(float)
    d.to_csv(f, index=False)
json.dump(syms, open("syms.json", "w")); print(len(syms))
