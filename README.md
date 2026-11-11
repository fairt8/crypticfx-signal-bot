# FVG Signal Bot (v1)
Crypto + forex signal generator implementing `strategy-spec.md`: 4H fair value gap (bias) → price taps it → first same-direction 5m FVG → limit entry at the 5m FVG edge, stop beyond the 3 FVG candles, target = 3× risk. Web dashboard + Telegram bot + optional AI explanations. **Educational, not financial advice.**

## Project guide
A project-by-project status guide (what each part produces, what "complete" means, and the to-do list) is in [docs/PROJECTS_GUIDE.md](docs/PROJECTS_GUIDE.md). A printable copy is [docs/CrypticFx-Guide.pdf](docs/CrypticFx-Guide.pdf).

## Run locally
```bash
pip install -r requirements.txt
cp .env.example .env        # fill in what you have; everything is optional
python -m app.scanner --no-post          # one scan, print new signals
uvicorn app.web:app --port 8000          # dashboard at http://localhost:8000, scans every 5 min, Telegram polling
```

## Structure
| file | role |
|---|---|
| app/binance.py | top-N USDT pairs by **48h rolling quote volume** (`/api/v3/ticker?windowSize=2d`), klines; excludes stablecoins and leveraged tokens; refreshed every 6h. If a kline request fails or is empty and OpenMarket is enabled, candles are fetched from the OpenMarket Data API (Binance spot, then Binance Futures) |
| app/forex.py | 30 instruments (7 majors, 21 crosses, XAUUSD, XAGUSD), session detection, currency-strength ranking, providers (yfinance / Twelve Data / optional OpenMarket). Default primary is still yfinance; OpenMarket fills pairs the primary missed when enabled |
| app/openmarket.py | Optional OpenMarket.xyz Data API client (OHLCV fallback). Off unless `OPENMARKET_ENABLED=1` and `OPENMARKET_API_KEY` are set |
| app/strategy.py | FVG detection, core model, confidence scoring |
| app/outcomes.py | pending → open (entry touched) → tp / sl; expires after 24h unfilled; TP and SL in the same candle = SL |
| app/db.py | SQLite history |
| app/telegram.py | posts signals; /signals /history [days] /stats /explain id /ask question /start |
| app/ai.py | OpenAI-compatible chat; off when `LLM_API_KEY` is empty |
| app/web.py + desk.html | FastAPI: `/` (signal desk: equity in $/R, positions, alerts, PnL), `/api/desk` (cached 60s), `/api/signals?days=30`, `/api/stats`, `POST /api/scan`, `/api/explain/{id}`, `POST /api/chat` |
| app/weekly_report.py | Weekly strategy report (past week + all-time stats from the DB, unprofitable note); `python -m app.weekly_report`. Posted to the owner Telegram chat |
| app/backtest_all.py | Monthly all-strategy backtest (default ≥ 3 years) with a Telegram summary; `python -m app.backtest_all` |
| deploy/systemd/ | systemd service/timer units for the weekly report and monthly backtest |

## Confidence score (heuristic, not a probability)
Base 45 when the core rules are met, then: 4H EMA50/200 trend +7 · 4H HH/HL structure +7 (−5 if against) · FVG at swing S/R +6 · 5m RSI not stretched +4 (−4) · MACD histogram agrees +5 · candlestick pattern (engulfing, hammer, star, three-inside, tweezer, doji) +6 · Fib 50–78.6% retracement +6 · crypto volume spike +5 · in London/NY session +8, else −10 and flagged · forex: priority pair +5, strength bias agrees +5 (−5). Clamped to 5–95. Weights are untested guesses; backtest before trusting them.

