"""Pluggable forex provider + session / currency-strength ranking."""
import pandas as pd, requests, itertools
from datetime import datetime, timezone
from . import config as C

# 30 instruments: 7 majors + 22 crosses + gold
FOREX_30 = ["EURUSD","GBPUSD","USDJPY","USDCHF","AUDUSD","USDCAD","NZDUSD",
    "EURGBP","EURJPY","EURCHF","EURAUD","EURCAD","EURNZD","GBPJPY","GBPCHF","GBPAUD","GBPCAD","GBPNZD",
    "AUDJPY","AUDCAD","AUDCHF","AUDNZD","NZDJPY","NZDCAD","NZDCHF","CADJPY","CADCHF","CHFJPY","XAGUSD","XAUUSD"]

# Extra instruments fetched ONLY for MF-REJ (not ranked/scanned by the other forex strategies)
MF_EXTRA = ["GBPCNH", "XAUAUD"]
# Synthetic instruments (no Yahoo ticker): price = base / divisor on common timestamps (bt_mfs/xau_cross.py)
SYNTH = {"XAUAUD": ("XAUUSD", "AUDUSD")}
_OHLCV = ["o", "h", "l", "c", "v"]
def synth(g, f):
    """g/f: OHLCV frames indexed by time. Wide (conservative) range: high = g.h/f.l, low = g.l/f.h, clipped to o/c."""
    g = g[_OHLCV]; f = f[_OHLCV]; i = g.index.intersection(f.index); g, f = g.loc[i], f.loc[i]
    x = pd.DataFrame({"o": g.o/f.o, "c": g.c/f.c, "h": g.h/f.l, "l": g.l/f.h, "v": g.v}, index=i)
    x["h"] = x[["h", "o", "c"]].max(axis=1); x["l"] = x[["l", "o", "c"]].min(axis=1); return x
def _h4(a): return a.resample("4h", origin="epoch").agg({"o":"first","h":"max","l":"min","c":"last","v":"sum"}).dropna()
def synth_triple(dx, dy):
    """Build (h4, ltf, h1) for a synthetic symbol from two already-fetched (h4, ltf, h1) triples."""
    ix = lambda d: d.set_index("t")
    a = synth(ix(dx[2]), ix(dy[2])); b = synth(ix(dx[1]), ix(dy[1]))
    return (_finish(_h4(a), "4h"), _finish(b, C.LTF_FREQ), _finish(a, "1h"))

# Session windows in UTC (fixed; DST shifts of ~1h are ignored in v1)
SESSIONS = {"Sydney": (21, 6), "Tokyo": (0, 9), "London": (7, 16), "NewYork": (12, 21)}
SESSION_CCY = {"Sydney": {"AUD","NZD"}, "Tokyo": {"JPY","AUD","NZD"},
               "London": {"GBP","EUR","CHF","XAU","XAG"}, "NewYork": {"USD","CAD","XAU","XAG"}}
# Creator's "major session" for entries = London or New York
MAJOR = {"London", "NewYork"}

def open_sessions(ts=None):
    h = (ts or datetime.now(timezone.utc)).hour
    return [s for s,(a,b) in SESSIONS.items() if (a <= h < b if a < b else (h >= a or h < b))]

def in_major_session(ts):
    return bool(set(open_sessions(ts)) & MAJOR)

def split(p): return p[:3], p[3:]

