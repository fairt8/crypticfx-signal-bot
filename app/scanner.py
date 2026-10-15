import time, logging, threading
from . import config as C, binance, forex, strategy, db, telegram, outcomes
log = logging.getLogger("scanner")
STATE = dict(universe=[], universe_at=0, last_scan=None, forex_rank=[], strength={}, active_ccy=[], sessions=[], errors=[])

def crypto_universe():
    if not STATE["universe"] or time.time()-STATE["universe_at"] > C.UNIVERSE_REFRESH_HOURS*3600:
        STATE["universe"] = binance.top_usdt_symbols(); STATE["universe_at"] = time.time()
    return STATE["universe"]

def qualifies(sig):
    """Live filter (backtest v3): only crypto FVG setups (plus the FVG-PLAN row of the same setup) with setup_score >= MIN_POST_SCORE."""
    if sig.get("strategy") == "MF-REJ": return True   # own forex strategy with its own filters (session, bias, range, 2/day)
    return sig.get("market") == "crypto" and sig.get("strategy") in ("FVG", "FVG-PLAN") and (sig.get("setup_score") or 0) >= C.MIN_POST_SCORE

def scan(crypto=True, fx=True, post=True, gen=None):
    t0 = time.time(); found = []; cache = {}; watch = []
    if crypto:
        try: data = binance.fetch_many(crypto_universe())
        except Exception as e: STATE["errors"].append(f"crypto universe: {e}"); data = {}
        cache.update(data)
        for s,(h4,m5,h1) in data.items():
            try:
                sig = strategy.analyze(s, "crypto", h4, m5)
                if sig and C.ENABLE_D1 and "crypto" in C.EXPERIMENTAL_MARKETS:
                    b = strategy.daily_bias(binance.daily(s))   # only fetched when a setup exists (cached 6h)
                    if b == sig["direction"]:
                        sig["tags"] = sig["tags"] + ["FVG-D1"]; sig["reasons"].append(f"Daily structure bias {b} (FVG-D1 [EXPERIMENTAL])")
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
                try:
                    sig = strategy.analyze(p, "forex", h4, m5, info.get(p))
                    if sig: found.append(sig)
                    w = strategy.watch_info(p, "forex", h4, m5)
                    if w: watch.append(w)
                    if C.ENABLE_CHK and "forex" in C.EXPERIMENTAL_MARKETS:
                        sig = strategy.analyze_chk(p, "forex", h4, h1)
                        if sig: found.append(sig)
                except Exception as e: STATE["errors"].append(f"{p}: {e}")
            if C.ENABLE_MF:
              try:
                  import pandas as pd
                  sp, ss = strategy.mf_strong_pair(st, data, pd.Timestamp.now(tz="UTC").floor("h"))   # session of the last closed 1H candle ≈ current hour
                  STATE["mf_strong_pair"] = dict(pair=sp, session=ss)
                  for p in list(strategy.MF_PAIRS) + ([sp] if sp else []):
                      if p not in data: continue
                      try:
                          sig = strategy.analyze_mf(p, data[p][0], data[p][2], today_count=db.count_today(p, "MF-REJ"),
                                                    strong_session=ss if p == sp else None)
                          if sig: found.append(sig)
                      except Exception as e: STATE["errors"].append(f"MF {p}: {e}")
              except Exception as e: STATE["errors"].append(f"MF: {e}")
        except Exception as e: STATE["errors"].append(f"forex: {e}")
    if gen is not None and gen != STATE.get("gen"):   # watchdog abandoned this scan: don't save/post stale results
        print("[scan] abandoned scan finished late; results dropped", flush=True); return []
    new = []
    found = [g for g in found if qualifies(g)]   # filtered signals are not saved, so dashboard/stats match what is posted
    for sig in found:
        i = db.insert(sig)
        if i: new.append(db.get(i))
    if post:   # one Telegram post per setup: FVG + FVG-PLAN rows from the same setup are posted together
        groups = {}
        for s in new: groups.setdefault((s["symbol"], s["confirm_time"], s["strategy"] in ("FVG", "FVG-PLAN")), []).append(s)
        for g in groups.values():
            try: telegram.post_group(g)
            except Exception as e: STATE["errors"].append(f"telegram: {e}")
    STATE["watch"] = watch
    try: STATE["outcomes"] = outcomes.update_all(cache)
    except Exception as e: STATE["errors"].append(f"outcomes: {e}")
    if C.ENABLE_DON20:
        try:
            from . import don20; don20.check_stops(cache, post=post)
        except Exception as e: STATE["errors"].append(f"don20 stops: {e}")
    STATE["last_scan"] = time.strftime("%Y-%m-%d %H:%M:%S %Z"); STATE["errors"] = STATE["errors"][-20:]
    STATE["last_counts"] = dict(scanned_crypto=len([k for k in cache if k.endswith("USDT")]),
        scanned_forex=len([k for k in cache if not k.endswith("USDT")]), candidates=len(found), new=len(new))
    print(f"[scan] done in {time.time()-t0:.0f}s {STATE['last_counts']}", flush=True)
    return new

_started = False
TTL = lambda: C.SCAN_MINUTES*60 + 120
def _renew(stop):
    """Keep the scheduler lease alive while a scan runs (so a long scan never loses leadership mid-way)."""
    while not stop.wait(60):
        try: db.lease("scheduler", ttl_s=TTL())
        except Exception as e: print(f"[lease] renew failed: {e}", flush=True)
def _run_once():
    STATE["gen"] = gen = STATE.get("gen", 0) + 1
    def target():
        try: scan(gen=gen)
        except Exception as e: STATE["errors"].append(f"scan: {e}"); print(f"[scan] crashed: {e!r}", flush=True)
    th = threading.Thread(target=target, daemon=True, name=f"scan-{gen}")
    stop = threading.Event(); threading.Thread(target=_renew, args=(stop,), daemon=True).start()
    STATE["scan_started"] = time.strftime("%Y-%m-%d %H:%M:%S %Z"); th.start(); th.join(C.SCAN_WATCHDOG_S); stop.set()
    if th.is_alive():
        STATE["gen"] = gen + 1   # orphan the hung scan; its results will be dropped
        STATE["errors"].append(f"watchdog: scan {gen} exceeded {C.SCAN_WATCHDOG_S}s, abandoned")
        print(f"[scan] watchdog abandoned scan {gen}", flush=True)
def loop():
    while True:
        t = time.time()
        try:
            if db.lease("scheduler", ttl_s=TTL()):   # only one instance scans/posts, even if two overlap during a deploy
                STATE["leader"] = True; _run_once()
            else:
                STATE["leader"] = False; time.sleep(60); continue   # follower: retry soon so a redeploy takes over within ~1 min
        except BaseException as e:
            STATE["errors"].append(f"loop: {e}"); print(f"[loop] {e!r}", flush=True)
        time.sleep(max(30, C.SCAN_MINUTES*60 - (time.time()-t)))
def start():
    global _started
    if _started: return
    _started = True; threading.Thread(target=loop, daemon=True, name="scheduler").start()

if __name__ == "__main__":
    import sys, json; db.init()
    new = scan(crypto="--no-crypto" not in sys.argv, fx="--no-forex" not in sys.argv, post="--no-post" not in sys.argv)
    print(json.dumps(STATE.get("last_counts"), indent=1)); print("errors:", STATE["errors"][:5])
    for s in new: print(s["id"], s["symbol"], s["direction"], s["entry"], s["sl"], s["tp"], s["confidence"], s["in_session"], s["status"])