## Forex session/strength rule (interpretation)
Sessions (UTC, DST ignored): Sydney 21–06, Tokyo 00–09, London 07–16, New York 12–21. Active currencies: Sydney AUD/NZD, Tokyo JPY/AUD/NZD, London GBP/EUR/CHF/XAU, NY USD/CAD/XAU.
Currency strength = average 24h % change of a currency across all pairs that contain it. Pair score = |strength(base) − strength(quote)| × (1 + 0.5 per active currency). Walking pairs by score, the first pair for each currency (with at least one active currency) is a **priority pair**: one strongest pair per currency. All 30 are still scanned; priority pairs and strength-aligned trades score higher.

## Data limits
- Binance public data: no key needed; weight limits are generous (one scan ≈ 400 requests and takes about 35s).
- yfinance (default forex): unofficial, can be delayed or rate-limited, and has no 4h interval (1h resampled to 4h). Gold and silver use COMEX futures GC=F / SI=F as proxies, so their prices differ from spot XAUUSD. FX volume is meaningless.
- Twelve Data free tier: 800 credits/day and 8/min, too few for 30 pairs every 5 minutes (the code paces requests at 16s each); use it with fewer pairs or a paid plan. Another provider can be added by implementing `fetch_many(pairs) -> {pair: (df4h, df5m)}`.
- OpenMarket.xyz Data API (optional fallback): `GET https://api.openmarket.xyz/v1/points` with `X-OpenMarket-Key`. Official coverage is crypto (this bot uses `BINANCE`, then `BINANCE_FUTURES`). It is used only when the primary source fails or lacks a symbol, or when `FOREX_PROVIDER=openmarket` (not the default; forex venues are not in the official exchange list). History depth follows the OpenMarket plan (Free 7 days, up to 1 year on Advanced), so it is not a 3-year backtest source. Rate limits are weight-based (Free: 10/min, 1000/day); the client caps calls, retries 429s, and caches briefly. Leave `OPENMARKET_ENABLED=0` until you add a key from your OpenMarket account settings.

## Deploy free: Render web service + Neon Postgres + 10-minute pinger
**1. Database (Neon, free).** Create a project at neon.tech, then copy the *pooled* connection string, e.g.
`postgresql://USER:PASSWORD@ep-xxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require`.
Optional: copy your local history into it:
```bash
DATABASE_URL='postgresql://...' python scripts/migrate_sqlite_to_pg.py signals.db   # idempotent, safe to re-run
```
**2. GitHub.** Create a **private** repo and push this folder (`.gitignore` already excludes `.env`, `*.db`, logs and backtest data):
```bash
git init && git add . && git commit -m "signal bot" && git branch -M main
git remote add origin https://github.com/<you>/fvg-signal-bot.git && git push -u origin main
```
**3. Render.** Dashboard → New → Blueprint → pick the repo (it reads `render.yaml`: free plan, `uvicorn app.web:app --host 0.0.0.0 --port $PORT --workers 1`, health check `/health`). Fill in the secret env vars when asked:

| Variable | Required | Value |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | yes | from @BotFather (@CrypticFxBot) |
| `TELEGRAM_CHAT_ID` | yes | `1318404489` |
| `DATABASE_URL` | yes | Neon connection string (from step 1) |
| `TELEGRAM_WEBHOOK_SECRET` | auto | generated by the blueprint (any random string works) |
| `LLM_API_KEY` | optional | OpenAI-compatible key; also set `LLM_BASE_URL`, `LLM_MODEL` if not OpenAI |
| preset in render.yaml | – | `LTF=15m`, `SCAN_MINUTES=15`, `SCAN_WORKERS=4`, `BINANCE_BASE`, `FOREX_PROVIDER=yfinance` |

Render sets `RENDER_EXTERNAL_URL` itself; the app uses it to register the Telegram **webhook** (`/telegram/webhook`, verified with the secret header), so no polling runs on Render.
**4. Pinger.** In UptimeRobot (free) or cron-job.org, add an HTTP(s) monitor on `https://<your-service>.onrender.com/health` every **10 minutes**. Free Render services sleep after ~15 minutes without traffic; the ping keeps the scanner running. (`/health` does no DB or network work, and HEAD is accepted.)
**5. Stop the local bot** (box server on port 8000) once Render is live, or run it without `TELEGRAM_BOT_TOKEN`. Otherwise both instances scan and post to the same chat, since they use different databases.

