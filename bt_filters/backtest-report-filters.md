# Filter backtests: forex news filter and crypto low-volume filter (research only, 18 Oct 2026)

Nothing live was changed. The replays use the **live strategy functions** from a snapshot of `app/` taken on 18 Oct 2026 (`backtest_all` code paths: `strategy.analyze_mf`, `patterns_live.pat_series`, `run_crypto`), with the same costs: forex majors 0.02%, crosses and CNH 0.03%, metals 0.05%, crypto 0.10% round trip, all converted to R. Window: **18 Oct 2024 → 17 Oct 2026**. Y1 runs to 17 Oct 2025, Y2 is after that. Scripts and data are in `/workspace/bt_filters/` (fx_gen.py, fx_sim2.py, cr_gen.py, cr_an.py, cr_floor.py).

## 1. Forex news filter

**Calendar source:** ForexFactory's public monthly calendar pages (`forexfactory.com/calendar?month=…`), Sep 2024 → Oct 2026. That gave 10,989 events. I kept the **1,731 timed high-impact ("red") events** for USD, EUR, GBP, JPY, AUD, NZD, CAD, CHF and CNY, and dropped All-Day events. FOMC dates match the Fed's official schedule (2024-09-18, 11-07, 12-18, 2025-01-29 …). The tier-1 subset (682 events) covers only rate decisions, FOMC statements and press conferences, NFP, CPI and GDP. CNH pairs use CNY events. XAU legs use USD events.

**Trades:** FOREX MF-REJ with the current live pair-session map (15 pairs, including GBPCNH and synthetic XAUAUD; 2-per-day cap per pair) and PAT-TRIPLE on PAT_FX (4H signals, path walked on 1H bars). CHK, FVG-D1 and FVG-PLAN do not run on forex live (`EXPERIMENTAL_MARKETS=crypto`), so they were not tested. Entry block = no new entry if a red event for either currency falls within ±W minutes of the entry. "Exit before event" = go flat at the 1H open at least 30 min before the event. "BE" = at that point, move the stop to entry if the trade is in profit.

| Strategy | Variant | n | Win% | Net R | R/trade | Y1 n/win/R | Y2 n/win/R |
|-|-|-|-|-|-|-|-|
|MF-REJ|baseline|123|69.1|+15.80|+0.128|54/63.0%/+3.14|69/73.9%/+12.66|
|MF-REJ|a) block ±30m|118|70.3|+17.23|+0.146|52/63.5%/+3.40|66/75.8%/+13.83|
|MF-REJ|a1) block ±30m, tier-1 only|120|70.8|+19.48|+0.162|53/64.2%/+4.25|67/76.1%/+15.23|
|MF-REJ|b) block ±60m|116|69.8|+15.87|+0.137|50/62.0%/+2.04|66/75.8%/+13.83|
|MF-REJ|c1) ±30m + exit before event|118|70.3|+13.14|+0.111|52/63.5%/−1.37|66/75.8%/+14.51|
|MF-REJ|c2) ±30m + BE before event|118|68.6|+11.52|+0.098|52/59.6%/−2.31|66/75.8%/+13.83|
|PAT-TRIPLE|baseline|125|56.0|+37.69|+0.301|53/52.8%/+13.02|72/58.3%/+24.66|
|PAT-TRIPLE|a) block ±30m|119|54.6|+32.09|+0.270|50/52.0%/+11.27|69/56.5%/+20.82|
|PAT-TRIPLE|a1) tier-1 only|123|55.3|+34.76|+0.283|52/51.9%/+11.54|71/57.7%/+23.21|
|PAT-TRIPLE|b) block ±60m|116|54.3|+30.26|+0.261|50/52.0%/+11.27|66/56.1%/+18.99|
|PAT-TRIPLE|c1) ±30m + exit before event|119|51.3|+15.35|+0.129|50/48.0%/+3.60|69/53.6%/+11.75|
|PAT-TRIPLE|c2) ±30m + BE before event|119|43.7|+15.59|+0.131|50/42.0%/+4.77|69/44.9%/+10.82|
|ALL forex|baseline|248|62.5|+53.49|+0.216|107/57.9%/+16.17|141/66.0%/+37.32|
|ALL forex|a) block ±30m|237|62.4|+49.32|+0.208|102/57.8%/+14.66|135/65.9%/+34.65|
|ALL forex|a1) tier-1 only|243|63.0|+54.24|+0.223|105/58.1%/+15.80|138/66.7%/+38.44|
|ALL forex|b) block ±60m|232|62.1|+46.13|+0.199|100/57.0%/+13.31|132/65.9%/+32.83|
|ALL forex|c1) ±30m + exit before event|237|60.8|+28.49|+0.120|102/55.9%/+2.23|135/64.4%/+26.26|
|ALL forex|c3) ±60m + exit before event|232|60.8|+27.19|+0.117|100/55.0%/+1.80|132/65.2%/+25.39|
|ALL forex|c4) no block, exit only|248|60.5|+28.83|+0.116|107/54.2%/+2.55|141/65.2%/+26.28|

The entry blocks touch very few trades. The ±30 min block removes 11 of 248 trades (MF 5, PAT 6), and those trades were **winners** on average (+0.38R each). The ±60 min block removes 16 trades at +0.46R each. The tier-1 block removes 5 trades at −0.15R each. Exiting or moving to breakeven before events roughly **halves** net R, because it cuts many trades that would have reached TP.

