# Stop-loss variants at a fixed 3R take-profit: all strategies (research only, no live change)

Question (user): for every strategy (losing, retired, and the profitable ones), what are the win rate and net R with a 1:3 R:R and
(a) a wider stop, (b) a stop beyond the 30-minute candle, (c) a stop beyond the 1-hour candle? Each is compared with the current live rules.

## Variants (entries identical to the live signal functions, the same calls `app/backtest_all` makes)
| Key | Stop | TP |
|-|-|-|
| live | current live rules (FVG/FVG-D1/CHK: 50% at 1.5R then BE; DON20: 3×ATR chandelier, no TP; PAT-TRIPLE 1.5R; MF-REJ next zone; others 3R) | as live |
| cur | current stop | 3R |
| w1.5 / w2 | 1.5× / 2× the current stop distance | 3R of the new stop |
| c30 / c60 | beyond the last **completed** 30m / 1h candle before the fill (long: min(candle low, entry) − 0.1×ATR14 of that timeframe; short mirror). No look-ahead. | 3R |
Crypto candle stops tighter than the live 0.3% minimum are widened to 0.3% ("Floored %"). Same-bar SL+TP counts as SL. Follow window per strategy as in
backtest_all (15m strategies 400×15m bars, 4H patterns 180×4H bars, MF-REJ 240×1H, PAT-TRIPLE 180×4H, DON20 to the end of data). Unresolved trades are marked to market.
Fees as backtest_all (crypto 0.10% round trip, forex 0.02–0.05%), converted to R per trade. $1M 24h-volume floor on crypto. DON20 keeps one position per coin, enforced separately for each variant.

## Data
- Crypto: the cached 30-coin Binance set of `research/fvg_plan_v2/data` (top 30 today, 15m from 2025-08-05, trades from 2025-08-17 to 2026-10-29, about 14.5 months). OOS = from 2026-06-05.
- Forex: Yahoo 1H, 2024-01 → 2026-10 (about 33 months), OOS from 2025-11-27. Variants are simulated on 1H bars. **Yahoo serves 30m candles for the last 60 days only**, so c30 for MF-REJ/PAT-TRIPLE covers just 10/15 signals.

## Results
Full tables: `results.md` (trades, win%, net R, avg R with a 90% bootstrap CI, gross avg, max DD, median stop, floored %, open-at-horizon %, IS/OOS avg).

Key points:
- **30m and 1h candle stops lose for every crypto strategy.** The stops are about 0.35–1.2%, so fees take 0.1–0.3R per trade, and the win rate does not rise to compensate. They're meaningless for DON20 (a daily system with ~20% stops) and for forex (0.04–0.1% stops).
- **Wider stops (2×) help the 15m FVG family and the 4H patterns**, partly because fees in R shrink. "Robust" (net > 0, IS avg > 0, OOS avg > 0): FVG 2× (+59R), FVG+TREND 2× (+82R, 4 of 6 quarters positive), PAT-WEDGE 2× (+18R), and BRK 1.5× (+6R, ≈ break-even). **None is statistically significant** (the 90% CIs include 0).
- FVG-PLAN 2× (+59R) is in-sample only (OOS −0.004R/trade). FVG-D1 loses under every variant. CHK loses under every variant over 14.5 months (live rules −355R; 2× wider −34R).
- DON20: the live rules are best in total (+64R, 315 trades); the 3R versions take fewer trades, and 23–56% were still open at the end (marked to market).
- MF-REJ and PAT-TRIPLE: the live rules (+12.7R, +22.4R) beat every 3R variant.

## Limits
One 2/3 / 1/3 split; 14.5 months of crypto history (survivorship: today's top 30); trades marked to market at the follow horizon (with wider stops more trades are open there, which acts as a time exit); the FVG-family strategies share setups, so they are not independent; forex 30m data covers only 60 days.

## Run
`W=4 python3 bt_crypto.py; W=3 python3 bt_fx.py; python3 report.py` (box only; ~10 min; under ~200 MB per worker). out/ and data/ are git-ignored.

---

# 3-year extension (results3y.md / results3y.json)

Follow-up question: "the backtest should be at least 3 years for all" + "backtest MF-REJ and PAT-TRIPLE in crypto".

## Periods and data
- **Crypto: 2023-10-01 → 2026-10-29 (3.08 years).** Binance bulk 15m klines (data.binance.vision, from 2022-10 for indicator warm-up), `fetch_crypto.py`.
  Universe = today's top 50 USDT pairs by volume (stablecoins / tokenised stocks / PAXG excluded) + BTC/ETH; each coin enters 12 days after its listing
  (no survivorship cut-off). Survivors subset = the 25 coins listed before Oct 2022 (reported on its own line under each table).
- **Forex: 2024-01-24 → 2026-10-30 (2.77 years), 19 pairs, Yahoo 1H** (`FXSRC=yahoo`). XAUUSD/XAUAUD on Yahoo start 2024-06-09.
  Yahoo does not serve 1H older than ~730 days back from the first cache, so **3 full years of forex is not available from Yahoo.**
  Dukascopy (free) has the history, but its server throttles bulk downloads (503 / SSL drops, ~20 s per file at 2 threads), so `fetch_fx.py`
  (Dukascopy BID 1H, 2022-09 → 2026-09, cached per pair-month in data/duka/) was still running at commit time. When it finishes:
  `python3 fetch_fx.py && W=1 python3 bt_fx3y.py && python3 report3y.py` gives the 4-year forex version (writes data/fx3y.pkl).
- Same variants, fees, follow windows and floors as above. Blocks: Y1 = 2023-10-01 → 2024-10-31, Y2 = → 2025-10-31, Y3 = last 12 months; plus a
  first-2/3 vs last-1/3 split and calendar years. ✅ = net R > 0 AND positive in a majority of the Y1–Y3 blocks AND positive in Y3 (last 12 months).

## Crypto ports
- **MF-REJ (crypto):** the live forex signal function unchanged (ATR-based levels), with the session filter disabled
  (`MF_SESSIONS_UTC["24h"]=(0,24)`, every coin mapped to it), live cap of 2 signals/day/pair, stops under the 0.3% crypto floor skipped.
- **PAT-TRIPLE (crypto):** `pat_series("PAT-TRIPLE", h4, "crypto")`, live TP 1.5R.

## Bug found and fixed
The previous run passed `max_age_min=10**6` (≈ 694 days) to the live signal functions, which silently dropped CHK and MF-REJ signals older than that
(the earlier forex MF-REJ result really covered only ~Dec 2024 → Oct 2026, not 33 months). Fixed (`10**8`). Forex MF-REJ and crypto MF-REJ were re-run
(`out3y_fixmf/`, merged by report3y.py). **CHK (retired) was not re-run for time; its 3-year table covers 2024-12-05 → 2026-10-29 only (~23 months).**
It loses under every variant there; re-run with `ONLY=CHK CRYOUT=out3y_fix SIDP=x W=2 python3 bt_crypto3y.py` (~3 min/coin) and merge if needed.

## Run
`python3 fetch_crypto.py; W=2 python3 bt_crypto3y.py; FXSRC=yahoo W=1 python3 bt_fx3y.py; python3 report3y.py` (box only, ~1.5 h at 2 workers;
~0.6 GB per worker). data/, out3y*/, out_fx*/ are git-ignored.