**Restart safety:** signals are unique per (symbol, confirm time, strategy) and posted only on first insert. The 6-hour PnL/position summary (`SUMMARY_EVERY_H`, default 6) time is stored in the DB, so restarts don't re-send it. A DB lease (`kv` table) makes only one instance scan and post; Telegram uses a webhook on Render, and locally it polls only if no webhook is set (or `TELEGRAM_MODE=polling`), behind a lease too.
**Memory:** a full scan (200 crypto + 30 FX; 300 crypto at SCAN_WORKERS=4 measured 243 MB peak, ~236 s, plus 1H data for the checklist) peaked at ~246 MB RSS with 8 workers and ~242 MB with 3; the whole server process measured 263 MB peak, comfortably under Render's 512 MB. `SCAN_WORKERS=4` is a safe default.
**Free-tier caveats:** Render free has a monthly instance-hour allowance (enough for one always-on service) and restarts on deploys. Neon free has limited monthly compute and storage and autosuspends idle computes. Scanning every 15 minutes (aligned to the 15m entry chart) lets it idle between scans. yfinance may be rate-limited from cloud IPs.

## Free hosting
Render (free web service; it sleeps after 15 min idle, so use an external pinger such as UptimeRobot; the disk is ephemeral, so the SQLite history resets on redeploy unless you use a paid disk), Railway (trial credit), Fly.io (small free allowance; a volume keeps the SQLite file), or any always-on free VM (Oracle Cloud Always Free is the most robust for a 24/7 scanner). Start command: see `Procfile`.

## Running without Grok Bot

The live scanner, Telegram alerts, 6-hour PnL summary, dashboard, Mini App and auto-trade already run as `fvg-signal-bot.service` on the private server (user `fvg`, working directory `/opt/fvg-signal-bot/app`, environment file `/etc/fvg-signal-bot.env`, venv `/opt/fvg-signal-bot/venv`). They do not need Grok Bot.

Two jobs that used to be Grok Bot routines now run as systemd timers on the same host and post to the owner Telegram chat through this bot (the token and chat id come from the environment file, never from a local `.env` on a development box):

| Job | Command | When (Africa/Lagos) | Units |
|---|---|---|---|
| Weekly strategy report | `python -m app.weekly_report` | Mondays at 09:53 | `fvg-weekly-report.service` / `.timer` |
| Monthly all-strategy backtest | `python -m app.backtest_all --days 1096 --workers 1` | 1st of the month at 09:00 | `fvg-monthly-backtest.service` / `.timer` |

The unit files live in `deploy/systemd/`. The monthly backtest is niced, uses `ionice`, has `MemoryMax=3G` and an 8-hour timeout, and writes under `/var/lib/fvg-signal-bot/bt_all` so it cannot starve the live service (the live unit is itself capped at 1G). Persistent=true, so a missed run is executed after a reboot. The calendar lines name `Africa/Lagos` explicitly.

**Deploy an update**

1. Back up the current checkout, e.g. `tar -czf /var/backups/fvg-signal-bot/app-<timestamp>-pre-<hash>.tgz` from the app dir.
2. Copy the new tree into `/opt/fvg-signal-bot/app` (tar over ssh is fine), `chown -R fvg:fvg` that tree, and write the git hash into `/opt/fvg-signal-bot/app/REVISION`.
3. Restart **only** `fvg-signal-bot.service` if the running app code changed. Do not `daemon-reload` for an ordinary code push. Do **not** restart the live service for report/backtest-only changes.
4. If the unit files in `deploy/systemd/` changed, copy them to `/etc/systemd/system/`, then `systemctl daemon-reload` and `systemctl enable --now fvg-weekly-report.timer fvg-monthly-backtest.timer`. Creating or changing unit files is the only case that needs `daemon-reload`. Enable and start the timers only; do not start the one-shot services unless you want a run now.