class YFinanceProvider:
    """Keyless. Unofficial Yahoo data: ~delayed, 5m history ≤60d, no 4h interval (resampled from 1h).
    Gold/silver use futures (GC=F / SI=F) as proxies for XAUUSD / XAGUSD."""
    name = "yfinance"
    def ticker(self, p): return {"XAUUSD":"GC=F","XAGUSD":"SI=F","USDCNH":"CNH=X"}.get(p, p+"=X")
    def _dl(self, tickers, interval, period):
        import yfinance as yf
        from concurrent.futures import ThreadPoolExecutor
        ex = ThreadPoolExecutor(1)
        fu = ex.submit(yf.download, tickers, interval=interval, period=period, group_by="ticker", progress=False,
                       auto_adjust=False, threads=True, timeout=15)
        try: return fu.result(timeout=C.YF_BUDGET_S)   # hard cap: a hung Yahoo request can't block the scan
        finally: ex.shutdown(wait=False, cancel_futures=True)
    def _norm(self, df):
        df = df.dropna(subset=["Open","High","Low","Close"]).rename(columns={"Open":"o","High":"h","Low":"l","Close":"c","Volume":"v"})
        df = df[["o","h","l","c","v"]].copy(); df.index = pd.to_datetime(df.index, utc=True)
        return df
    def fetch_many(self, pairs):
        want = list(dict.fromkeys(pairs)); real = list(dict.fromkeys(q for p in want for q in SYNTH.get(p, (p,))))
        tk = {self.ticker(p): p for p in real}
        h1 = self._dl(list(tk), "1h", "60d"); m5 = self._dl(list(tk), C.LTF, "10d")
        norm = {}
        for t, p in tk.items():
            try: norm[p] = (self._norm(h1[t]), self._norm(m5[t]))
            except Exception: pass
        out = {}
        for p in want:
            try:
                if p in SYNTH:
                    x, y = SYNTH[p]; a = synth(norm[x][0], norm[y][0]); b = synth(norm[x][1], norm[y][1])
                else: a, b = norm[p]
                out[p] = (_finish(_h4(a), "4h"), _finish(b, C.LTF_FREQ), _finish(a, "1h"))
            except Exception:
                pass
        return out

class TwelveDataProvider:
    """Free key: 800 credits/day, 8/min -> 30 pairs x 2 calls per scan is too heavy; use with a small pair list or slow scans."""
    name = "twelvedata"
    def sym(self, p): return p[:3]+"/"+p[3:]
    def series(self, p, interval, n):
        r = requests.get("https://api.twelvedata.com/time_series", params=dict(symbol=self.sym(p), interval=interval,
            outputsize=n, apikey=C.TWELVEDATA_API_KEY, timezone="UTC"), timeout=20).json()
        df = pd.DataFrame(r["values"]).iloc[::-1]
        df.index = pd.to_datetime(df.datetime, utc=True)
        df = df.rename(columns={"open":"o","high":"h","low":"l","close":"c"})[["o","h","l","c"]].astype(float); df["v"] = 0.0
        return df
    def fetch_many(self, pairs):
        import time; out = {}
        for p in pairs:
            try:
                out[p] = (_finish(self.series(p,"4h",300),"4h"), _finish(self.series(p,{"15m":"15min","5m":"5min","1m":"1min"}[C.LTF],400),C.LTF_FREQ), None); time.sleep(16)
            except Exception: pass
        return out

def _finish(df, freq):
    df = df.copy(); df["t"] = df.index; df["ct"] = df.t + pd.Timedelta(freq)
    df = df[df.ct <= pd.Timestamp.now(tz="UTC")]
    return df.reset_index(drop=True)

class OpenMarketForexProvider:
    """Optional forex source via the OpenMarket Data API. Official docs list crypto exchanges only;
    this is a best-effort mapping (OPENMARKET_FOREX_EXCHANGE, default INTERBANK_FX) and stays off
    as the primary unless FOREX_PROVIDER=openmarket. Missing pairs fall through silently."""
    name = "openmarket"
    def fetch_many(self, pairs):
        from . import openmarket as om
        if not om.enabled(): return {}
        want = list(dict.fromkeys(pairs)); real = list(dict.fromkeys(q for p in want for q in SYNTH.get(p, (p,))))
        raw = {}
        for p in real:
            try:
                h1 = om.forex_klines(p, "1h", 1500); ltf = om.forex_klines(p, C.LTF, 400)
                if len(h1) and len(ltf):
                    raw[p] = (h1.set_index("t")[_OHLCV], ltf.set_index("t")[_OHLCV])
            except Exception:
                pass
        out = {}
        for p in want:
            try:
                if p in SYNTH:
                    x, y = SYNTH[p]
                    if x not in raw or y not in raw: continue
                    a = synth(raw[x][0], raw[y][0]); b = synth(raw[x][1], raw[y][1])
                else:
                    if p not in raw: continue
                    a, b = raw[p]
                out[p] = (_finish(_h4(a), "4h"), _finish(b, C.LTF_FREQ), _finish(a, "1h"))
            except Exception:
                pass
        return out