**Recommendation (forex): do not adopt the news filter, and especially not the exit/BE-before-event rule (−25R over 2 years).** The only variant that doesn't hurt is the **tier-1-only ±30 min entry block** (+0.75R total; MF-REJ +3.7R from 3 skipped trades). That difference is noise. If you want it as cheap insurance against rate-decision and NFP spikes, it costs nothing, but there's no evidence for it. Not applying the ±30/±60 block to PAT-TRIPLE is clearly better.

## 2. Crypto low-volume filter

**Data:** 65 coins sampled every 6th rank across the live universe (Binance top 480 by volume, stocks removed; BTC, ETH, BNB … down to ~rank 390), 730 days. Trades come from the live code paths. Volume is Binance 1H quote volume: v24 = the 24h quote volume of the closed 1H bars at signal time, and the 30-day average = 720 bars / 30. Ratio = v24 / 30d average. Trades: 33,232 (CHK 21,469; FVG-PLAN 4,273; BRK 4,552; FVG-D1 1,852; DON20 1,086).

### Relative filter (v24 ≥ X% of own 30d average) and the $5M floor (R/trade, net after costs)

| Strategy | baseline | ≥30% | ≥50% | ≥70% | ≥$5M | ≥50% + $5M | ≥70% + $5M |
|-|-|-|-|-|-|-|-|
|CHK|−0.106 (21,469)|−0.102|−0.087|−0.070|**−0.033** (5,165)|−0.023|−0.004 (2,997)|
|DON20|−0.030 (1,086)|−0.025|−0.033|−0.024|**+0.003** (452)|−0.013|−0.013|
|BRK|−0.030 (4,552)|−0.031|−0.040|−0.055|**−0.001** (1,387)|−0.029|−0.054|
|FVG-D1|−0.121 (1,852)|−0.117|−0.158|−0.187|**−0.090** (603)|−0.131|−0.165|
|FVG-PLAN|−0.113 (4,273)|−0.113|−0.109|−0.096|**−0.094** (1,323)|−0.112|−0.105|
|ALL|−0.095 (33,232), −3,147R|−0.091|−0.085|−0.077|**−0.039** (8,930), −350R|−0.046|−0.043|

Win rates hardly move: ALL is 35.3% at baseline and 36.3% with the $5M floor. The gain comes from fewer losses, which partly reflects the 0.10% cost, since thin coins have smaller moves relative to that cost.

### Absolute floor sweep (ALL live crypto strategies)

| v24 floor | n | kept | Win% | Net R | R/trade | Y1 n/R per trade | Y2 n/R per trade |
|-|-|-|-|-|-|-|-|
|none|33,232|100%|35.3|−3,147|−0.095|13,359/−0.038|19,873/−0.133|
|$1M|19,107|57%|36.5|−799|−0.042|10,992/−0.018|8,115/−0.074|
|$2M|14,232|43%|36.3|−637|−0.045|8,667/−0.023|5,565/−0.078|
|$5M|8,930|27%|36.3|−350|−0.039|5,575/−0.026|3,355/−0.061|
|$10M|6,084|18%|36.1|−307|−0.050|3,689/−0.046|2,395/−0.057|
|$20M|4,066|12%|35.7|−280|−0.069|2,390/−0.067|1,676/−0.071|

Per strategy, the $1M floor gives: CHK −0.106 → −0.032 (better in both years), DON20 −0.030 → −0.017, BRK −0.030 → −0.031, FVG-D1 −0.121 → −0.071, FVG-PLAN −0.113 → −0.090. The $5M floor gives: DON20 +0.003, better in Y1 but slightly worse in Y2. BRK and FVG-D1/FVG-PLAN are better overall but worse in one of the two years.

### Findings
- **The relative (% of own 30-day average) filter doesn't work consistently.** At 70% it helps CHK and FVG-PLAN a little, but hurts FVG-D1 and BRK. By bucket, trades at 30–100% of normal volume do no worse than trades above it. For FVG-D1 and DON20, the busiest bucket (>150%) is among the worst.
- **Absolute liquidity matters.** Trades on coins with under $1M of 24h volume lose −0.19R each on CHK and −0.21R on FVG-D1. That's where most of the loss sits. The median v24 at signal time across the sample is only $1.4M, so many of the 480 live coins are this thin.
- Going from a $1M to a $5M floor adds little: R/trade goes −0.042 → −0.039 while cutting signals from 57% to 27% of baseline. Above $10M it gets worse again.

**Recommendation (crypto): adopt an absolute floor instead of a % rule. Skip signals when the coin's 24h quote volume at signal time is below $1M.** That keeps about 57% of signals and cuts total backtest losses by about 75%. $5M is the stricter option: slightly better per trade but about 73% fewer signals. Combining it with a % rule adds nothing. The real benefit is probably larger than shown, because the backtest charges the same 0.10% cost on thin coins, whose real spread and slippage are worse.

## Caveats
- **Small forex samples:** 123 MF-REJ trades and 125 PAT-TRIPLE trades over 2 years, with only 5–16 trades affected by each block. A ±4R difference is within noise. Treat the forex result as "no evidence the filter helps".
- **Crypto baselines are negative in this replay.** CHK, FVG-D1 and FVG-PLAN lose after costs across a universe that is mostly mid/small caps, which is worse than the older top-coin backtests. Even with the floor, every crypto strategy except DON20 is still slightly negative per trade. The filter reduces losses but doesn't create an edge. The baselines deserve a separate review.
- The coin list is today's universe (survivorship bias). DON20's one-position-per-coin rule isn't re-run after a skip: skipped signals are simply dropped. PAT-TRIPLE paths are walked on 1H instead of 4H. The MF-REJ dynamic strong pair and per-scan caps are not replayed.
- ForexFactory "Tentative" times (some BOJ/RBNZ items) are used as listed.