**View logs**

```bash
journalctl -u fvg-signal-bot.service -e
journalctl -u fvg-weekly-report.service -e
journalctl -u fvg-monthly-backtest.service -e
systemctl list-timers 'fvg-*'
systemctl status fvg-weekly-report.timer fvg-monthly-backtest.timer
```

**Restart**

```bash
# live scanner / Telegram / dashboard (only when its code changed)
sudo systemctl restart fvg-signal-bot.service
# run a report or backtest now (does not restart the live service)
sudo systemctl start fvg-weekly-report.service
sudo systemctl start fvg-monthly-backtest.service
```

Health of the live service: `curl -sS -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8100/health` (loopback only). Auto-trade stays off and in dry-run unless you switch it on; these jobs never change signal generation or alerts.

## Live posting filter (Oct 2026)
## Strategy tiers (since 2026-10-31)

There are only two live tiers. There are no NORMAL or EXPERIMENTAL signals any more.

| Tier | Strategy | Stop / target |
|---|---|---|
| ⭐ PRIMARY | DON20 | daily Donchian-20, 3×ATR trail |
| ⭐ PRIMARY | MF-REJ (forex) | current rules |
| ⭐ PRIMARY | PAT-TRIPLE (forex) | current rules |
| ⭐ PRIMARY | PAT-WEDGE (crypto) | 1.5× pattern stop, 3R |
| ⭐ PRIMARY | BRK (crypto) | current stop, 3R |
| 🔷 SECONDARY | CHK, FVG-D1 | unchanged |
| 🔷 SECONDARY | FVG-PLAN | 1.5× swing stop, 3R |
| 🔷 SECONDARY | PAT-TRIPLE-C (crypto) | 2× stop, 3R |
| 🔷 SECONDARY | FVG+TREND | last closed 1h candle ∓0.1 ATR (set at fill), 3R |
| 🔷 SECONDARY | DON28 (crypto, since 2026-11-04) | DON20 + coin's own 200-day SMA filter, 3×ATR trail |
| 🗄 retired | FVG (old live), PAT-CUP | history kept, no new signals |

### DON28 · DON20 + 200-day SMA filter (🔷 SECONDARY, since 2026-11-04)

- **Rule:** exactly the DON20 setup (daily close beyond the prior 20-day high/low, 3×ATR20 stop, chandelier trail, no target, 0.1% fee per side), kept only when it agrees with the coin's own 200-day SMA of daily closes: longs only when the signal-day close is above SMA200, shorts only when it is at or below it.
- **Research:** `research/don20_filters/don28_3y.py` (commit 1dba938): +349.4R over 3 years, 2023-10-01 → 2026-11-02, 127 coins, 2,199 trades.
- **Under 200 daily bars:** like the research (`cma = 0` → no filter), a coin with fewer than 200 daily bars is **not** skipped; its DON28 signal equals its DON20 signal (`SMA_UNKNOWN_PASSES` in `app/don20.py`). On the research data that is 495 of 3,174 per-coin entries (young listings).
- **Tracking:** its own table `don28` (same columns as `don20`) with its own one-position-per-coin rule, trail and exits, so it can differ from DON20 when one of them already holds the coin. It starts empty on 2026-11-04: no backfill, and DON20 positions are untouched. Same daily run as DON20 (after 00:05 UTC); one daily fetch of 260 daily candles per coin serves both. Stops are checked every 15-minute scan, like DON20. No per-scan cap (DON20 has none either). The per-scan `last_checked` writes for DON20/DON28 are batched into one UPDATE per table.
- **Telegram:** a DON28 entry/exit that mirrors a DON20 one posted in the same run (same coin, direction and signal day) is folded into the DON20 message as a line (`🔷 also DON28 ✓ (above/below SMA200 …)`, or `🔷 also DON28 #id closed`). Otherwise it gets its own 🔷 SECONDARY message, only when the alert mode includes SECONDARY (muted ones are still recorded). Trail lines identical to DON20 are not repeated.
- **Where it shows:** `/secondary`, `/signals`, `/don28` (live PnL card), `/stats`, the 6h summary, the dashboard `/`, the Mini App `/app`, and `/api/desk` (tier `secondary`).
- **Switch:** `ENABLE_DON28` (env, default `1`).
- **Parity:** `research/don20_filters/don28_parity.py` replays the research engine with the entry decision swapped for the live `signal()` + `don28_ok()` on the live 259-closed-bar window. On all 191 coins in `d1x3/`, it matched 3,174 of 3,174 research trades (signal day, direction and status) with 0 mismatches (`don28_parity.json`).