class _FallbackForex:
    """Use the primary provider first; fill only the pairs it missed, without changing provider.name."""
    def __init__(self, primary, fallback):
        self.name = primary.name; self.primary = primary; self.fallback = fallback
    def fetch_many(self, pairs):
        want = list(pairs); out = {}
        try: out = self.primary.fetch_many(want) or {}
        except Exception: out = {}
        missing = [p for p in want if p not in out or not out[p] or not len(out[p][0])]
        if missing:
            try:
                extra = self.fallback.fetch_many(missing) or {}
                filled = []
                for p, v in extra.items():
                    if v and len(v[0]):
                        out[p] = v; filled.append(p)
                if filled:
                    print(f"[forex] OpenMarket fallback filled {', '.join(sorted(filled))}", flush=True)
            except Exception as e:
                print(f"[forex] OpenMarket fallback failed: {type(e).__name__}", flush=True)
        return out

def provider():
    if C.FOREX_PROVIDER == "openmarket":
        primary = OpenMarketForexProvider()
    elif C.FOREX_PROVIDER == "twelvedata" and C.TWELVEDATA_API_KEY:
        primary = TwelveDataProvider()
    else:
        primary = YFinanceProvider()
    # OpenMarket is a fallback when enabled, even if it is not the configured primary.
    # Keep yfinance as the default primary; FOREX_PROVIDER=openmarket opts in as primary.
    if C.FOREX_PROVIDER != "openmarket":
        try:
            from . import openmarket as om
            if om.enabled():
                return _FallbackForex(primary, OpenMarketForexProvider())
        except Exception:
            pass
    return primary

def currency_strength(data, hours=24):
    """Strength per currency = avg % change over `hours` across all pairs containing it (sign-adjusted)."""
    acc = {}
    for p,v in data.items():
        m5 = v[1]
        if len(m5) < 20: continue
        last = m5.c.iloc[-1]; t0 = m5.t.iloc[-1] - pd.Timedelta(hours=hours)
        past = m5[m5.t <= t0]; ref = past.c.iloc[-1] if len(past) else m5.c.iloc[0]
        ch = (last/ref - 1)*100; b,q = split(p)
        acc.setdefault(b,[]).append(ch); acc.setdefault(q,[]).append(-ch)
    return {k: sum(v)/len(v) for k,v in acc.items()}

def rank_pairs(data, now=None):
    """Interpretation of 'prioritise active-session pairs / only one strong pair':
    score = |strength(base)-strength(quote)| x (1 + 0.5 per currency active in an open session).
    Greedy pick: walk pairs by score, keep one per currency -> 'priority' set (the strongest pair for each currency)."""
    st = currency_strength(data); act = set().union(*[SESSION_CCY[s] for s in open_sessions(now)] or [set()])
    rows = []
    for p in data:
        b,q = split(p)
        if b not in st or q not in st: continue
        diff = st[b]-st[q]; mult = 1 + 0.5*((b in act)+(q in act))
        rows.append(dict(pair=p, score=abs(diff)*mult, bias="long" if diff>0 else "short", active=(b in act or q in act)))
    rows.sort(key=lambda r: -r["score"]); used=set(); 
    for r in rows:
        b,q = split(r["pair"]); r["priority"] = r["active"] and b not in used and q not in used
        if r["priority"]: used |= {b,q}
    return rows, st, sorted(act)
