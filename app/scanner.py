import time, logging, threading
from . import config as C, binance, forex, strategy, db, telegram, outcomes
log = logging.getLogger("scanner")
STATE = dict(universe=[], universe_at=0, last_scan=None, forex_rank=[], strength={}, active_ccy=[], sessions=[], errors=[])

def crypto_universe():
    if not STATE["universe"] or time.time()-STATE["universe_at"] > C.UNIVERSE_REFRESH_HOURS*3600:
        STATE["universe"] = binance.top_usdt_symbols(); STATE["universe_at"] = time.time()
    return STATE["universe"]

def scan(crypto=True, fx=True, post=True):
    found = []; cache = {}; watch = []
    if crypto:
        data = binance.fetch_many(crypto_universe()); cache.update(data)
        for s,(h4,m5,h1) in data.items():
            try:
                sig = strategy.analyze(s, "crypto", h4, m5)
                if sig: found.append(sig)
                if sig and "crypto" in C.EXPERIMENTAL_MARKETS:
                    pv = strategy.plan_variant(sig)
                    if pv: found.append(pv)
                w = strategy.watch_info(s, "crypto", h4, m5)
                if w: watch.append(w)
                if C.ENABLE_CHK and "crypto" in C.EXPERIMENTAL_MARKETS:
                    sig = strategy.analyze_chk(s, "crypto", h4, h1)
                    if sig: found.append(sig)
            except Exception as e: STATE["errors"].append(f"{s}: {e}")
    if fx:
        try:
            data = forex.provider().fetch_many(forex.FOREX_30); cache.update(data)
            rows, st, act = forex.rank_pairs(data)
            STATE.update(forex_rank=rows, strength=st, active_ccy=act, sessions=forex.open_sessions())
            info = {r["pair"]: r for r in rows}
            for p,(h4,m5,h1) in data.items():
                sig = strategy.analyze(p, "forex", h4, m5, info.get(p))
                if sig: found.append(sig)
                w = strategy.watch_info(p, "forex", h4, m5)
                if w: watch.append(w)
                if C.ENABLE_CHK and "forex" in C.EXPERIMENTAL_MARKETS:
                    sig = strategy.analyze_chk(p, "forex", h4, h1)
                    if sig: found.append(sig)
        except Exception as e: STATE["errors"].append(f"forex: {e}")
    new = []
    for sig in found:
        i = db.insert(sig)
        if i: new.append(db.get(i))
    if post:   # one Telegram post per setup: FVG + FVG-PLAN rows from the same setup are posted together
        groups = {}
        for s in new: groups.setdefault((s["symbol"], s["confirm_time"], s["strategy"] in ("FVG", "FVG-PLAN")), []).append(s)
        for g in groups.values(): telegram.post_group(g)
    STATE["watch"] = watch
    STATE["outcomes"] = outcomes.update_all(cache)
    STATE["last_scan"] = time.strftime("%Y-%m-%d %H:%M:%S %Z"); STATE["errors"] = STATE["errors"][-20:]
    STATE["last_counts"] = dict(scanned_crypto=len([k for k in cache if k.endswith("USDT")]),
        scanned_forex=len([k for k in cache if not k.endswith("USDT")]), candidates=len(found), new=len(new))
    return new

_started = False
def loop():
    while True:
        try:
            if db.lease("scheduler", ttl_s=C.SCAN_MINUTES*60+120):   # only one instance scans/posts, even if two overlap during a deploy
                STATE["leader"] = True; scan()
            else: STATE["leader"] = False
        except Exception as e: STATE["errors"].append(str(e))
        time.sleep(C.SCAN_MINUTES*60)
def start():
    global _started
    if _started: return
    _started = True; threading.Thread(target=loop, daemon=True).start()

if __name__ == "__main__":
    import sys, json; db.init()
    new = scan(crypto="--no-crypto" not in sys.argv, fx="--no-forex" not in sys.argv, post="--no-post" not in sys.argv)
    print(json.dumps(STATE.get("last_counts"), indent=1)); print("errors:", STATE["errors"][:5])
    for s in new: print(s["id"], s["symbol"], s["direction"], s["entry"], s["sl"], s["tp"], s["confidence"], s["in_session"], s["status"])