### Opposite-candle filters (since 2026-11-03)

BRK and PAT-TRIPLE forex skip **new** signals when a candlestick pattern pointing the other way has just completed. Open trades are not touched. The code is `app/candles21.py`, a verbatim port of the `research/candles21/patterns.py` detectors (the "all" set, including the relaxed `~` gap versions). Only candles that closed at or before the signal's 4H close are used.

| Strategy | Skip the signal when an opposite pattern completes on… | 3-year backtest (same stop / target) |
|---|---|---|
| BRK (crypto, current stop, 3R) | the 4H entry candle or the 2 before it, **or** one of the last 3 daily candles | 5117 trades +69.2R → 3286 trades +157.4R (Nov 3 refresh; every year better) |
| PAT-TRIPLE (forex, current rules) | the last completed daily candle | 165 trades +22.4R → 157 trades +28.9R |

- A skipped signal is saved once with status `filtered` and a reason (pattern, timeframe and close time).
- It is never posted to Telegram, gets no outcome tracking, and is left out of stats, summaries, `/history` and trade lists.
- It shows as 🕯 filtered · not sent in the dashboard / Mini App alerts feed.
- The scan log prints `[candles21] opposite-candle filters active: …` once, plus one line per skipped signal. `last_counts.candle_filtered` counts them per scan.
- `CANDLE_FILTERS` (env, default `BRK,PAT-TRIPLE`) switches them. Set it to empty to turn both off.
- Parity: `research/candles21/parity_live.py` runs the live filter on live-sized windows and compares it with the research filter on the full history. On the 3-year trades, BRK filtered 1831/5117 in both and PAT-TRIPLE FX 8/165 (prev_oct30) and 8/167 (out3y) in both, with 0 mismatches.

The stop variants live in `app/variants.py`. They are the same code as the backtest in `research/stop_variants_3r/engine.py`. The crypto stop floor is 0.3%, and the $1M crypto volume floor still applies. Alert modes are `/alerts primary` and `/alerts primary_secondary`. Other commands are `/signals`, `/primary`, `/secondary`, `/don20`, `/don28` and `/stats`. The Mini App is at `/app` (owner only) and the dashboard is at `/`.

Only **crypto FVG setups with raw setup score ≥ `MIN_POST_SCORE` (default 70, env-overridable)** are saved and posted (TP stays 1:3). Forex, CHK and sub-70 crypto FVG setups are dropped before saving, so dashboard/stats match Telegram. FVG+TREND / FVG-PLAN / FVG-D1 experimental tags still ride on qualifying signals. Backtest v3: ~29% win rate, ≈ +0.02R/trade (break-even; paper signals, not an edge).
`TELEGRAM_BOT_TOKEN` is sanitized (whitespace/quotes/leading `bot` stripped); `/api/stats` → `telegram_token_shape` shows length/regex/getMe result only.
- Every signal also shows **TP1 (1:1.5)** (entry ± 1.5×risk) next to **TP2 (1:3)** in Telegram, dashboard and API (`tp1`). Outcomes/stats are still tracked on TP2 only.
