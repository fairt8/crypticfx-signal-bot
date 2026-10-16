"""One-shot scan for GitHub Actions: scan -> outcomes -> DON20 daily (when due) -> 2h summary (when due), then exit.
Telegram via sendMessage only (no webhook server). Uses the DB 'scheduler' lease so it never overlaps a Render scheduler."""
import sys, time, threading
from datetime import datetime, timezone
from . import config as C, db, scanner, telegram, summary, don20

def main():
    post = "--no-post" not in sys.argv
    db.init(); don20.init()
    if not db.lease("scheduler", ttl_s=C.SCAN_WATCHDOG_S + 300):
        print("[run_once] another instance holds the scheduler lease; skipping", flush=True); return 0
    scanner.STATE["leader"] = True
    t0 = time.time()
    scanner.scan(post=post)
    if C.ENABLE_DON20 and don20.due():
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        th = threading.Thread(target=lambda: don20.daily_run(scanner.crypto_universe(), post=post), daemon=True); th.start()
        th.join(C.SCAN_WATCHDOG_S); db.kv_set("don20_last_day", day)
    if post and telegram.enabled() and summary.due(2):
        ok = telegram.send(summary.build(2), html=True)
        if ok: db.kv_set("last_summary_at", datetime.now(timezone.utc).isoformat())
        print(f"[run_once] summary sent={ok}", flush=True)
    print(f"[run_once] total {time.time()-t0:.0f}s counts={scanner.STATE.get('last_counts')} errors={scanner.STATE['errors'][:5]}", flush=True)
    try: db.release_lease("scheduler")
    except Exception: pass
    return 0

if __name__ == "__main__": sys.exit(main())
