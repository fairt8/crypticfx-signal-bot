# Breakout-then-retest and cup & handle backtest (research only, live bot unchanged)

Total resolved trade rows: 235438. Period 2024-10-01 to 2026-09-30. IS = Oct 2024-Sep 2025, OOS = Oct 2025-Sep 2026.


## Verdict (read this first)
- **Retest entries do not beat immediate breakouts overall.** Pooled across all breakout patterns, retest is worse in crypto on both TFs (1H OOS 1:1.5: immediate -0.007R vs retest -0.104/-0.123R; 4H OOS: -0.002 vs -0.032/-0.058R). Win rate barely moves (about 40-42% either way). Waiting for a retest filters out the strongest breakouts, which never come back. Forex 4H is the one spot where retest helps (OOS +0.025R vs -0.105R immediate), but forex overall is still negative.
- **21 of about 250 combos pass** (positive in both halves, n>=50 each). Most crypto passes are tiny (+0.01 to +0.05R per trade), which is within noise after testing this many combos. They are not worth adding to the bot.
- **Most robust candidates (worth paper-trading only):**
  - Wedge breakouts, crypto 4H, retest entry with the level stop, 1:3: IS +0.003R / OOS +0.161R (n 1058/1117). Positive in bull, bear, sideways and both volume regimes.
  - Triple top/bottom, forex 4H, retest with the level stop, 1:1.5: IS 44.8% / +0.042R, OOS 57.5% / +0.332R (n 58/87). Positive in both FX volatility regimes, but the sample is small.
  - Cup & handle, crypto 4H, retest with the swing stop, 1:3: IS +0.191R / OOS +0.198R, but only n=52/61. It loses in bull weeks (n=9), so the edge is thin.
- **Cup & handle with immediate entry fails.** It loses in IS on 1H and 4H and only works in OOS. Forex cups are too rare to judge (under 50 trades).
- **50%+ win rate:** the only combos above 50% in both halves are double and triple tops/bottoms on crypto 4H, immediate entry, measured-move target (57-59% win). That is because the measured move is often shorter than the stop, so expectancy is only +0.01 to +0.07R. Nothing gets 50%+ at 1:1.5 or 1:3 in both halves. Triple forex 4H retest gets 57.5% in OOS but only 44.8% in IS.
- Caveats: survivorship-biased coin list. A bar that hits both stop and target counts as a loss (conservative). Forex has no minimum stop, so very tight 1H FX stops get crushed by costs, which explains the large forex 1H OOS losses. Overlapping signals across patterns are all counted.

## Method
- Data: same as the regime report. Crypto: 44 Binance coins, 1H (resampled from 15m) and 4H. Forex: Yahoo 1H for 7 majors + EURJPY, GBPJPY + XAUUSD, 4H resampled from 1H. Costs per trade 0.1% crypto, 0.02% majors, 0.03% JPY crosses, 0.05% XAU, charged as cost/risk in R. Crypto stops <0.3% dropped.
- Patterns: the existing detector in `app/backtest_patterns.py` (pivots k=3, equal tops within 0.5 ATR) run on each TF: double, triple, flags, ascending/descending triangle, rising/falling wedge, rectangle (= horizontal S/R). H&S excluded (not requested).
- Immediate entry: first close beyond the neckline/trendline within 24 bars; stop = pattern stop (as before).
- Retest entry: after that breakout close, wait up to 10 bars for price to touch the broken level, then enter on the first candle that closes in the breakout direction (green for longs, red for shorts) beyond the level. Cancelled if a close comes back more than 0.5 ATR through the level. Two stops: `retest_swing` = beyond the retest swing extreme +0.1 ATR; `retest_lvl` = level ∓0.5 ATR.
- Cup & handle: K=5 pivots; two rims within 10% of depth, 20-300 bars apart, no higher high inside, bottom in middle half, rounded (>=20% of bars in the lower third of the cup), depth 12-50% crypto (forex adapted to 1.5-10%, since FX never moves 12%), handle 3 bars to half the cup width and retracing < 1/3 of depth. Inverse version mirrored. Entry on rim breakout (immediate) or rim retest, stop below handle low.
- Outcomes on the same TF bars, 400-bar horizon; if one bar hits both stop and target it counts as a loss. Targets 1:1.5, 1:3, measured move (MM, pattern height).
- Regimes: ex-ante weekly labels from the regime report (BTC trend bull/bear/sideways; BTC volume high/low; FX median weekly range high/low ATR).

## PASS list (positive R/trade in IS and OOS, n>=50 each)

| fam      | market   | tf   | entry        | target   |   IS_n |   IS_win |   IS_R |   OOS_n |   OOS_win |   OOS_R | PASS   |
|:---------|:---------|:-----|:-------------|:---------|-------:|---------:|-------:|--------:|----------:|--------:|:-------|
| CUP      | crypto   | 4H   | retest_lvl   | 1:3      |     52 |     26.9 |  0.042 |      61 |      29.5 |   0.135 | True   |
| CUP      | crypto   | 4H   | retest_swing | 1:3      |     52 |     30.8 |  0.191 |      61 |      31.1 |   0.198 | True   |
| DOUBLE   | crypto   | 4H   | immediate    | 1:1.5    |   1579 |     41.3 |  0.019 |    1660 |      41   |   0.007 | True   |
| DOUBLE   | crypto   | 4H   | immediate    | MM       |   1582 |     57.3 |  0.011 |    1672 |      58.6 |   0.031 | True   |
| HORIZ_SR | crypto   | 4H   | immediate    | 1:1.5    |    799 |     40.7 |  0.004 |     881 |      42.8 |   0.054 | True   |
| HORIZ_SR | forex    | 4H   | retest_lvl   | 1:1.5    |     66 |     45.5 |  0.051 |      57 |      47.4 |   0.081 | True   |
| HORIZ_SR | forex    | 4H   | retest_swing | MM       |     66 |     27.3 |  0.15  |      57 |      29.8 |   0.017 | True   |
| TRIANGLE | crypto   | 1H   | immediate    | 1:1.5    |   6237 |     41.6 |  0.006 |    6329 |      43   |   0.034 | True   |
| TRIANGLE | crypto   | 1H   | immediate    | MM       |   6239 |     43.9 |  0.007 |    6334 |      45.8 |   0.027 | True   |
| TRIPLE   | crypto   | 4H   | immediate    | 1:1.5    |    757 |     44.1 |  0.093 |    1018 |      42.5 |   0.05  | True   |
| TRIPLE   | crypto   | 4H   | immediate    | MM       |    762 |     59.1 |  0.066 |    1035 |      58.1 |   0.043 | True   |
| TRIPLE   | forex    | 4H   | retest_lvl   | 1:1.5    |     58 |     44.8 |  0.042 |      87 |      57.5 |   0.332 | True   |
| TRIPLE   | forex    | 4H   | retest_lvl   | 1:3      |     58 |     27.6 |  0.025 |      87 |      32.2 |   0.182 | True   |
| TRIPLE   | forex    | 4H   | retest_lvl   | MM       |     58 |     31   |  0.034 |      87 |      29.9 |   0.071 | True   |
| TRIPLE   | forex    | 4H   | retest_swing | 1:3      |     58 |     29.3 |  0.092 |      87 |      28.7 |   0.041 | True   |
| TRIPLE   | forex    | 4H   | retest_swing | MM       |     58 |     32.8 |  0.235 |      87 |      28.7 |   0.099 | True   |
| WEDGE    | crypto   | 4H   | immediate    | 1:1.5    |   3349 |     43.2 |  0.053 |    3465 |      41.4 |   0.001 | True   |
| WEDGE    | crypto   | 4H   | immediate    | 1:3      |   3331 |     27.2 |  0.06  |    3434 |      26.2 |   0.014 | True   |
| WEDGE    | crypto   | 4H   | immediate    | MM       |   3349 |     35   |  0.072 |    3445 |      35.6 |   0.058 | True   |
| WEDGE    | crypto   | 4H   | retest_lvl   | 1:3      |   1058 |     26   |  0.003 |    1117 |      30.2 |   0.161 | True   |
| WEDGE    | forex    | 4H   | retest_lvl   | MM       |    214 |     27.1 |  0.035 |     232 |      31.9 |   0.16  | True   |

## Headline: immediate vs retest, all breakout patterns pooled

|                                                          |   n 1:1.5 |   win% 1:1.5 |   R/tr 1:1.5 |   n 1:3 |   win% 1:3 |   R/tr 1:3 |   n MM |   win% MM |   R/tr MM |
|:---------------------------------------------------------|----------:|-------------:|-------------:|--------:|-----------:|-----------:|-------:|----------:|----------:|
| ('CUP', 'crypto', '1H', 'immediate', 'IS')               |       371 |         38   |       -0.073 |     358 |       21.2 |     -0.174 |    359 |      18.4 |    -0.207 |
| ('CUP', 'crypto', '1H', 'immediate', 'OOS')              |       188 |         43.6 |        0.065 |     179 |       29.6 |      0.159 |    170 |      22.4 |     0.008 |
| ('CUP', 'crypto', '1H', 'retest_lvl', 'IS')              |       169 |         27.8 |       -0.369 |     169 |       18.9 |     -0.307 |    169 |       6.5 |    -0.267 |
| ('CUP', 'crypto', '1H', 'retest_lvl', 'OOS')             |       102 |         41.2 |       -0.037 |     102 |       27.5 |      0.032 |    100 |      12   |     0.129 |
| ('CUP', 'crypto', '1H', 'retest_swing', 'IS')            |       169 |         33.7 |       -0.224 |     169 |       18.3 |     -0.333 |    169 |       5.9 |    -0.399 |
| ('CUP', 'crypto', '1H', 'retest_swing', 'OOS')           |       102 |         40.2 |       -0.069 |     102 |       30.4 |      0.142 |    100 |      11   |    -0.007 |
| ('CUP', 'crypto', '4H', 'immediate', 'IS')               |       101 |         34.7 |       -0.146 |     100 |       17   |     -0.333 |    100 |      18   |    -0.284 |
| ('CUP', 'crypto', '4H', 'immediate', 'OOS')              |       105 |         51.4 |        0.27  |      99 |       34.3 |      0.358 |     98 |      32.7 |     0.31  |
| ('CUP', 'crypto', '4H', 'retest_lvl', 'IS')              |        52 |         44.2 |        0.071 |      52 |       26.9 |      0.042 |     52 |      11.5 |    -0.396 |
| ('CUP', 'crypto', '4H', 'retest_lvl', 'OOS')             |        61 |         41   |       -0.021 |      61 |       29.5 |      0.135 |     60 |      15   |     0.191 |
| ('CUP', 'crypto', '4H', 'retest_swing', 'IS')            |        52 |         46.2 |        0.114 |      52 |       30.8 |      0.191 |     52 |      11.5 |    -0.388 |
| ('CUP', 'crypto', '4H', 'retest_swing', 'OOS')           |        61 |         41   |       -0.023 |      61 |       31.1 |      0.198 |     60 |      15   |     0.315 |
| ('CUP', 'forex', '1H', 'immediate', 'IS')                |        41 |         31.7 |       -0.254 |      40 |       20   |     -0.248 |     39 |      15.4 |    -0.401 |
| ('CUP', 'forex', '1H', 'immediate', 'OOS')               |        17 |         23.5 |       -0.461 |      17 |       11.8 |     -0.578 |     17 |      11.8 |    -0.405 |
| ('CUP', 'forex', '1H', 'retest_lvl', 'IS')               |        20 |         45   |       -0.006 |      20 |       45   |      0.669 |     19 |      21.1 |     0.798 |
| ('CUP', 'forex', '1H', 'retest_lvl', 'OOS')              |         8 |         37.5 |       -0.228 |       8 |       12.5 |     -0.666 |      8 |       0   |    -1.166 |
| ('CUP', 'forex', '1H', 'retest_swing', 'IS')             |        20 |         40   |       -0.164 |      20 |       35   |      0.236 |     20 |      15   |     0.581 |
| ('CUP', 'forex', '1H', 'retest_swing', 'OOS')            |         8 |         50   |        0.109 |       8 |       25   |     -0.141 |      8 |      12.5 |     1.076 |
| ('CUP', 'forex', '4H', 'immediate', 'IS')                |        24 |         45.8 |        0.115 |      22 |       18.2 |     -0.305 |     22 |      18.2 |    -0.169 |
| ('CUP', 'forex', '4H', 'immediate', 'OOS')               |        14 |         50   |        0.216 |      14 |       35.7 |      0.395 |     12 |      25   |     0.273 |
| ('CUP', 'forex', '4H', 'retest_lvl', 'IS')               |        10 |         60   |        0.402 |      10 |       30   |      0.102 |     10 |       0   |    -1.098 |
| ('CUP', 'forex', '4H', 'retest_lvl', 'OOS')              |         9 |         33.3 |       -0.267 |       9 |       33.3 |      0.233 |      9 |      22.2 |     0.594 |
| ('CUP', 'forex', '4H', 'retest_swing', 'IS')             |        10 |         60   |        0.401 |      10 |       30   |      0.101 |     10 |       0   |    -1.099 |
| ('CUP', 'forex', '4H', 'retest_swing', 'OOS')            |         9 |         33.3 |       -0.255 |       9 |       33.3 |      0.245 |      9 |      22.2 |     0.518 |
| ('breakout pats', 'crypto', '1H', 'immediate', 'IS')     |     43106 |         40.4 |       -0.03  |   42570 |       25   |     -0.041 |  43161 |      43.1 |    -0.028 |
| ('breakout pats', 'crypto', '1H', 'immediate', 'OOS')    |     45180 |         41.7 |       -0.007 |   44220 |       25.9 |     -0.013 |  45332 |      44.4 |     0.005 |
| ('breakout pats', 'crypto', '1H', 'retest_lvl', 'IS')    |     18740 |         41.4 |       -0.047 |   18728 |       26.1 |     -0.037 |  18738 |      27.2 |    -0.009 |
| ('breakout pats', 'crypto', '1H', 'retest_lvl', 'OOS')   |     19153 |         39.7 |       -0.104 |   19129 |       25   |     -0.098 |  19147 |      26.8 |    -0.089 |
| ('breakout pats', 'crypto', '1H', 'retest_swing', 'IS')  |     18633 |         41.1 |       -0.061 |   18620 |       26.1 |     -0.046 |  18627 |      25.5 |    -0.02  |
| ('breakout pats', 'crypto', '1H', 'retest_swing', 'OOS') |     18985 |         39.4 |       -0.123 |   18958 |       25.2 |     -0.099 |  18984 |      25.7 |    -0.091 |
| ('breakout pats', 'crypto', '4H', 'immediate', 'IS')     |      9524 |         41.7 |        0.022 |    9326 |       24.8 |     -0.028 |   9529 |      42.3 |     0.007 |
| ('breakout pats', 'crypto', '4H', 'immediate', 'OOS')    |     10411 |         40.9 |       -0.002 |   10112 |       25.1 |     -0.021 |  10417 |      43.9 |     0.021 |
| ('breakout pats', 'crypto', '4H', 'retest_lvl', 'IS')    |      4055 |         42.2 |        0.015 |    4053 |       25.7 |     -0.014 |   4055 |      25.2 |    -0.044 |
| ('breakout pats', 'crypto', '4H', 'retest_lvl', 'OOS')   |      4436 |         40.7 |       -0.032 |    4421 |       25.1 |     -0.045 |   4429 |      25   |    -0.069 |
| ('breakout pats', 'crypto', '4H', 'retest_swing', 'IS')  |      4052 |         41.9 |        0.001 |    4052 |       26.5 |      0.014 |   4052 |      23.7 |    -0.025 |
| ('breakout pats', 'crypto', '4H', 'retest_swing', 'OOS') |      4435 |         39.9 |       -0.058 |    4423 |       24.6 |     -0.072 |   4431 |      23.1 |    -0.11  |
| ('breakout pats', 'forex', '1H', 'immediate', 'IS')      |      6798 |         39.6 |       -0.156 |    6688 |       24.6 |     -0.164 |   6812 |      41.3 |    -0.106 |
| ('breakout pats', 'forex', '1H', 'immediate', 'OOS')     |      7233 |         39.7 |       -0.519 |    7111 |       24.9 |     -0.523 |   7243 |      40.9 |    -0.509 |
| ('breakout pats', 'forex', '1H', 'retest_lvl', 'IS')     |      2893 |         39   |       -0.19  |    2891 |       25   |     -0.163 |   2893 |      25.5 |    -0.187 |
| ('breakout pats', 'forex', '1H', 'retest_lvl', 'OOS')    |      2969 |         37   |       -0.287 |    2967 |       23.4 |     -0.276 |   2969 |      24   |    -0.27  |
| ('breakout pats', 'forex', '1H', 'retest_swing', 'IS')   |      2893 |         38.2 |       -0.228 |    2890 |       24.9 |     -0.187 |   2893 |      25.1 |    -0.17  |
| ('breakout pats', 'forex', '1H', 'retest_swing', 'OOS')  |      2969 |         36.4 |       -0.33  |    2967 |       22.5 |     -0.337 |   2969 |      22.4 |    -0.299 |
| ('breakout pats', 'forex', '4H', 'immediate', 'IS')      |      1781 |         36.6 |       -0.564 |    1727 |       21.3 |     -0.643 |   1790 |      39   |    -0.544 |
| ('breakout pats', 'forex', '4H', 'immediate', 'OOS')     |      1679 |         38.6 |       -0.105 |    1628 |       25.7 |     -0.045 |   1675 |      42.1 |    -0.065 |
| ('breakout pats', 'forex', '4H', 'retest_lvl', 'IS')     |       713 |         40.4 |       -0.072 |     713 |       26.2 |     -0.033 |    713 |      27.6 |     0.051 |
| ('breakout pats', 'forex', '4H', 'retest_lvl', 'OOS')    |       745 |         45.1 |        0.025 |     740 |       27.4 |     -0.005 |    741 |      27   |    -0.052 |
| ('breakout pats', 'forex', '4H', 'retest_swing', 'IS')   |       713 |         40.4 |       -0.084 |     713 |       26.2 |     -0.044 |    713 |      26.2 |     0.051 |
| ('breakout pats', 'forex', '4H', 'retest_swing', 'OOS')  |       745 |         43.9 |       -0.017 |     745 |       26.7 |     -0.046 |    744 |      25   |    -0.058 |

## Family x market x TF x entry, IS vs OOS

| fam      | market   | tf   | entry        | target   |   IS_n |   IS_win |   IS_R |   OOS_n |   OOS_win |   OOS_R | PASS   |
|:---------|:---------|:-----|:-------------|:---------|-------:|---------:|-------:|--------:|----------:|--------:|:-------|
| CUP      | crypto   | 1H   | immediate    | 1:1.5    |    371 |     38   | -0.073 |     188 |      43.6 |   0.065 | False  |
| CUP      | crypto   | 1H   | immediate    | 1:3      |    358 |     21.2 | -0.174 |     179 |      29.6 |   0.159 | False  |
| CUP      | crypto   | 1H   | immediate    | MM       |    359 |     18.4 | -0.207 |     170 |      22.4 |   0.008 | False  |
| CUP      | crypto   | 1H   | retest_lvl   | 1:1.5    |    169 |     27.8 | -0.369 |     102 |      41.2 |  -0.037 | False  |
| CUP      | crypto   | 1H   | retest_lvl   | 1:3      |    169 |     18.9 | -0.307 |     102 |      27.5 |   0.032 | False  |
| CUP      | crypto   | 1H   | retest_lvl   | MM       |    169 |      6.5 | -0.267 |     100 |      12   |   0.129 | False  |
| CUP      | crypto   | 1H   | retest_swing | 1:1.5    |    169 |     33.7 | -0.224 |     102 |      40.2 |  -0.069 | False  |
| CUP      | crypto   | 1H   | retest_swing | 1:3      |    169 |     18.3 | -0.333 |     102 |      30.4 |   0.142 | False  |
| CUP      | crypto   | 1H   | retest_swing | MM       |    169 |      5.9 | -0.399 |     100 |      11   |  -0.007 | False  |
| CUP      | crypto   | 4H   | immediate    | 1:1.5    |    101 |     34.7 | -0.146 |     105 |      51.4 |   0.27  | False  |
| CUP      | crypto   | 4H   | immediate    | 1:3      |    100 |     17   | -0.333 |      99 |      34.3 |   0.358 | False  |
| CUP      | crypto   | 4H   | immediate    | MM       |    100 |     18   | -0.284 |      98 |      32.7 |   0.31  | False  |
| CUP      | crypto   | 4H   | retest_lvl   | 1:1.5    |     52 |     44.2 |  0.071 |      61 |      41   |  -0.021 | False  |
| CUP      | crypto   | 4H   | retest_lvl   | 1:3      |     52 |     26.9 |  0.042 |      61 |      29.5 |   0.135 | True   |
| CUP      | crypto   | 4H   | retest_lvl   | MM       |     52 |     11.5 | -0.396 |      60 |      15   |   0.191 | False  |
| CUP      | crypto   | 4H   | retest_swing | 1:1.5    |     52 |     46.2 |  0.114 |      61 |      41   |  -0.023 | False  |
| CUP      | crypto   | 4H   | retest_swing | 1:3      |     52 |     30.8 |  0.191 |      61 |      31.1 |   0.198 | True   |
| CUP      | crypto   | 4H   | retest_swing | MM       |     52 |     11.5 | -0.388 |      60 |      15   |   0.315 | False  |
| CUP      | forex    | 1H   | immediate    | 1:1.5    |     41 |     31.7 | -0.254 |      17 |      23.5 |  -0.461 | False  |
| CUP      | forex    | 1H   | immediate    | 1:3      |     40 |     20   | -0.248 |      17 |      11.8 |  -0.578 | False  |
| CUP      | forex    | 1H   | immediate    | MM       |     39 |     15.4 | -0.401 |      17 |      11.8 |  -0.405 | False  |
| CUP      | forex    | 1H   | retest_lvl   | 1:1.5    |     20 |     45   | -0.006 |       8 |      37.5 |  -0.228 | False  |
| CUP      | forex    | 1H   | retest_lvl   | 1:3      |     20 |     45   |  0.669 |       8 |      12.5 |  -0.666 | False  |
| CUP      | forex    | 1H   | retest_lvl   | MM       |     19 |     21.1 |  0.798 |       8 |       0   |  -1.166 | False  |
| CUP      | forex    | 1H   | retest_swing | 1:1.5    |     20 |     40   | -0.164 |       8 |      50   |   0.109 | False  |
| CUP      | forex    | 1H   | retest_swing | 1:3      |     20 |     35   |  0.236 |       8 |      25   |  -0.141 | False  |
| CUP      | forex    | 1H   | retest_swing | MM       |     20 |     15   |  0.581 |       8 |      12.5 |   1.076 | False  |
| CUP      | forex    | 4H   | immediate    | 1:1.5    |     24 |     45.8 |  0.115 |      14 |      50   |   0.216 | False  |
| CUP      | forex    | 4H   | immediate    | 1:3      |     22 |     18.2 | -0.305 |      14 |      35.7 |   0.395 | False  |
| CUP      | forex    | 4H   | immediate    | MM       |     22 |     18.2 | -0.169 |      12 |      25   |   0.273 | False  |
| CUP      | forex    | 4H   | retest_lvl   | 1:1.5    |     10 |     60   |  0.402 |       9 |      33.3 |  -0.267 | False  |
| CUP      | forex    | 4H   | retest_lvl   | 1:3      |     10 |     30   |  0.102 |       9 |      33.3 |   0.233 | False  |
| CUP      | forex    | 4H   | retest_lvl   | MM       |     10 |      0   | -1.098 |       9 |      22.2 |   0.594 | False  |
| CUP      | forex    | 4H   | retest_swing | 1:1.5    |     10 |     60   |  0.401 |       9 |      33.3 |  -0.255 | False  |
| CUP      | forex    | 4H   | retest_swing | 1:3      |     10 |     30   |  0.101 |       9 |      33.3 |   0.245 | False  |
| CUP      | forex    | 4H   | retest_swing | MM       |     10 |      0   | -1.099 |       9 |      22.2 |   0.518 | False  |
| DOUBLE   | crypto   | 1H   | immediate    | 1:1.5    |   7129 |     39.7 | -0.035 |    7312 |      41.6 |   0.004 | False  |
| DOUBLE   | crypto   | 1H   | immediate    | 1:3      |   6990 |     24.1 | -0.066 |    7051 |      25.6 |  -0.014 | False  |
| DOUBLE   | crypto   | 1H   | immediate    | MM       |   7156 |     56.5 | -0.022 |    7373 |      58.4 |  -0.004 | False  |
| DOUBLE   | crypto   | 1H   | retest_lvl   | 1:1.5    |   3402 |     43.2 | -0.006 |    3354 |      39.6 |  -0.111 | False  |
| DOUBLE   | crypto   | 1H   | retest_lvl   | 1:3      |   3399 |     26.5 | -0.025 |    3351 |      24.9 |  -0.103 | False  |
| DOUBLE   | crypto   | 1H   | retest_lvl   | MM       |   3402 |     31.9 | -0.005 |    3355 |      31.7 |  -0.109 | False  |
| DOUBLE   | crypto   | 1H   | retest_swing | 1:1.5    |   3385 |     42.9 | -0.019 |    3327 |      38.8 |  -0.138 | False  |
| DOUBLE   | crypto   | 1H   | retest_swing | 1:3      |   3382 |     26.5 | -0.032 |    3322 |      25.2 |  -0.101 | False  |
| DOUBLE   | crypto   | 1H   | retest_swing | MM       |   3385 |     30.4 | -0.015 |    3328 |      30.6 |  -0.114 | False  |
| DOUBLE   | crypto   | 4H   | immediate    | 1:1.5    |   1579 |     41.3 |  0.019 |    1660 |      41   |   0.007 | True   |
| DOUBLE   | crypto   | 4H   | immediate    | 1:3      |   1532 |     24.2 | -0.045 |    1587 |      24.4 |  -0.042 | False  |
| DOUBLE   | crypto   | 4H   | immediate    | MM       |   1582 |     57.3 |  0.011 |    1672 |      58.6 |   0.031 | True   |
| DOUBLE   | crypto   | 4H   | retest_lvl   | 1:1.5    |    720 |     41.5 | -0.003 |     789 |      40.4 |  -0.041 | False  |
| DOUBLE   | crypto   | 4H   | retest_lvl   | 1:3      |    720 |     25.7 | -0.013 |     787 |      23.8 |  -0.101 | False  |
| DOUBLE   | crypto   | 4H   | retest_lvl   | MM       |    720 |     30.8 | -0.022 |     788 |      27.8 |  -0.136 | False  |
| DOUBLE   | crypto   | 4H   | retest_swing | 1:1.5    |    720 |     41.2 | -0.015 |     790 |      38.6 |  -0.091 | False  |
| DOUBLE   | crypto   | 4H   | retest_swing | 1:3      |    720 |     27.2 |  0.042 |     787 |      22.6 |  -0.151 | False  |
| DOUBLE   | crypto   | 4H   | retest_swing | MM       |    720 |     29.7 |  0.016 |     789 |      26.6 |  -0.154 | False  |
| DOUBLE   | forex    | 1H   | immediate    | 1:1.5    |   1060 |     39.4 | -0.068 |    1154 |      41.2 |  -0.037 | False  |
| DOUBLE   | forex    | 1H   | immediate    | 1:3      |   1031 |     22.4 | -0.158 |    1120 |      26.1 |  -0.026 | False  |
| DOUBLE   | forex    | 1H   | immediate    | MM       |   1065 |     57.1 | -0.046 |    1160 |      57.5 |  -0.044 | False  |
| DOUBLE   | forex    | 1H   | retest_lvl   | 1:1.5    |    539 |     39.7 | -0.173 |     537 |      37.6 |  -0.269 | False  |
| DOUBLE   | forex    | 1H   | retest_lvl   | 1:3      |    538 |     26.6 | -0.103 |     536 |      24.1 |  -0.247 | False  |
| DOUBLE   | forex    | 1H   | retest_lvl   | MM       |    539 |     32.5 | -0.124 |     537 |      29.8 |  -0.265 | False  |
| DOUBLE   | forex    | 1H   | retest_swing | 1:1.5    |    539 |     39.7 | -0.183 |     537 |      36.3 |  -0.319 | False  |
| DOUBLE   | forex    | 1H   | retest_swing | 1:3      |    537 |     26.8 | -0.104 |     536 |      21.3 |  -0.377 | False  |
| DOUBLE   | forex    | 1H   | retest_swing | MM       |    539 |     32.5 | -0.106 |     537 |      27.6 |  -0.341 | False  |
| DOUBLE   | forex    | 4H   | immediate    | 1:1.5    |    281 |     32.4 | -0.215 |     265 |      46.4 |   0.129 | False  |
| DOUBLE   | forex    | 4H   | immediate    | 1:3      |    267 |     19.1 | -0.261 |     252 |      32.1 |   0.254 | False  |
| DOUBLE   | forex    | 4H   | immediate    | MM       |    283 |     53.4 | -0.085 |     265 |      62.3 |   0.076 | False  |
| DOUBLE   | forex    | 4H   | retest_lvl   | 1:1.5    |    122 |     38.5 | -0.127 |     129 |      44.2 |  -0.007 | False  |
| DOUBLE   | forex    | 4H   | retest_lvl   | 1:3      |    122 |     24.6 | -0.107 |     129 |      28.7 |   0.035 | False  |
| DOUBLE   | forex    | 4H   | retest_lvl   | MM       |    122 |     30.3 | -0.037 |     129 |      31.8 |   0.009 | False  |
| DOUBLE   | forex    | 4H   | retest_swing | 1:1.5    |    122 |     36.1 | -0.199 |     129 |      48.8 |   0.103 | False  |
| DOUBLE   | forex    | 4H   | retest_swing | 1:3      |    122 |     19.7 | -0.313 |     129 |      31   |   0.122 | False  |
| DOUBLE   | forex    | 4H   | retest_swing | MM       |    122 |     27   | -0.198 |     129 |      34.1 |   0.138 | False  |
| FLAG     | crypto   | 1H   | immediate    | 1:1.5    |   6654 |     40.5 | -0.027 |    8287 |      40.2 |  -0.047 | False  |
| FLAG     | crypto   | 1H   | immediate    | 1:3      |   6623 |     25.8 | -0.01  |    8229 |      25.4 |  -0.035 | False  |
| FLAG     | crypto   | 1H   | immediate    | MM       |   6643 |     33.1 | -0.024 |    8274 |      33   |  -0.03  | False  |
| FLAG     | crypto   | 1H   | retest_lvl   | 1:1.5    |   3368 |     39.9 | -0.086 |    4132 |      37.2 |  -0.171 | False  |
| FLAG     | crypto   | 1H   | retest_lvl   | 1:3      |   3363 |     25.6 | -0.059 |    4131 |      22.1 |  -0.215 | False  |
| FLAG     | crypto   | 1H   | retest_lvl   | MM       |   3366 |     21.5 |  0.008 |    4129 |      17.9 |  -0.204 | False  |
| FLAG     | crypto   | 1H   | retest_swing | 1:1.5    |   3352 |     39.3 | -0.106 |    4104 |      36.2 |  -0.204 | False  |
| FLAG     | crypto   | 1H   | retest_swing | 1:3      |   3346 |     25.8 | -0.058 |    4098 |      21.8 |  -0.236 | False  |
| FLAG     | crypto   | 1H   | retest_swing | MM       |   3346 |     20.6 | -0     |    4101 |      17.1 |  -0.237 | False  |
| FLAG     | crypto   | 4H   | immediate    | 1:1.5    |   1642 |     38.7 | -0.053 |    1858 |      39.3 |  -0.042 | False  |
| FLAG     | crypto   | 4H   | immediate    | 1:3      |   1632 |     23.2 | -0.094 |    1822 |      23.2 |  -0.097 | False  |
| FLAG     | crypto   | 4H   | immediate    | MM       |   1642 |     30.3 | -0.099 |    1845 |      32.6 |  -0.014 | False  |
| FLAG     | crypto   | 4H   | retest_lvl   | 1:1.5    |    837 |     45.5 |  0.095 |     957 |      38.5 |  -0.093 | False  |
| FLAG     | crypto   | 4H   | retest_lvl   | 1:3      |    837 |     25.9 | -0.006 |     956 |      24.7 |  -0.067 | False  |
| FLAG     | crypto   | 4H   | retest_lvl   | MM       |    837 |     18.9 | -0.072 |     957 |      17.5 |  -0.106 | False  |
| FLAG     | crypto   | 4H   | retest_swing | 1:1.5    |    836 |     44   |  0.054 |     955 |      39   |  -0.086 | False  |
| FLAG     | crypto   | 4H   | retest_swing | 1:3      |    836 |     26.2 |  0.001 |     954 |      23.8 |  -0.109 | False  |
| FLAG     | crypto   | 4H   | retest_swing | MM       |    836 |     17.6 | -0.026 |     956 |      16.6 |  -0.113 | False  |
| FLAG     | forex    | 1H   | immediate    | 1:1.5    |   1400 |     42.2 | -0.031 |    1344 |      39.1 |  -0.124 | False  |
| FLAG     | forex    | 1H   | immediate    | 1:3      |   1390 |     28.9 |  0.07  |    1336 |      24.6 |  -0.116 | False  |
| FLAG     | forex    | 1H   | immediate    | MM       |   1397 |     35.1 |  0.049 |    1340 |      30.6 |  -0.135 | False  |
| FLAG     | forex    | 1H   | retest_lvl   | 1:1.5    |    656 |     41.2 | -0.14  |     600 |      36.3 |  -0.32  | False  |
| FLAG     | forex    | 1H   | retest_lvl   | 1:3      |    656 |     25.9 | -0.133 |     600 |      21.8 |  -0.355 | False  |
| FLAG     | forex    | 1H   | retest_lvl   | MM       |    656 |     21.8 | -0.102 |     600 |      16.2 |  -0.296 | False  |
| FLAG     | forex    | 1H   | retest_swing | 1:1.5    |    656 |     40.2 | -0.174 |     600 |      35   |  -0.372 | False  |
| FLAG     | forex    | 1H   | retest_swing | 1:3      |    656 |     26.8 | -0.107 |     600 |      23.2 |  -0.32  | False  |
| FLAG     | forex    | 1H   | retest_swing | MM       |    656 |     22.3 | -0.066 |     600 |      16.3 |  -0.303 | False  |
| FLAG     | forex    | 4H   | immediate    | 1:1.5    |    258 |     46.1 |  0.115 |     258 |      32.9 |  -0.222 | False  |
| FLAG     | forex    | 4H   | immediate    | 1:3      |    258 |     27.9 |  0.078 |     254 |      18.5 |  -0.306 | False  |
| FLAG     | forex    | 4H   | immediate    | MM       |    258 |     37.2 |  0.093 |     257 |      25.7 |  -0.295 | False  |
| FLAG     | forex    | 4H   | retest_lvl   | 1:1.5    |    124 |     35.5 | -0.202 |     133 |      38.3 |  -0.142 | False  |
| FLAG     | forex    | 4H   | retest_lvl   | 1:3      |    124 |     25   | -0.089 |     131 |      17.6 |  -0.399 | False  |
| FLAG     | forex    | 4H   | retest_lvl   | MM       |    124 |     22.6 |  0.216 |     131 |      11.5 |  -0.536 | False  |
| FLAG     | forex    | 4H   | retest_swing | 1:1.5    |    124 |     41.9 | -0.049 |     133 |      38.3 |  -0.148 | False  |
| FLAG     | forex    | 4H   | retest_swing | 1:3      |    124 |     32.3 |  0.193 |     133 |      19.5 |  -0.325 | False  |
| FLAG     | forex    | 4H   | retest_swing | MM       |    124 |     23.4 |  0.404 |     133 |      11.3 |  -0.558 | False  |
| HORIZ_SR | crypto   | 1H   | immediate    | 1:1.5    |   4055 |     39.6 | -0.039 |    4073 |      42.4 |   0.024 | False  |
| HORIZ_SR | crypto   | 1H   | immediate    | 1:3      |   3995 |     23.8 | -0.077 |    3949 |      25   |  -0.035 | False  |
| HORIZ_SR | crypto   | 1H   | immediate    | MM       |   4074 |     56.8 | -0.003 |    4109 |      58.3 |   0.01  | False  |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | 1:1.5    |   1994 |     43   | -0.007 |    1908 |      41.1 |  -0.069 | False  |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | 1:3      |   1993 |     26   | -0.041 |    1905 |      25.9 |  -0.061 | False  |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | MM       |   1994 |     31.3 |  0.021 |    1908 |      32.5 |  -0.061 | False  |
| HORIZ_SR | crypto   | 1H   | retest_swing | 1:1.5    |   1985 |     44.4 |  0.019 |    1891 |      40.9 |  -0.082 | False  |
| HORIZ_SR | crypto   | 1H   | retest_swing | 1:3      |   1984 |     27.5 |  0.011 |    1888 |      27.3 |  -0.014 | False  |
| HORIZ_SR | crypto   | 1H   | retest_swing | MM       |   1985 |     30.6 |  0.039 |    1891 |      32.5 |  -0.023 | False  |
| HORIZ_SR | crypto   | 4H   | immediate    | 1:1.5    |    799 |     40.7 |  0.004 |     881 |      42.8 |   0.054 | True   |
| HORIZ_SR | crypto   | 4H   | immediate    | 1:3      |    770 |     21.7 | -0.145 |     832 |      26.6 |   0.046 | False  |
| HORIZ_SR | crypto   | 4H   | immediate    | MM       |    799 |     54.3 | -0.03  |     887 |      59   |   0.049 | False  |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | 1:1.5    |    420 |     39.8 | -0.048 |     414 |      39.1 |  -0.072 | False  |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | 1:3      |    420 |     21.9 | -0.166 |     412 |      21.1 |  -0.206 | False  |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | MM       |    420 |     25.7 | -0.153 |     414 |      27.1 |  -0.182 | False  |
| HORIZ_SR | crypto   | 4H   | retest_swing | 1:1.5    |    420 |     40   | -0.046 |     413 |      38.3 |  -0.099 | False  |
| HORIZ_SR | crypto   | 4H   | retest_swing | 1:3      |    420 |     26.4 |  0.012 |     412 |      24   |  -0.095 | False  |
| HORIZ_SR | crypto   | 4H   | retest_swing | MM       |    420 |     25.5 | -0.149 |     413 |      24   |  -0.264 | False  |
| HORIZ_SR | forex    | 1H   | immediate    | 1:1.5    |    503 |     37.4 | -0.124 |     638 |      38.6 |  -0.111 | False  |
| HORIZ_SR | forex    | 1H   | immediate    | 1:3      |    492 |     22.4 | -0.165 |     620 |      26.1 |  -0.031 | False  |
| HORIZ_SR | forex    | 1H   | immediate    | MM       |    506 |     53   | -0.106 |     643 |      54   |  -0.097 | False  |
| HORIZ_SR | forex    | 1H   | retest_lvl   | 1:1.5    |    272 |     34.9 | -0.299 |     295 |      33.9 |  -0.372 | False  |
| HORIZ_SR | forex    | 1H   | retest_lvl   | 1:3      |    272 |     22.1 | -0.29  |     294 |      22.1 |  -0.336 | False  |
| HORIZ_SR | forex    | 1H   | retest_lvl   | MM       |    272 |     24.3 | -0.386 |     295 |      26.8 |  -0.346 | False  |
| HORIZ_SR | forex    | 1H   | retest_swing | 1:1.5    |    272 |     33.5 | -0.343 |     295 |      34.2 |  -0.382 | False  |
| HORIZ_SR | forex    | 1H   | retest_swing | 1:3      |    272 |     18.8 | -0.43  |     294 |      18.7 |  -0.49  | False  |
| HORIZ_SR | forex    | 1H   | retest_swing | MM       |    272 |     24.6 | -0.347 |     295 |      24.4 |  -0.417 | False  |
| HORIZ_SR | forex    | 4H   | immediate    | 1:1.5    |    161 |     31.7 | -0.233 |     127 |      36.2 |  -0.124 | False  |
| HORIZ_SR | forex    | 4H   | immediate    | 1:3      |    154 |     22.1 | -0.143 |     120 |      24.2 |  -0.063 | False  |
| HORIZ_SR | forex    | 4H   | immediate    | MM       |    163 |     49.1 | -0.139 |     127 |      52   |  -0.083 | False  |
| HORIZ_SR | forex    | 4H   | retest_lvl   | 1:1.5    |     66 |     45.5 |  0.051 |      57 |      47.4 |   0.081 | True   |
| HORIZ_SR | forex    | 4H   | retest_lvl   | 1:3      |     66 |     33.3 |  0.248 |      56 |      23.2 |  -0.176 | False  |
| HORIZ_SR | forex    | 4H   | retest_lvl   | MM       |     66 |     33.3 |  0.046 |      57 |      29.8 |  -0.014 | False  |
| HORIZ_SR | forex    | 4H   | retest_swing | 1:1.5    |     66 |     40.9 | -0.081 |      57 |      47.4 |   0.075 | False  |
| HORIZ_SR | forex    | 4H   | retest_swing | 1:3      |     66 |     25.8 | -0.074 |      57 |      26.3 |  -0.057 | False  |
| HORIZ_SR | forex    | 4H   | retest_swing | MM       |     66 |     27.3 |  0.15  |      57 |      29.8 |   0.017 | True   |
| TRIANGLE | crypto   | 1H   | immediate    | 1:1.5    |   6237 |     41.6 |  0.006 |    6329 |      43   |   0.034 | True   |
| TRIANGLE | crypto   | 1H   | immediate    | 1:3      |   6158 |     25.8 | -0     |    6202 |      26.5 |   0.019 | False  |
| TRIANGLE | crypto   | 1H   | immediate    | MM       |   6239 |     43.9 |  0.007 |    6334 |      45.8 |   0.027 | True   |
| TRIANGLE | crypto   | 1H   | retest_lvl   | 1:1.5    |   2985 |     41.8 | -0.04  |    2973 |      39.8 |  -0.106 | False  |
| TRIANGLE | crypto   | 1H   | retest_lvl   | 1:3      |   2983 |     27.4 |  0.011 |    2970 |      24.7 |  -0.113 | False  |
| TRIANGLE | crypto   | 1H   | retest_lvl   | MM       |   2985 |     23.9 |  0     |    2973 |      24   |  -0.077 | False  |
| TRIANGLE | crypto   | 1H   | retest_swing | 1:1.5    |   2977 |     41.4 | -0.058 |    2951 |      40.4 |  -0.097 | False  |
| TRIANGLE | crypto   | 1H   | retest_swing | 1:3      |   2975 |     27   | -0.011 |    2944 |      25.1 |  -0.104 | False  |
| TRIANGLE | crypto   | 1H   | retest_swing | MM       |   2977 |     22.5 | -0.025 |    2952 |      23.5 |  -0.072 | False  |
| TRIANGLE | crypto   | 4H   | immediate    | 1:1.5    |   1398 |     41   |  0.01  |    1529 |      39.4 |  -0.034 | False  |
| TRIANGLE | crypto   | 4H   | immediate    | 1:3      |   1353 |     24   | -0.054 |    1484 |      24.5 |  -0.037 | False  |
| TRIANGLE | crypto   | 4H   | immediate    | MM       |   1395 |     41.1 | -0.043 |    1533 |      41.6 |  -0.058 | False  |
| TRIANGLE | crypto   | 4H   | retest_lvl   | 1:1.5    |    656 |     45.3 |  0.09  |     703 |      38.5 |  -0.087 | False  |
| TRIANGLE | crypto   | 4H   | retest_lvl   | 1:3      |    654 |     25.8 | -0.009 |     698 |      23.1 |  -0.129 | False  |
| TRIANGLE | crypto   | 4H   | retest_lvl   | MM       |    656 |     22.9 | -0.046 |     700 |      21   |  -0.146 | False  |
| TRIANGLE | crypto   | 4H   | retest_swing | 1:1.5    |    656 |     45.7 |  0.098 |     702 |      37.7 |  -0.111 | False  |
| TRIANGLE | crypto   | 4H   | retest_swing | 1:3      |    656 |     27   |  0.034 |     700 |      21.4 |  -0.198 | False  |
| TRIANGLE | crypto   | 4H   | retest_swing | MM       |    656 |     22.1 | -0.011 |     701 |      17.8 |  -0.262 | False  |
| TRIANGLE | forex    | 1H   | immediate    | 1:1.5    |    857 |     37   | -0.14  |     934 |      39.1 |  -0.102 | False  |
| TRIANGLE | forex    | 1H   | immediate    | 1:3      |    840 |     21.5 | -0.203 |     916 |      21.8 |  -0.207 | False  |
| TRIANGLE | forex    | 1H   | immediate    | MM       |    857 |     38.5 | -0.164 |     930 |      39.5 |  -0.172 | False  |
| TRIANGLE | forex    | 1H   | retest_lvl   | 1:1.5    |    396 |     39.6 | -0.179 |     449 |      34.7 |  -0.336 | False  |
| TRIANGLE | forex    | 1H   | retest_lvl   | 1:3      |    395 |     24.8 | -0.178 |     449 |      21.8 |  -0.331 | False  |
| TRIANGLE | forex    | 1H   | retest_lvl   | MM       |    396 |     21.2 | -0.303 |     449 |      22.5 |  -0.307 | False  |
| TRIANGLE | forex    | 1H   | retest_swing | 1:1.5    |    396 |     39.6 | -0.185 |     449 |      33.2 |  -0.396 | False  |
| TRIANGLE | forex    | 1H   | retest_swing | 1:3      |    395 |     24.8 | -0.184 |     449 |      21.2 |  -0.379 | False  |
| TRIANGLE | forex    | 1H   | retest_swing | MM       |    396 |     21.7 | -0.26  |     449 |      21.4 |  -0.35  | False  |
| TRIANGLE | forex    | 4H   | immediate    | 1:1.5    |    272 |     34.2 | -0.174 |     232 |      41.4 |  -0.004 | False  |
| TRIANGLE | forex    | 4H   | immediate    | 1:3      |    264 |     20.5 | -0.211 |     222 |      27.5 |   0.06  | False  |
| TRIANGLE | forex    | 4H   | immediate    | MM       |    274 |     37.6 | -0.156 |     230 |      45.7 |  -0.01  | False  |
| TRIANGLE | forex    | 4H   | retest_lvl   | 1:1.5    |    129 |     41.9 | -0.034 |     106 |      40.6 |  -0.089 | False  |
| TRIANGLE | forex    | 4H   | retest_lvl   | 1:3      |    129 |     25.6 | -0.058 |     105 |      26.7 |  -0.037 | False  |
| TRIANGLE | forex    | 4H   | retest_lvl   | MM       |    129 |     26.4 |  0.013 |     105 |      25.7 |  -0.112 | False  |
| TRIANGLE | forex    | 4H   | retest_swing | 1:1.5    |    129 |     45   |  0.04  |     106 |      39.6 |  -0.113 | False  |
| TRIANGLE | forex    | 4H   | retest_swing | 1:3      |    129 |     28.7 |  0.063 |     106 |      25.5 |  -0.084 | False  |
| TRIANGLE | forex    | 4H   | retest_swing | MM       |    129 |     29.5 |  0.108 |     106 |      24.5 |  -0.117 | False  |
| TRIPLE   | crypto   | 1H   | immediate    | 1:1.5    |   4330 |     39.5 | -0.036 |    4720 |      43.2 |   0.05  | False  |
| TRIPLE   | crypto   | 1H   | immediate    | 1:3      |   4193 |     23.3 | -0.093 |    4493 |      25.2 |  -0.023 | False  |
| TRIPLE   | crypto   | 1H   | immediate    | MM       |   4352 |     56.2 | -0.007 |    4781 |      59.3 |   0.037 | False  |
| TRIPLE   | crypto   | 1H   | retest_lvl   | 1:1.5    |   2064 |     42.9 | -0.009 |    2197 |      39.9 |  -0.097 | False  |
| TRIPLE   | crypto   | 1H   | retest_lvl   | 1:3      |   2064 |     26.6 | -0.019 |    2196 |      26.1 |  -0.05  | False  |
| TRIPLE   | crypto   | 1H   | retest_lvl   | MM       |   2064 |     28.3 | -0.019 |    2199 |      29.9 |  -0.061 | False  |
| TRIPLE   | crypto   | 1H   | retest_swing | 1:1.5    |   2054 |     42.2 | -0.034 |    2182 |      39.4 |  -0.118 | False  |
| TRIPLE   | crypto   | 1H   | retest_swing | 1:3      |   2054 |     25.7 | -0.059 |    2181 |      25.7 |  -0.076 | False  |
| TRIPLE   | crypto   | 1H   | retest_swing | MM       |   2054 |     26.8 | -0.036 |    2184 |      29   |  -0.069 | False  |
| TRIPLE   | crypto   | 4H   | immediate    | 1:1.5    |    757 |     44.1 |  0.093 |    1018 |      42.5 |   0.05  | True   |
| TRIPLE   | crypto   | 4H   | immediate    | 1:3      |    708 |     23.3 | -0.079 |     953 |      25.4 |   0.002 | False  |
| TRIPLE   | crypto   | 4H   | immediate    | MM       |    762 |     59.1 |  0.066 |    1035 |      58.1 |   0.043 | True   |
| TRIPLE   | crypto   | 4H   | retest_lvl   | 1:1.5    |    364 |     42.3 |  0.019 |     453 |      40.6 |  -0.031 | False  |
| TRIPLE   | crypto   | 4H   | retest_lvl   | 1:3      |    364 |     28   |  0.082 |     451 |      22.8 |  -0.133 | False  |
| TRIPLE   | crypto   | 4H   | retest_lvl   | MM       |    364 |     29.1 |  0.016 |     452 |      25.2 |  -0.146 | False  |
| TRIPLE   | crypto   | 4H   | retest_swing | 1:1.5    |    364 |     42.3 |  0.016 |     453 |      39.3 |  -0.067 | False  |
| TRIPLE   | crypto   | 4H   | retest_swing | 1:3      |    364 |     28.6 |  0.101 |     451 |      22.2 |  -0.163 | False  |
| TRIPLE   | crypto   | 4H   | retest_swing | MM       |    364 |     27.5 | -0.004 |     452 |      23.9 |  -0.144 | False  |
| TRIPLE   | forex    | 1H   | immediate    | 1:1.5    |    589 |     40.2 | -0.038 |     669 |      41   |  -0.033 | False  |
| TRIPLE   | forex    | 1H   | immediate    | 1:3      |    560 |     23.2 | -0.116 |     635 |      26.5 |  -0     | False  |
| TRIPLE   | forex    | 1H   | immediate    | MM       |    593 |     56.3 | -0.033 |     674 |      54.9 |  -0.063 | False  |
| TRIPLE   | forex    | 1H   | retest_lvl   | 1:1.5    |    295 |     36.6 | -0.258 |     309 |      36.9 |  -0.29  | False  |
| TRIPLE   | forex    | 1H   | retest_lvl   | 1:3      |    295 |     26.4 | -0.116 |     309 |      24.6 |  -0.229 | False  |
| TRIPLE   | forex    | 1H   | retest_lvl   | MM       |    295 |     27.8 | -0.1   |     309 |      24.6 |  -0.204 | False  |
| TRIPLE   | forex    | 1H   | retest_swing | 1:1.5    |    295 |     33.9 | -0.341 |     309 |      32   |  -0.427 | False  |
| TRIPLE   | forex    | 1H   | retest_swing | 1:3      |    295 |     24.4 | -0.213 |     309 |      20.4 |  -0.412 | False  |
| TRIPLE   | forex    | 1H   | retest_swing | MM       |    295 |     27.5 | -0.089 |     309 |      20.1 |  -0.373 | False  |
| TRIPLE   | forex    | 4H   | immediate    | 1:1.5    |    153 |     27.5 | -0.335 |     186 |      37.1 |  -0.098 | False  |
| TRIPLE   | forex    | 4H   | immediate    | 1:3      |    141 |     17.7 | -0.313 |     172 |      22.7 |  -0.119 | False  |
| TRIPLE   | forex    | 4H   | immediate    | MM       |    155 |     46.5 | -0.19  |     186 |      54.8 |  -0.036 | False  |
| TRIPLE   | forex    | 4H   | retest_lvl   | 1:1.5    |     58 |     44.8 |  0.042 |      87 |      57.5 |   0.332 | True   |
| TRIPLE   | forex    | 4H   | retest_lvl   | 1:3      |     58 |     27.6 |  0.025 |      87 |      32.2 |   0.182 | True   |
| TRIPLE   | forex    | 4H   | retest_lvl   | MM       |     58 |     31   |  0.034 |      87 |      29.9 |   0.071 | True   |
| TRIPLE   | forex    | 4H   | retest_swing | 1:1.5    |     58 |     41.4 | -0.046 |      87 |      55.2 |   0.271 | False  |
| TRIPLE   | forex    | 4H   | retest_swing | 1:3      |     58 |     29.3 |  0.092 |      87 |      28.7 |   0.041 | True   |
| TRIPLE   | forex    | 4H   | retest_swing | MM       |     58 |     32.8 |  0.235 |      87 |      28.7 |   0.099 | True   |
| WEDGE    | crypto   | 1H   | immediate    | 1:1.5    |  14701 |     40.7 | -0.04  |   14459 |      41.4 |  -0.034 | False  |
| WEDGE    | crypto   | 1H   | immediate    | 1:3      |  14611 |     25.5 | -0.036 |   14296 |      26.6 |  -0.005 | False  |
| WEDGE    | crypto   | 1H   | immediate    | MM       |  14697 |     33   | -0.062 |   14461 |      34.2 |   0.007 | False  |
| WEDGE    | crypto   | 1H   | retest_lvl   | 1:1.5    |   4927 |     39.6 | -0.086 |    4589 |      41.4 |  -0.056 | False  |
| WEDGE    | crypto   | 1H   | retest_lvl   | 1:3      |   4926 |     25.2 | -0.067 |    4576 |      26.8 |  -0.019 | False  |
| WEDGE    | crypto   | 1H   | retest_lvl   | MM       |   4927 |     27.6 | -0.037 |    4583 |      29.2 |  -0.004 | False  |
| WEDGE    | crypto   | 1H   | retest_swing | 1:1.5    |   4880 |     39.3 | -0.106 |    4530 |      41.3 |  -0.075 | False  |
| WEDGE    | crypto   | 1H   | retest_swing | 1:3      |   4879 |     25   | -0.088 |    4525 |      27.2 |  -0.018 | False  |
| WEDGE    | crypto   | 1H   | retest_swing | MM       |   4880 |     24.8 | -0.05  |    4528 |      27   |   0.008 | False  |
| WEDGE    | crypto   | 4H   | immediate    | 1:1.5    |   3349 |     43.2 |  0.053 |    3465 |      41.4 |   0.001 | True   |
| WEDGE    | crypto   | 4H   | immediate    | 1:3      |   3331 |     27.2 |  0.06  |    3434 |      26.2 |   0.014 | True   |
| WEDGE    | crypto   | 4H   | immediate    | MM       |   3349 |     35   |  0.072 |    3445 |      35.6 |   0.058 | True   |
| WEDGE    | crypto   | 4H   | retest_lvl   | 1:1.5    |   1058 |     39.1 | -0.059 |    1120 |      44.8 |   0.075 | False  |
| WEDGE    | crypto   | 4H   | retest_lvl   | 1:3      |   1058 |     26   |  0.003 |    1117 |      30.2 |   0.161 | True   |
| WEDGE    | crypto   | 4H   | retest_lvl   | MM       |   1058 |     26.2 | -0.011 |    1118 |      31.1 |   0.133 | False  |
| WEDGE    | crypto   | 4H   | retest_swing | 1:1.5    |   1056 |     38.7 | -0.076 |    1122 |      43.9 |   0.041 | False  |
| WEDGE    | crypto   | 4H   | retest_swing | 1:3      |   1056 |     25.2 | -0.036 |    1119 |      29.8 |   0.138 | False  |
| WEDGE    | crypto   | 4H   | retest_swing | MM       |   1056 |     23.6 | -0.019 |    1120 |      28.9 |   0.088 | False  |
| WEDGE    | forex    | 1H   | immediate    | 1:1.5    |   2389 |     39.5 | -0.309 |    2494 |      39.5 |  -1.346 | False  |
| WEDGE    | forex    | 1H   | immediate    | 1:3      |   2375 |     24.9 | -0.3   |    2484 |      25.1 |  -1.339 | False  |
| WEDGE    | forex    | 1H   | immediate    | MM       |   2394 |     32.5 | -0.219 |    2496 |      32   |  -1.279 | False  |
| WEDGE    | forex    | 1H   | retest_lvl   | 1:1.5    |    735 |     38.6 | -0.185 |     779 |      39.5 |  -0.213 | False  |
| WEDGE    | forex    | 1H   | retest_lvl   | 1:3      |    735 |     23.8 | -0.199 |     779 |      25   |  -0.201 | False  |
| WEDGE    | forex    | 1H   | retest_lvl   | MM       |    735 |     25.7 | -0.207 |     779 |      25.8 |  -0.229 | False  |
| WEDGE    | forex    | 1H   | retest_swing | 1:1.5    |    735 |     37.8 | -0.242 |     779 |      41.8 |  -0.209 | False  |
| WEDGE    | forex    | 1H   | retest_swing | 1:3      |    735 |     24.2 | -0.219 |     779 |      26.1 |  -0.213 | False  |
| WEDGE    | forex    | 1H   | retest_swing | MM       |    735 |     23.4 | -0.226 |     779 |      24.3 |  -0.161 | False  |
| WEDGE    | forex    | 4H   | immediate    | 1:1.5    |    656 |     39   | -1.277 |     611 |      37.5 |  -0.195 | False  |
| WEDGE    | forex    | 4H   | immediate    | 1:3      |    643 |     20.5 | -1.461 |     608 |      26.5 |  -0.073 | False  |
| WEDGE    | forex    | 4H   | immediate    | MM       |    657 |     29.8 | -1.339 |     610 |      33.1 |  -0.056 | False  |
| WEDGE    | forex    | 4H   | retest_lvl   | 1:1.5    |    214 |     40.7 | -0.058 |     233 |      46.4 |   0.063 | False  |
| WEDGE    | forex    | 4H   | retest_lvl   | 1:3      |    214 |     25.7 | -0.046 |     232 |      31.9 |   0.18  | False  |
| WEDGE    | forex    | 4H   | retest_lvl   | MM       |    214 |     27.1 |  0.035 |     232 |      31.9 |   0.16  | True   |
| WEDGE    | forex    | 4H   | retest_swing | 1:1.5    |    214 |     38.8 | -0.124 |     233 |      41.2 |  -0.094 | False  |
| WEDGE    | forex    | 4H   | retest_swing | 1:3      |    214 |     24.3 | -0.121 |     233 |      28.3 |   0.009 | False  |
| WEDGE    | forex    | 4H   | retest_swing | MM       |    214 |     23.4 | -0.127 |     232 |      25.4 |   0.068 | False  |

## Full-period totals

|                                              |   n 1:1.5 |   win% 1:1.5 |   R/tr 1:1.5 |   n 1:3 |   win% 1:3 |   R/tr 1:3 |   n MM |   win% MM |   R/tr MM |
|:---------------------------------------------|----------:|-------------:|-------------:|--------:|-----------:|-----------:|-------:|----------:|----------:|
| ('CUP', 'crypto', '1H', 'immediate')         |       559 |         39.9 |       -0.026 |     537 |       24   |     -0.063 |    529 |      19.7 |    -0.138 |
| ('CUP', 'crypto', '1H', 'retest_lvl')        |       271 |         32.8 |       -0.244 |     271 |       22.1 |     -0.179 |    269 |       8.6 |    -0.12  |
| ('CUP', 'crypto', '1H', 'retest_swing')      |       271 |         36.2 |       -0.165 |     271 |       22.9 |     -0.154 |    269 |       7.8 |    -0.253 |
| ('CUP', 'crypto', '4H', 'immediate')         |       206 |         43.2 |        0.066 |     199 |       25.6 |      0.011 |    198 |      25.3 |     0.01  |
| ('CUP', 'crypto', '4H', 'retest_lvl')        |       113 |         42.5 |        0.022 |     113 |       28.3 |      0.092 |    112 |      13.4 |    -0.082 |
| ('CUP', 'crypto', '4H', 'retest_swing')      |       113 |         43.4 |        0.04  |     113 |       31   |      0.195 |    112 |      13.4 |    -0.011 |
| ('CUP', 'forex', '1H', 'immediate')          |        58 |         29.3 |       -0.315 |      57 |       17.5 |     -0.346 |     56 |      14.3 |    -0.402 |
| ('CUP', 'forex', '1H', 'retest_lvl')         |        28 |         42.9 |       -0.07  |      28 |       35.7 |      0.288 |     27 |      14.8 |     0.216 |
| ('CUP', 'forex', '1H', 'retest_swing')       |        28 |         42.9 |       -0.086 |      28 |       32.1 |      0.129 |     28 |      14.3 |     0.723 |
| ('CUP', 'forex', '4H', 'immediate')          |        38 |         47.4 |        0.152 |      36 |       25   |     -0.033 |     34 |      20.6 |    -0.013 |
| ('CUP', 'forex', '4H', 'retest_lvl')         |        19 |         47.4 |        0.085 |      19 |       31.6 |      0.164 |     19 |      10.5 |    -0.296 |
| ('CUP', 'forex', '4H', 'retest_swing')       |        19 |         47.4 |        0.09  |      19 |       31.6 |      0.169 |     19 |      10.5 |    -0.333 |
| ('DOUBLE', 'crypto', '1H', 'immediate')      |     14441 |         40.7 |       -0.015 |   14041 |       24.8 |     -0.04  |  14529 |      57.5 |    -0.013 |
| ('DOUBLE', 'crypto', '1H', 'retest_lvl')     |      6756 |         41.4 |       -0.058 |    6750 |       25.7 |     -0.064 |   6757 |      31.8 |    -0.056 |
| ('DOUBLE', 'crypto', '1H', 'retest_swing')   |      6712 |         40.9 |       -0.078 |    6704 |       25.9 |     -0.066 |   6713 |      30.5 |    -0.064 |
| ('DOUBLE', 'crypto', '4H', 'immediate')      |      3239 |         41.1 |        0.013 |    3119 |       24.3 |     -0.043 |   3254 |      58   |     0.021 |
| ('DOUBLE', 'crypto', '4H', 'retest_lvl')     |      1509 |         41   |       -0.023 |    1507 |       24.7 |     -0.059 |   1508 |      29.2 |    -0.081 |
| ('DOUBLE', 'crypto', '4H', 'retest_swing')   |      1510 |         39.9 |       -0.055 |    1507 |       24.8 |     -0.059 |   1509 |      28.1 |    -0.073 |
| ('DOUBLE', 'forex', '1H', 'immediate')       |      2214 |         40.4 |       -0.052 |    2151 |       24.3 |     -0.09  |   2225 |      57.3 |    -0.045 |
| ('DOUBLE', 'forex', '1H', 'retest_lvl')      |      1076 |         38.7 |       -0.221 |    1074 |       25.3 |     -0.175 |   1076 |      31.1 |    -0.194 |
| ('DOUBLE', 'forex', '1H', 'retest_swing')    |      1076 |         38   |       -0.251 |    1073 |       24   |     -0.24  |   1076 |      30   |    -0.224 |
| ('DOUBLE', 'forex', '4H', 'immediate')       |       546 |         39.2 |       -0.048 |     519 |       25.4 |     -0.011 |    548 |      57.7 |    -0.007 |
| ('DOUBLE', 'forex', '4H', 'retest_lvl')      |       251 |         41.4 |       -0.066 |     251 |       26.7 |     -0.034 |    251 |      31.1 |    -0.013 |
| ('DOUBLE', 'forex', '4H', 'retest_swing')    |       251 |         42.6 |       -0.044 |     251 |       25.5 |     -0.089 |    251 |      30.7 |    -0.025 |
| ('FLAG', 'crypto', '1H', 'immediate')        |     14941 |         40.3 |       -0.038 |   14852 |       25.6 |     -0.024 |  14917 |      33   |    -0.028 |
| ('FLAG', 'crypto', '1H', 'retest_lvl')       |      7500 |         38.4 |       -0.133 |    7494 |       23.7 |     -0.145 |   7495 |      19.6 |    -0.109 |
| ('FLAG', 'crypto', '1H', 'retest_swing')     |      7456 |         37.6 |       -0.16  |    7444 |       23.6 |     -0.156 |   7447 |      18.7 |    -0.131 |
| ('FLAG', 'crypto', '4H', 'immediate')        |      3500 |         39   |       -0.047 |    3454 |       23.2 |     -0.096 |   3487 |      31.5 |    -0.054 |
| ('FLAG', 'crypto', '4H', 'retest_lvl')       |      1794 |         41.8 |       -0.005 |    1793 |       25.3 |     -0.038 |   1794 |      18.1 |    -0.09  |
| ('FLAG', 'crypto', '4H', 'retest_swing')     |      1791 |         41.3 |       -0.021 |    1790 |       24.9 |     -0.057 |   1792 |      17.1 |    -0.073 |
| ('FLAG', 'forex', '1H', 'immediate')         |      2744 |         40.7 |       -0.076 |    2726 |       26.8 |     -0.021 |   2737 |      32.9 |    -0.041 |
| ('FLAG', 'forex', '1H', 'retest_lvl')        |      1256 |         38.9 |       -0.226 |    1256 |       24   |     -0.239 |   1256 |      19.1 |    -0.194 |
| ('FLAG', 'forex', '1H', 'retest_swing')      |      1256 |         37.7 |       -0.269 |    1256 |       25.1 |     -0.209 |   1256 |      19.4 |    -0.18  |
| ('FLAG', 'forex', '4H', 'immediate')         |       516 |         39.5 |       -0.054 |     512 |       23.2 |     -0.112 |    515 |      31.5 |    -0.101 |
| ('FLAG', 'forex', '4H', 'retest_lvl')        |       257 |         37   |       -0.171 |     255 |       21.2 |     -0.248 |    255 |      16.9 |    -0.17  |
| ('FLAG', 'forex', '4H', 'retest_swing')      |       257 |         40.1 |       -0.1   |     257 |       25.7 |     -0.075 |    257 |      17.1 |    -0.094 |
| ('HORIZ_SR', 'crypto', '1H', 'immediate')    |      8128 |         41   |       -0.007 |    7944 |       24.4 |     -0.056 |   8183 |      57.5 |     0.004 |
| ('HORIZ_SR', 'crypto', '1H', 'retest_lvl')   |      3902 |         42.1 |       -0.037 |    3898 |       26   |     -0.051 |   3902 |      31.9 |    -0.019 |
| ('HORIZ_SR', 'crypto', '1H', 'retest_swing') |      3876 |         42.7 |       -0.03  |    3872 |       27.4 |     -0.001 |   3876 |      31.5 |     0.009 |
| ('HORIZ_SR', 'crypto', '4H', 'immediate')    |      1680 |         41.8 |        0.03  |    1602 |       24.2 |     -0.046 |   1686 |      56.8 |     0.012 |
| ('HORIZ_SR', 'crypto', '4H', 'retest_lvl')   |       834 |         39.4 |       -0.06  |     832 |       21.5 |     -0.186 |    834 |      26.4 |    -0.168 |
| ('HORIZ_SR', 'crypto', '4H', 'retest_swing') |       833 |         39.1 |       -0.072 |     832 |       25.2 |     -0.041 |    833 |      24.7 |    -0.206 |
| ('HORIZ_SR', 'forex', '1H', 'immediate')     |      1141 |         38   |       -0.117 |    1112 |       24.5 |     -0.09  |   1149 |      53.5 |    -0.101 |
| ('HORIZ_SR', 'forex', '1H', 'retest_lvl')    |       567 |         34.4 |       -0.337 |     566 |       22.1 |     -0.314 |    567 |      25.6 |    -0.365 |
| ('HORIZ_SR', 'forex', '1H', 'retest_swing')  |       567 |         33.9 |       -0.363 |     566 |       18.7 |     -0.461 |    567 |      24.5 |    -0.384 |
| ('HORIZ_SR', 'forex', '4H', 'immediate')     |       288 |         33.7 |       -0.185 |     274 |       23   |     -0.108 |    290 |      50.3 |    -0.114 |
| ('HORIZ_SR', 'forex', '4H', 'retest_lvl')    |       123 |         46.3 |        0.065 |     122 |       28.7 |      0.053 |    123 |      31.7 |     0.018 |
| ('HORIZ_SR', 'forex', '4H', 'retest_swing')  |       123 |         43.9 |       -0.009 |     123 |       26   |     -0.066 |    123 |      28.5 |     0.089 |
| ('TRIANGLE', 'crypto', '1H', 'immediate')    |     12566 |         42.3 |        0.02  |   12360 |       26.2 |      0.009 |  12573 |      44.8 |     0.017 |
| ('TRIANGLE', 'crypto', '1H', 'retest_lvl')   |      5958 |         40.8 |       -0.073 |    5953 |       26.1 |     -0.051 |   5958 |      23.9 |    -0.038 |
| ('TRIANGLE', 'crypto', '1H', 'retest_swing') |      5928 |         40.9 |       -0.078 |    5919 |       26.1 |     -0.057 |   5929 |      23   |    -0.049 |
| ('TRIANGLE', 'crypto', '4H', 'immediate')    |      2927 |         40.1 |       -0.013 |    2837 |       24.3 |     -0.045 |   2928 |      41.4 |    -0.051 |
| ('TRIANGLE', 'crypto', '4H', 'retest_lvl')   |      1359 |         41.8 |       -0.002 |    1352 |       24.4 |     -0.071 |   1356 |      21.9 |    -0.098 |
| ('TRIANGLE', 'crypto', '4H', 'retest_swing') |      1358 |         41.6 |       -0.01  |    1356 |       24.1 |     -0.086 |   1357 |      19.9 |    -0.141 |
| ('TRIANGLE', 'forex', '1H', 'immediate')     |      1791 |         38.1 |       -0.12  |    1756 |       21.7 |     -0.205 |   1787 |      39   |    -0.168 |
| ('TRIANGLE', 'forex', '1H', 'retest_lvl')    |       845 |         37   |       -0.262 |     844 |       23.2 |     -0.26  |    845 |      21.9 |    -0.305 |
| ('TRIANGLE', 'forex', '1H', 'retest_swing')  |       845 |         36.2 |       -0.297 |     844 |       22.9 |     -0.288 |    845 |      21.5 |    -0.308 |
| ('TRIANGLE', 'forex', '4H', 'immediate')     |       504 |         37.5 |       -0.096 |     486 |       23.7 |     -0.087 |    504 |      41.3 |    -0.089 |
| ('TRIANGLE', 'forex', '4H', 'retest_lvl')    |       235 |         41.3 |       -0.059 |     234 |       26.1 |     -0.048 |    234 |      26.1 |    -0.043 |
| ('TRIANGLE', 'forex', '4H', 'retest_swing')  |       235 |         42.6 |       -0.029 |     235 |       27.2 |     -0.003 |    235 |      27.2 |     0.006 |
| ('TRIPLE', 'crypto', '1H', 'immediate')      |      9050 |         41.4 |        0.009 |    8686 |       24.3 |     -0.057 |   9133 |      57.8 |     0.016 |
| ('TRIPLE', 'crypto', '1H', 'retest_lvl')     |      4261 |         41.4 |       -0.054 |    4260 |       26.3 |     -0.035 |   4263 |      29.2 |    -0.04  |
| ('TRIPLE', 'crypto', '1H', 'retest_swing')   |      4236 |         40.7 |       -0.077 |    4235 |       25.7 |     -0.068 |   4238 |      27.9 |    -0.053 |
| ('TRIPLE', 'crypto', '4H', 'immediate')      |      1775 |         43.2 |        0.068 |    1661 |       24.5 |     -0.032 |   1797 |      58.5 |     0.053 |
| ('TRIPLE', 'crypto', '4H', 'retest_lvl')     |       817 |         41.4 |       -0.009 |     815 |       25.2 |     -0.037 |    816 |      27   |    -0.074 |
| ('TRIPLE', 'crypto', '4H', 'retest_swing')   |       817 |         40.6 |       -0.03  |     815 |       25   |     -0.045 |    816 |      25.5 |    -0.081 |
| ('TRIPLE', 'forex', '1H', 'immediate')       |      1258 |         40.6 |       -0.035 |    1195 |       24.9 |     -0.055 |   1267 |      55.6 |    -0.049 |
| ('TRIPLE', 'forex', '1H', 'retest_lvl')      |       604 |         36.8 |       -0.275 |     604 |       25.5 |     -0.174 |    604 |      26.2 |    -0.153 |
| ('TRIPLE', 'forex', '1H', 'retest_swing')    |       604 |         32.9 |       -0.385 |     604 |       22.4 |     -0.315 |    604 |      23.7 |    -0.235 |
| ('TRIPLE', 'forex', '4H', 'immediate')       |       339 |         32.7 |       -0.205 |     313 |       20.4 |     -0.206 |    341 |      51   |    -0.106 |
| ('TRIPLE', 'forex', '4H', 'retest_lvl')      |       145 |         52.4 |        0.216 |     145 |       30.3 |      0.119 |    145 |      30.3 |     0.056 |
| ('TRIPLE', 'forex', '4H', 'retest_swing')    |       145 |         49.7 |        0.144 |     145 |       29   |      0.062 |    145 |      30.3 |     0.153 |
| ('WEDGE', 'crypto', '1H', 'immediate')       |     29160 |         41.1 |       -0.037 |   28907 |       26.1 |     -0.021 |  29158 |      33.6 |    -0.028 |
| ('WEDGE', 'crypto', '1H', 'retest_lvl')      |      9516 |         40.5 |       -0.072 |    9502 |       26   |     -0.044 |   9510 |      28.3 |    -0.021 |
| ('WEDGE', 'crypto', '1H', 'retest_swing')    |      9410 |         40.3 |       -0.091 |    9404 |       26.1 |     -0.054 |   9408 |      25.8 |    -0.022 |
| ('WEDGE', 'crypto', '4H', 'immediate')       |      6814 |         42.3 |        0.027 |    6765 |       26.7 |      0.037 |   6794 |      35.3 |     0.065 |
| ('WEDGE', 'crypto', '4H', 'retest_lvl')      |      2178 |         42.1 |        0.01  |    2175 |       28.1 |      0.084 |   2176 |      28.7 |     0.063 |
| ('WEDGE', 'crypto', '4H', 'retest_swing')    |      2178 |         41.4 |       -0.016 |    2175 |       27.6 |      0.054 |   2176 |      26.3 |     0.036 |
| ('WEDGE', 'forex', '1H', 'immediate')        |      4883 |         39.5 |       -0.839 |    4859 |       25   |     -0.831 |   4890 |      32.3 |    -0.76  |
| ('WEDGE', 'forex', '1H', 'retest_lvl')       |      1514 |         39.1 |       -0.2   |    1514 |       24.4 |     -0.2   |   1514 |      25.8 |    -0.219 |
| ('WEDGE', 'forex', '1H', 'retest_swing')     |      1514 |         39.9 |       -0.225 |    1514 |       25.2 |     -0.216 |   1514 |      23.8 |    -0.192 |
| ('WEDGE', 'forex', '4H', 'immediate')        |      1267 |         38.3 |       -0.755 |    1251 |       23.4 |     -0.786 |   1267 |      31.4 |    -0.721 |
| ('WEDGE', 'forex', '4H', 'retest_lvl')       |       447 |         43.6 |        0.005 |     446 |       28.9 |      0.071 |    446 |      29.6 |     0.1   |
| ('WEDGE', 'forex', '4H', 'retest_swing')     |       447 |         40   |       -0.108 |     447 |       26.4 |     -0.053 |    446 |      24.4 |    -0.025 |

## Regime splits (full period)

| fam      | market   | tf   | entry        | regime         |   n 1:1.5 |   win% 1:1.5 |   R/tr 1:1.5 |   n 1:3 |   win% 1:3 |   R/tr 1:3 |   n MM |   win% MM |   R/tr MM |
|:---------|:---------|:-----|:-------------|:---------------|----------:|-------------:|-------------:|--------:|-----------:|-----------:|-------:|----------:|----------:|
| CUP      | crypto   | 1H   | immediate    | trend=bear     |       103 |         48.5 |        0.188 |      97 |       32   |      0.252 |     88 |      22.7 |     0.003 |
| CUP      | crypto   | 1H   | immediate    | trend=bull     |       175 |         41.7 |        0.02  |     166 |       25.3 |     -0.011 |    167 |      22.2 |    -0.037 |
| CUP      | crypto   | 1H   | immediate    | trend=sideways |       281 |         35.6 |       -0.134 |     274 |       20.4 |     -0.206 |    274 |      17.2 |    -0.244 |
| CUP      | crypto   | 1H   | immediate    | vol=high-vol   |       214 |         47.7 |        0.168 |     209 |       34.9 |      0.374 |    198 |      27.3 |     0.214 |
| CUP      | crypto   | 1H   | immediate    | vol=low-vol    |       345 |         35.1 |       -0.147 |     328 |       17.1 |     -0.342 |    331 |      15.1 |    -0.348 |
| CUP      | crypto   | 1H   | retest_lvl   | trend=bear     |        61 |         42.6 |       -0.001 |      61 |       23   |     -0.149 |     59 |       6.8 |    -0.584 |
| CUP      | crypto   | 1H   | retest_lvl   | trend=bull     |        80 |         30   |       -0.312 |      80 |       22.5 |     -0.162 |     80 |      11.2 |     0.297 |
| CUP      | crypto   | 1H   | retest_lvl   | trend=sideways |       130 |         30   |       -0.315 |     130 |       21.5 |     -0.204 |    130 |       7.7 |    -0.166 |
| CUP      | crypto   | 1H   | retest_lvl   | vol=high-vol   |       107 |         32.7 |       -0.243 |     107 |       22.4 |     -0.163 |    106 |      11.3 |     0.014 |
| CUP      | crypto   | 1H   | retest_lvl   | vol=low-vol    |       164 |         32.9 |       -0.244 |     164 |       22   |     -0.19  |    163 |       6.7 |    -0.207 |
| CUP      | crypto   | 1H   | retest_swing | trend=bear     |        61 |         41   |       -0.048 |      61 |       27.9 |      0.042 |     59 |       6.8 |    -0.529 |
| CUP      | crypto   | 1H   | retest_swing | trend=bull     |        80 |         37.5 |       -0.128 |      80 |       23.8 |     -0.116 |     80 |      11.2 |     0.228 |
| CUP      | crypto   | 1H   | retest_swing | trend=sideways |       130 |         33.1 |       -0.243 |     130 |       20   |     -0.27  |    130 |       6.2 |    -0.425 |
| CUP      | crypto   | 1H   | retest_swing | vol=high-vol   |       107 |         38.3 |       -0.111 |     107 |       26.2 |     -0.022 |    106 |      10.4 |     0.006 |
| CUP      | crypto   | 1H   | retest_swing | vol=low-vol    |       164 |         34.8 |       -0.201 |     164 |       20.7 |     -0.24  |    163 |       6.1 |    -0.422 |
| CUP      | crypto   | 4H   | immediate    | trend=bear     |        64 |         46.9 |        0.158 |      60 |       20   |     -0.214 |     60 |      20   |    -0.257 |
| CUP      | crypto   | 4H   | immediate    | trend=bull     |        25 |         24   |       -0.413 |      25 |       20   |     -0.213 |     25 |      20   |    -0.219 |
| CUP      | crypto   | 4H   | immediate    | trend=sideways |       117 |         45.3 |        0.118 |     114 |       29.8 |      0.178 |    113 |      29.2 |     0.202 |
| CUP      | crypto   | 4H   | immediate    | vol=high-vol   |        63 |         42.9 |        0.058 |      59 |       25.4 |      0.003 |     59 |      23.7 |    -0.029 |
| CUP      | crypto   | 4H   | immediate    | vol=low-vol    |       143 |         43.4 |        0.069 |     140 |       25.7 |      0.014 |    139 |      25.9 |     0.026 |
| CUP      | crypto   | 4H   | retest_lvl   | trend=bear     |        30 |         50   |        0.213 |      30 |       36.7 |      0.43  |     30 |      13.3 |     0.202 |
| CUP      | crypto   | 4H   | retest_lvl   | trend=bull     |         9 |         33.3 |       -0.2   |       9 |        0   |     -1.034 |      9 |       0   |    -1.034 |
| CUP      | crypto   | 4H   | retest_lvl   | trend=sideways |        74 |         40.5 |       -0.029 |      74 |       28.4 |      0.093 |     73 |      15.1 |    -0.081 |
| CUP      | crypto   | 4H   | retest_lvl   | vol=high-vol   |        30 |         50   |        0.207 |      30 |       26.7 |      0.023 |     30 |       6.7 |    -0.27  |
| CUP      | crypto   | 4H   | retest_lvl   | vol=low-vol    |        83 |         39.8 |       -0.045 |      83 |       28.9 |      0.117 |     82 |      15.9 |    -0.013 |
| CUP      | crypto   | 4H   | retest_swing | trend=bear     |        30 |         53.3 |        0.29  |      30 |       40   |      0.557 |     30 |      13.3 |     0.243 |
| CUP      | crypto   | 4H   | retest_swing | trend=bull     |         9 |         33.3 |       -0.215 |       9 |       22.2 |     -0.16  |      9 |       0   |    -1.048 |
| CUP      | crypto   | 4H   | retest_swing | trend=sideways |        74 |         40.5 |       -0.03  |      74 |       28.4 |      0.091 |     73 |      15.1 |     0.012 |
| CUP      | crypto   | 4H   | retest_swing | vol=high-vol   |        30 |         50   |        0.205 |      30 |       33.3 |      0.288 |     30 |       6.7 |    -0.363 |
| CUP      | crypto   | 4H   | retest_swing | vol=low-vol    |        83 |         41   |       -0.019 |      83 |       30.1 |      0.161 |     82 |      15.9 |     0.117 |
| CUP      | forex    | 1H   | immediate    | fxvol=high-ATR |        29 |         24.1 |       -0.439 |      28 |       14.3 |     -0.472 |     27 |      11.1 |    -0.515 |
| CUP      | forex    | 1H   | immediate    | fxvol=low-ATR  |        29 |         34.5 |       -0.19  |      29 |       20.7 |     -0.225 |     29 |      17.2 |    -0.297 |
| CUP      | forex    | 1H   | retest_lvl   | fxvol=high-ATR |        12 |         41.7 |       -0.077 |      12 |       33.3 |      0.215 |     11 |      18.2 |     0.265 |
| CUP      | forex    | 1H   | retest_lvl   | fxvol=low-ATR  |        16 |         43.8 |       -0.064 |      16 |       37.5 |      0.342 |     16 |      12.5 |     0.182 |
| CUP      | forex    | 1H   | retest_swing | fxvol=high-ATR |        12 |         33.3 |       -0.298 |      12 |       16.7 |     -0.465 |     12 |       8.3 |    -0.505 |
| CUP      | forex    | 1H   | retest_swing | fxvol=low-ATR  |        16 |         50   |        0.074 |      16 |       43.8 |      0.574 |     16 |      18.8 |     1.643 |
| CUP      | forex    | 4H   | immediate    | fxvol=high-ATR |        12 |         50   |        0.224 |      10 |       30   |      0.172 |     10 |      30   |     0.449 |
| CUP      | forex    | 4H   | immediate    | fxvol=low-ATR  |        26 |         46.2 |        0.119 |      26 |       23.1 |     -0.111 |     24 |      16.7 |    -0.205 |
| CUP      | forex    | 4H   | retest_lvl   | fxvol=high-ATR |         5 |         60   |        0.407 |       5 |       40   |      0.507 |      5 |       0   |    -1.093 |
| CUP      | forex    | 4H   | retest_lvl   | fxvol=low-ATR  |        14 |         42.9 |       -0.03  |      14 |       28.6 |      0.042 |     14 |      14.3 |    -0.012 |
| CUP      | forex    | 4H   | retest_swing | fxvol=high-ATR |         5 |         60   |        0.431 |       5 |       40   |      0.531 |      5 |       0   |    -1.069 |
| CUP      | forex    | 4H   | retest_swing | fxvol=low-ATR  |        14 |         42.9 |       -0.032 |      14 |       28.6 |      0.039 |     14 |      14.3 |    -0.07  |
| DOUBLE   | crypto   | 1H   | immediate    | trend=bear     |      3045 |         42.2 |        0.027 |    2889 |       24.3 |     -0.057 |   3077 |      59.3 |     0.025 |
| DOUBLE   | crypto   | 1H   | immediate    | trend=bull     |      3468 |         41.6 |        0.011 |    3391 |       25.7 |      0.001 |   3490 |      57.7 |    -0.006 |
| DOUBLE   | crypto   | 1H   | immediate    | trend=sideways |      7928 |         39.7 |       -0.043 |    7761 |       24.6 |     -0.051 |   7962 |      56.6 |    -0.03  |
| DOUBLE   | crypto   | 1H   | immediate    | vol=high-vol   |      4452 |         42   |        0.021 |    4271 |       23.9 |     -0.073 |   4493 |      58.3 |     0.006 |
| DOUBLE   | crypto   | 1H   | immediate    | vol=low-vol    |      9989 |         40.1 |       -0.032 |    9770 |       25.2 |     -0.025 |  10036 |      57.1 |    -0.021 |
| DOUBLE   | crypto   | 1H   | retest_lvl   | trend=bear     |      1415 |         37.2 |       -0.158 |    1415 |       21.6 |     -0.222 |   1415 |      28.5 |    -0.154 |
| DOUBLE   | crypto   | 1H   | retest_lvl   | trend=bull     |      1664 |         44.1 |        0.018 |    1661 |       27.2 |      0.003 |   1665 |      32.7 |     0.003 |
| DOUBLE   | crypto   | 1H   | retest_lvl   | trend=sideways |      3677 |         41.8 |       -0.054 |    3674 |       26.6 |     -0.034 |   3677 |      32.7 |    -0.046 |
| DOUBLE   | crypto   | 1H   | retest_lvl   | vol=high-vol   |      2074 |         39.3 |       -0.099 |    2071 |       23.9 |     -0.124 |   2075 |      31   |    -0.087 |
| DOUBLE   | crypto   | 1H   | retest_lvl   | vol=low-vol    |      4682 |         42.3 |       -0.04  |    4679 |       26.5 |     -0.038 |   4682 |      32.2 |    -0.043 |
| DOUBLE   | crypto   | 1H   | retest_swing | trend=bear     |      1406 |         36.1 |       -0.191 |    1406 |       22.3 |     -0.201 |   1406 |      27.5 |    -0.17  |
| DOUBLE   | crypto   | 1H   | retest_swing | trend=bull     |      1659 |         42.6 |       -0.026 |    1655 |       26.5 |     -0.029 |   1660 |      30.6 |     0.003 |
| DOUBLE   | crypto   | 1H   | retest_swing | trend=sideways |      3647 |         42   |       -0.058 |    3643 |       26.9 |     -0.031 |   3647 |      31.6 |    -0.053 |
| DOUBLE   | crypto   | 1H   | retest_swing | vol=high-vol   |      2066 |         39.3 |       -0.106 |    2062 |       23.5 |     -0.147 |   2067 |      30.2 |    -0.086 |
| DOUBLE   | crypto   | 1H   | retest_swing | vol=low-vol    |      4646 |         41.6 |       -0.066 |    4642 |       26.9 |     -0.03  |   4646 |      30.6 |    -0.054 |
| DOUBLE   | crypto   | 4H   | immediate    | trend=bear     |       713 |         40.5 |        0     |     667 |       15.7 |     -0.384 |    721 |      59.4 |     0.047 |
| DOUBLE   | crypto   | 4H   | immediate    | trend=bull     |       843 |         41.9 |        0.033 |     809 |       28.4 |      0.123 |    846 |      56.1 |     0.001 |
| DOUBLE   | crypto   | 4H   | immediate    | trend=sideways |      1683 |         41   |        0.009 |    1643 |       25.7 |      0.013 |   1687 |      58.3 |     0.02  |
| DOUBLE   | crypto   | 4H   | immediate    | vol=high-vol   |      1035 |         41.2 |        0.016 |     964 |       21.5 |     -0.154 |   1046 |      59.7 |     0.063 |
| DOUBLE   | crypto   | 4H   | immediate    | vol=low-vol    |      2204 |         41.1 |        0.012 |    2155 |       25.6 |      0.007 |   2208 |      57.2 |     0.001 |
| DOUBLE   | crypto   | 4H   | retest_lvl   | trend=bear     |       329 |         44.1 |        0.063 |     328 |       25.9 |     -0.003 |    328 |      33.5 |     0.041 |
| DOUBLE   | crypto   | 4H   | retest_lvl   | trend=bull     |       421 |         39.7 |       -0.051 |     420 |       26.9 |      0.034 |    421 |      29.7 |    -0.052 |
| DOUBLE   | crypto   | 4H   | retest_lvl   | trend=sideways |       759 |         40.3 |       -0.044 |     759 |       22.9 |     -0.135 |    759 |      27.1 |    -0.151 |
| DOUBLE   | crypto   | 4H   | retest_lvl   | vol=high-vol   |       534 |         40.8 |       -0.02  |     533 |       23.6 |     -0.095 |    534 |      29   |    -0.089 |
| DOUBLE   | crypto   | 4H   | retest_lvl   | vol=low-vol    |       975 |         41   |       -0.024 |     974 |       25.3 |     -0.04  |    974 |      29.4 |    -0.077 |
| DOUBLE   | crypto   | 4H   | retest_swing | trend=bear     |       329 |         44.1 |        0.058 |     328 |       25   |     -0.044 |    328 |      32.3 |     0.032 |
| DOUBLE   | crypto   | 4H   | retest_swing | trend=bull     |       422 |         39.6 |       -0.057 |     420 |       26.9 |      0.03  |    422 |      28.2 |    -0.036 |
| DOUBLE   | crypto   | 4H   | retest_swing | trend=sideways |       759 |         38.2 |       -0.103 |     759 |       23.6 |     -0.114 |    759 |      26.2 |    -0.139 |
| DOUBLE   | crypto   | 4H   | retest_swing | vol=high-vol   |       536 |         42.7 |        0.022 |     534 |       25.1 |     -0.042 |    536 |      28.7 |    -0.04  |
| DOUBLE   | crypto   | 4H   | retest_swing | vol=low-vol    |       974 |         38.3 |       -0.097 |     973 |       24.7 |     -0.068 |    973 |      27.7 |    -0.092 |
| DOUBLE   | forex    | 1H   | immediate    | fxvol=high-ATR |       881 |         42   |       -0.009 |     858 |       27.5 |      0.04  |    887 |      57.8 |    -0.037 |
| DOUBLE   | forex    | 1H   | immediate    | fxvol=low-ATR  |      1333 |         39.3 |       -0.08  |    1293 |       22.2 |     -0.176 |   1338 |      57   |    -0.05  |
| DOUBLE   | forex    | 1H   | retest_lvl   | fxvol=high-ATR |       422 |         39.3 |       -0.189 |     421 |       27.1 |     -0.09  |    422 |      31.8 |    -0.205 |
| DOUBLE   | forex    | 1H   | retest_lvl   | fxvol=low-ATR  |       654 |         38.2 |       -0.241 |     653 |       24.2 |     -0.229 |    654 |      30.7 |    -0.188 |
| DOUBLE   | forex    | 1H   | retest_swing | fxvol=high-ATR |       422 |         37.4 |       -0.247 |     421 |       23.8 |     -0.233 |    422 |      30.8 |    -0.218 |
| DOUBLE   | forex    | 1H   | retest_swing | fxvol=low-ATR  |       654 |         38.4 |       -0.254 |     652 |       24.2 |     -0.245 |    654 |      29.5 |    -0.228 |
| DOUBLE   | forex    | 4H   | immediate    | fxvol=high-ATR |       179 |         46.4 |        0.132 |     166 |       30.1 |      0.177 |    179 |      63.1 |     0.096 |
| DOUBLE   | forex    | 4H   | immediate    | fxvol=low-ATR  |       367 |         35.7 |       -0.136 |     353 |       23.2 |     -0.1   |    369 |      55   |    -0.057 |
| DOUBLE   | forex    | 4H   | retest_lvl   | fxvol=high-ATR |        74 |         39.2 |       -0.111 |      74 |       23   |     -0.172 |     74 |      27   |    -0.288 |
| DOUBLE   | forex    | 4H   | retest_lvl   | fxvol=low-ATR  |       177 |         42.4 |       -0.046 |     177 |       28.2 |      0.024 |    177 |      32.8 |     0.102 |
| DOUBLE   | forex    | 4H   | retest_swing | fxvol=high-ATR |        74 |         43.2 |       -0.026 |      74 |       20.3 |     -0.297 |     74 |      27   |    -0.277 |
| DOUBLE   | forex    | 4H   | retest_swing | fxvol=low-ATR  |       177 |         42.4 |       -0.051 |     177 |       27.7 |     -0.003 |    177 |      32.2 |     0.08  |
| FLAG     | crypto   | 1H   | immediate    | trend=bear     |      3474 |         42.4 |        0.016 |    3443 |       26.2 |      0.005 |   3468 |      34   |    -0.001 |
| FLAG     | crypto   | 1H   | immediate    | trend=bull     |      3115 |         41.9 |        0.006 |    3092 |       28.3 |      0.089 |   3110 |      35   |     0.053 |
| FLAG     | crypto   | 1H   | immediate    | trend=sideways |      8352 |         38.9 |       -0.077 |    8317 |       24.3 |     -0.077 |   8339 |      31.9 |    -0.069 |
| FLAG     | crypto   | 1H   | immediate    | vol=high-vol   |      4696 |         40.9 |       -0.019 |    4655 |       25   |     -0.04  |   4687 |      33   |    -0.03  |
| FLAG     | crypto   | 1H   | immediate    | vol=low-vol    |     10245 |         40.1 |       -0.047 |   10197 |       25.8 |     -0.016 |  10230 |      33.1 |    -0.026 |
| FLAG     | crypto   | 1H   | retest_lvl   | trend=bear     |      1806 |         39.8 |       -0.094 |    1806 |       23   |     -0.17  |   1805 |      17.7 |    -0.21  |
| FLAG     | crypto   | 1H   | retest_lvl   | trend=bull     |      1521 |         37.9 |       -0.138 |    1520 |       25.5 |     -0.066 |   1519 |      20.1 |    -0.057 |
| FLAG     | crypto   | 1H   | retest_lvl   | trend=sideways |      4173 |         38   |       -0.149 |    4168 |       23.4 |     -0.163 |   4171 |      20.1 |    -0.085 |
| FLAG     | crypto   | 1H   | retest_lvl   | vol=high-vol   |      2385 |         37.5 |       -0.146 |    2384 |       24.2 |     -0.118 |   2383 |      18.1 |    -0.148 |
| FLAG     | crypto   | 1H   | retest_lvl   | vol=low-vol    |      5115 |         38.8 |       -0.127 |    5110 |       23.5 |     -0.158 |   5112 |      20.2 |    -0.091 |
| FLAG     | crypto   | 1H   | retest_swing | trend=bear     |      1801 |         37.9 |       -0.149 |    1800 |       23.8 |     -0.146 |   1798 |      17   |    -0.223 |
| FLAG     | crypto   | 1H   | retest_swing | trend=bull     |      1521 |         37.7 |       -0.147 |    1520 |       25.1 |     -0.088 |   1519 |      19.4 |    -0.061 |
| FLAG     | crypto   | 1H   | retest_swing | trend=sideways |      4134 |         37.4 |       -0.169 |    4124 |       23   |     -0.185 |   4130 |      19.2 |    -0.116 |
| FLAG     | crypto   | 1H   | retest_swing | vol=high-vol   |      2375 |         36.7 |       -0.173 |    2373 |       23.4 |     -0.154 |   2373 |      16.9 |    -0.202 |
| FLAG     | crypto   | 1H   | retest_swing | vol=low-vol    |      5081 |         38   |       -0.154 |    5071 |       23.7 |     -0.157 |   5074 |      19.5 |    -0.097 |
| FLAG     | crypto   | 4H   | immediate    | trend=bear     |       758 |         44.6 |        0.094 |     739 |       20.7 |     -0.193 |    755 |      37.1 |     0.078 |
| FLAG     | crypto   | 4H   | immediate    | trend=bull     |       783 |         31.5 |       -0.234 |     774 |       20.7 |     -0.196 |    782 |      26.1 |    -0.243 |
| FLAG     | crypto   | 4H   | immediate    | trend=sideways |      1959 |         39.9 |       -0.027 |    1941 |       25.1 |     -0.018 |   1950 |      31.5 |    -0.029 |
| FLAG     | crypto   | 4H   | immediate    | vol=high-vol   |      1308 |         38.7 |       -0.054 |    1276 |       19.4 |     -0.244 |   1295 |      29.8 |    -0.115 |
| FLAG     | crypto   | 4H   | immediate    | vol=low-vol    |      2192 |         39.2 |       -0.043 |    2178 |       25.4 |     -0.009 |   2192 |      32.5 |    -0.018 |
| FLAG     | crypto   | 4H   | retest_lvl   | trend=bear     |       343 |         42.3 |        0.015 |     343 |       29.7 |      0.147 |    342 |      19.3 |     0.076 |
| FLAG     | crypto   | 4H   | retest_lvl   | trend=bull     |       390 |         33.8 |       -0.205 |     390 |       22.1 |     -0.169 |    392 |      17.3 |    -0.284 |
| FLAG     | crypto   | 4H   | retest_lvl   | trend=sideways |      1061 |         44.5 |        0.062 |    1060 |       25   |     -0.051 |   1060 |      18   |    -0.072 |
| FLAG     | crypto   | 4H   | retest_lvl   | vol=high-vol   |       685 |         37.2 |       -0.117 |     684 |       22.8 |     -0.135 |    685 |      14.3 |    -0.24  |
| FLAG     | crypto   | 4H   | retest_lvl   | vol=low-vol    |      1109 |         44.5 |        0.064 |    1109 |       26.8 |      0.021 |   1109 |      20.5 |     0.003 |
| FLAG     | crypto   | 4H   | retest_swing | trend=bear     |       343 |         44   |        0.055 |     343 |       30   |      0.155 |    342 |      17.8 |    -0.05  |
| FLAG     | crypto   | 4H   | retest_swing | trend=bull     |       390 |         34.4 |       -0.196 |     389 |       21.1 |     -0.211 |    392 |      17.3 |    -0.219 |
| FLAG     | crypto   | 4H   | retest_swing | trend=sideways |      1058 |         43   |        0.019 |    1058 |       24.7 |     -0.07  |   1058 |      16.7 |    -0.025 |
| FLAG     | crypto   | 4H   | retest_swing | vol=high-vol   |       685 |         39.4 |       -0.067 |     684 |       23   |     -0.134 |    686 |      14   |    -0.224 |
| FLAG     | crypto   | 4H   | retest_swing | vol=low-vol    |      1106 |         42.5 |        0.007 |    1106 |       26.1 |     -0.01  |   1106 |      19   |     0.021 |
| FLAG     | forex    | 1H   | immediate    | fxvol=high-ATR |       993 |         38.3 |       -0.131 |     986 |       25.9 |     -0.053 |    993 |      30.4 |    -0.096 |
| FLAG     | forex    | 1H   | immediate    | fxvol=low-ATR  |      1751 |         42   |       -0.045 |    1740 |       27.4 |     -0.002 |   1744 |      34.3 |    -0.01  |
| FLAG     | forex    | 1H   | retest_lvl   | fxvol=high-ATR |       473 |         38.5 |       -0.22  |     473 |       21.8 |     -0.311 |    473 |      16.5 |    -0.309 |
| FLAG     | forex    | 1H   | retest_lvl   | fxvol=low-ATR  |       783 |         39.1 |       -0.23  |     783 |       25.3 |     -0.196 |    783 |      20.7 |    -0.125 |
| FLAG     | forex    | 1H   | retest_swing | fxvol=high-ATR |       473 |         37   |       -0.273 |     473 |       23.7 |     -0.251 |    473 |      16.7 |    -0.247 |
| FLAG     | forex    | 1H   | retest_swing | fxvol=low-ATR  |       783 |         38.2 |       -0.266 |     783 |       25.9 |     -0.184 |    783 |      21.1 |    -0.139 |
| FLAG     | forex    | 4H   | immediate    | fxvol=high-ATR |       200 |         43   |        0.04  |     199 |       27.6 |      0.07  |    199 |      37.2 |     0.062 |
| FLAG     | forex    | 4H   | immediate    | fxvol=low-ATR  |       316 |         37.3 |       -0.113 |     313 |       20.4 |     -0.229 |    316 |      27.8 |    -0.203 |
| FLAG     | forex    | 4H   | retest_lvl   | fxvol=high-ATR |        95 |         48.4 |        0.125 |      95 |       29.5 |      0.094 |     95 |      23.2 |     0.309 |
| FLAG     | forex    | 4H   | retest_lvl   | fxvol=low-ATR  |       162 |         30.2 |       -0.345 |     160 |       16.2 |     -0.452 |    160 |      13.1 |    -0.455 |
| FLAG     | forex    | 4H   | retest_swing | fxvol=high-ATR |        95 |         48.4 |        0.116 |      95 |       34.7 |      0.295 |     95 |      23.2 |     0.345 |
| FLAG     | forex    | 4H   | retest_swing | fxvol=low-ATR  |       162 |         35.2 |       -0.227 |     162 |       20.4 |     -0.292 |    162 |      13.6 |    -0.351 |
| HORIZ_SR | crypto   | 1H   | immediate    | trend=bear     |      1692 |         42.4 |        0.033 |    1625 |       23.9 |     -0.071 |   1706 |      59.3 |     0.04  |
| HORIZ_SR | crypto   | 1H   | immediate    | trend=bull     |      1953 |         41.7 |        0.015 |    1923 |       24.8 |     -0.038 |   1968 |      57.6 |     0.01  |
| HORIZ_SR | crypto   | 1H   | immediate    | trend=sideways |      4483 |         40.1 |       -0.032 |    4396 |       24.4 |     -0.058 |   4509 |      56.9 |    -0.012 |
| HORIZ_SR | crypto   | 1H   | immediate    | vol=high-vol   |      2684 |         43   |        0.046 |    2602 |       25.1 |     -0.026 |   2713 |      58.3 |     0.021 |
| HORIZ_SR | crypto   | 1H   | immediate    | vol=low-vol    |      5444 |         40   |       -0.033 |    5342 |       24.1 |     -0.071 |   5470 |      57.2 |    -0.005 |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | trend=bear     |       807 |         40.5 |       -0.072 |     807 |       23.5 |     -0.143 |    807 |      29.2 |    -0.11  |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | trend=bull     |       957 |         44   |        0.018 |     954 |       27.1 |      0.004 |    957 |      32.8 |     0.035 |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | trend=sideways |      2138 |         41.9 |       -0.05  |    2137 |       26.4 |     -0.04  |   2138 |      32.6 |    -0.009 |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | vol=high-vol   |      1277 |         41.9 |       -0.034 |    1274 |       26.3 |     -0.029 |   1277 |      32.7 |     0.007 |
| HORIZ_SR | crypto   | 1H   | retest_lvl   | vol=low-vol    |      2625 |         42.2 |       -0.039 |    2624 |       25.8 |     -0.061 |   2625 |      31.6 |    -0.032 |
| HORIZ_SR | crypto   | 1H   | retest_swing | trend=bear     |       803 |         40.8 |       -0.074 |     803 |       25.7 |     -0.069 |    803 |      29.8 |    -0.019 |
| HORIZ_SR | crypto   | 1H   | retest_swing | trend=bull     |       953 |         43.4 |       -0.002 |     951 |       26.7 |     -0.02  |    953 |      30.4 |    -0.001 |
| HORIZ_SR | crypto   | 1H   | retest_swing | trend=sideways |      2120 |         43.1 |       -0.025 |    2118 |       28.4 |      0.033 |   2120 |      32.6 |     0.024 |
| HORIZ_SR | crypto   | 1H   | retest_swing | vol=high-vol   |      1273 |         42.3 |       -0.03  |    1271 |       27   |     -0.009 |   1273 |      32.2 |     0.066 |
| HORIZ_SR | crypto   | 1H   | retest_swing | vol=low-vol    |      2603 |         42.9 |       -0.03  |    2601 |       27.6 |      0.002 |   2603 |      31.2 |    -0.019 |
| HORIZ_SR | crypto   | 4H   | immediate    | trend=bear     |       384 |         42.7 |        0.055 |     352 |       17.6 |     -0.308 |    389 |      59.1 |     0.058 |
| HORIZ_SR | crypto   | 4H   | immediate    | trend=bull     |       472 |         43.4 |        0.073 |     445 |       29.4 |      0.164 |    472 |      54.2 |    -0.017 |
| HORIZ_SR | crypto   | 4H   | immediate    | trend=sideways |       824 |         40.4 |       -0.006 |     805 |       24.2 |     -0.047 |    825 |      57.1 |     0.007 |
| HORIZ_SR | crypto   | 4H   | immediate    | vol=high-vol   |       519 |         44.7 |        0.105 |     475 |       24   |     -0.053 |    525 |      58.9 |     0.073 |
| HORIZ_SR | crypto   | 4H   | immediate    | vol=low-vol    |      1161 |         40.5 |       -0.003 |    1127 |       24.3 |     -0.043 |   1161 |      55.8 |    -0.016 |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | trend=bear     |       193 |         48.7 |        0.177 |     191 |       22.5 |     -0.14  |    193 |      33.2 |     0.052 |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | trend=bull     |       234 |         39.3 |       -0.058 |     234 |       28.6 |      0.105 |    234 |      30.8 |     0.012 |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | trend=sideways |       407 |         35.1 |       -0.173 |     407 |       17   |     -0.374 |    407 |      20.6 |    -0.375 |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | vol=high-vol   |       273 |         45.8 |        0.104 |     272 |       23.9 |     -0.085 |    273 |      30.8 |    -0.01  |
| HORIZ_SR | crypto   | 4H   | retest_lvl   | vol=low-vol    |       561 |         36.4 |       -0.139 |     560 |       20.4 |     -0.234 |    561 |      24.2 |    -0.244 |
| HORIZ_SR | crypto   | 4H   | retest_swing | trend=bear     |       193 |         47.2 |        0.133 |     192 |       30.2 |      0.162 |    193 |      28.5 |    -0.06  |
| HORIZ_SR | crypto   | 4H   | retest_swing | trend=bull     |       234 |         38.5 |       -0.084 |     234 |       29.1 |      0.117 |    234 |      28.6 |    -0.043 |
| HORIZ_SR | crypto   | 4H   | retest_swing | trend=sideways |       406 |         35.7 |       -0.163 |     406 |       20.7 |     -0.228 |    406 |      20.7 |    -0.369 |
| HORIZ_SR | crypto   | 4H   | retest_swing | vol=high-vol   |       273 |         46.5 |        0.118 |     272 |       30.1 |      0.161 |    273 |      29.7 |     0.014 |
| HORIZ_SR | crypto   | 4H   | retest_swing | vol=low-vol    |       560 |         35.5 |       -0.165 |     560 |       22.9 |     -0.139 |    560 |      22.3 |    -0.313 |
| HORIZ_SR | forex    | 1H   | immediate    | fxvol=high-ATR |       485 |         38.1 |       -0.104 |     473 |       27.1 |      0.024 |    491 |      52.7 |    -0.113 |
| HORIZ_SR | forex    | 1H   | immediate    | fxvol=low-ATR  |       656 |         38   |       -0.126 |     639 |       22.5 |     -0.175 |    658 |      54.1 |    -0.091 |
| HORIZ_SR | forex    | 1H   | retest_lvl   | fxvol=high-ATR |       229 |         34.5 |       -0.32  |     229 |       24   |     -0.221 |    229 |      24.9 |    -0.36  |
| HORIZ_SR | forex    | 1H   | retest_lvl   | fxvol=low-ATR  |       338 |         34.3 |       -0.349 |     337 |       20.8 |     -0.376 |    338 |      26   |    -0.369 |
| HORIZ_SR | forex    | 1H   | retest_swing | fxvol=high-ATR |       229 |         31.9 |       -0.394 |     229 |       19.2 |     -0.422 |    229 |      24.5 |    -0.316 |
| HORIZ_SR | forex    | 1H   | retest_swing | fxvol=low-ATR  |       338 |         35.2 |       -0.343 |     337 |       18.4 |     -0.488 |    338 |      24.6 |    -0.429 |
| HORIZ_SR | forex    | 4H   | immediate    | fxvol=high-ATR |        84 |         47.6 |        0.165 |      78 |       33.3 |      0.307 |     84 |      58.3 |     0.035 |
| HORIZ_SR | forex    | 4H   | immediate    | fxvol=low-ATR  |       204 |         27.9 |       -0.329 |     196 |       18.9 |     -0.273 |    206 |      47.1 |    -0.175 |
| HORIZ_SR | forex    | 4H   | retest_lvl   | fxvol=high-ATR |        34 |         50   |        0.157 |      34 |       35.3 |      0.319 |     34 |      41.2 |     0.422 |
| HORIZ_SR | forex    | 4H   | retest_lvl   | fxvol=low-ATR  |        89 |         44.9 |        0.029 |      88 |       26.1 |     -0.049 |     89 |      28.1 |    -0.136 |
| HORIZ_SR | forex    | 4H   | retest_swing | fxvol=high-ATR |        34 |         44.1 |       -0.014 |      34 |       29.4 |      0.06  |     34 |      32.4 |     0.697 |
| HORIZ_SR | forex    | 4H   | retest_swing | fxvol=low-ATR  |        89 |         43.8 |       -0.007 |      89 |       24.7 |     -0.114 |     89 |      27   |    -0.144 |
| TRIANGLE | crypto   | 1H   | immediate    | trend=bear     |      2733 |         44.9 |        0.09  |    2663 |       28.5 |      0.106 |   2736 |      48.1 |     0.091 |
| TRIANGLE | crypto   | 1H   | immediate    | trend=bull     |      2931 |         44.5 |        0.079 |    2903 |       28.3 |      0.101 |   2934 |      47.3 |     0.09  |
| TRIANGLE | crypto   | 1H   | immediate    | trend=sideways |      6902 |         40.4 |       -0.032 |    6794 |       24.3 |     -0.068 |   6903 |      42.5 |    -0.043 |
| TRIANGLE | crypto   | 1H   | immediate    | vol=high-vol   |      4074 |         41.5 |        0.006 |    3980 |       26   |      0.006 |   4081 |      44.1 |     0.013 |
| TRIANGLE | crypto   | 1H   | immediate    | vol=low-vol    |      8492 |         42.7 |        0.027 |    8380 |       26.3 |      0.011 |   8492 |      45.2 |     0.019 |
| TRIANGLE | crypto   | 1H   | retest_lvl   | trend=bear     |      1304 |         42.2 |       -0.032 |    1304 |       25.8 |     -0.052 |   1305 |      24.8 |    -0.016 |
| TRIANGLE | crypto   | 1H   | retest_lvl   | trend=bull     |      1403 |         41.1 |       -0.056 |    1400 |       27.9 |      0.033 |   1402 |      26.9 |     0.145 |
| TRIANGLE | crypto   | 1H   | retest_lvl   | trend=sideways |      3251 |         40.1 |       -0.097 |    3249 |       25.4 |     -0.086 |   3251 |      22.3 |    -0.126 |
| TRIANGLE | crypto   | 1H   | retest_lvl   | vol=high-vol   |      1929 |         40.6 |       -0.072 |    1928 |       24.6 |     -0.104 |   1929 |      22.4 |    -0.081 |
| TRIANGLE | crypto   | 1H   | retest_lvl   | vol=low-vol    |      4029 |         40.9 |       -0.073 |    4025 |       26.8 |     -0.025 |   4029 |      24.6 |    -0.018 |
| TRIANGLE | crypto   | 1H   | retest_swing | trend=bear     |      1296 |         42.3 |       -0.036 |    1294 |       25.6 |     -0.07  |   1297 |      23.7 |    -0.051 |
| TRIANGLE | crypto   | 1H   | retest_swing | trend=bull     |      1404 |         40.8 |       -0.071 |    1402 |       28.2 |      0.036 |   1404 |      25.4 |     0.126 |
| TRIANGLE | crypto   | 1H   | retest_swing | trend=sideways |      3228 |         40.4 |       -0.097 |    3223 |       25.3 |     -0.093 |   3228 |      21.7 |    -0.123 |
| TRIANGLE | crypto   | 1H   | retest_swing | vol=high-vol   |      1931 |         40.7 |       -0.077 |    1929 |       25.1 |     -0.088 |   1932 |      21.5 |    -0.104 |
| TRIANGLE | crypto   | 1H   | retest_swing | vol=low-vol    |      3997 |         41   |       -0.078 |    3990 |       26.5 |     -0.042 |   3997 |      23.8 |    -0.022 |
| TRIANGLE | crypto   | 4H   | immediate    | trend=bear     |       721 |         40.1 |       -0.013 |     688 |       18   |     -0.295 |    723 |      41.9 |    -0.047 |
| TRIANGLE | crypto   | 4H   | immediate    | trend=bull     |       764 |         44.6 |        0.101 |     733 |       30.2 |      0.191 |    765 |      44.4 |     0.018 |
| TRIANGLE | crypto   | 4H   | immediate    | trend=sideways |      1442 |         37.8 |       -0.073 |    1416 |       24.3 |     -0.046 |   1440 |      39.4 |    -0.089 |
| TRIANGLE | crypto   | 4H   | immediate    | vol=high-vol   |      1008 |         42.2 |        0.04  |     955 |       24.1 |     -0.051 |   1013 |      41.5 |    -0.042 |
| TRIANGLE | crypto   | 4H   | immediate    | vol=low-vol    |      1919 |         39.1 |       -0.04  |    1882 |       24.4 |     -0.042 |   1915 |      41.3 |    -0.055 |
| TRIANGLE | crypto   | 4H   | retest_lvl   | trend=bear     |       319 |         41.7 |       -0.001 |     314 |       25.5 |     -0.024 |    316 |      22.5 |     0.022 |
| TRIANGLE | crypto   | 4H   | retest_lvl   | trend=bull     |       377 |         40.1 |       -0.04  |     375 |       27.7 |      0.068 |    378 |      25.4 |    -0.003 |
| TRIANGLE | crypto   | 4H   | retest_lvl   | trend=sideways |       663 |         42.8 |        0.019 |     663 |       22   |     -0.171 |    662 |      19.6 |    -0.209 |
| TRIANGLE | crypto   | 4H   | retest_lvl   | vol=high-vol   |       504 |         41.7 |        0.001 |     500 |       25.2 |     -0.033 |    503 |      19.7 |    -0.135 |
| TRIANGLE | crypto   | 4H   | retest_lvl   | vol=low-vol    |       855 |         41.9 |       -0.003 |     852 |       23.9 |     -0.092 |    853 |      23.2 |    -0.076 |
| TRIANGLE | crypto   | 4H   | retest_swing | trend=bear     |       319 |         41.4 |       -0.015 |     317 |       27.1 |      0.035 |    317 |      18.3 |    -0.103 |
| TRIANGLE | crypto   | 4H   | retest_swing | trend=bull     |       377 |         41.6 |       -0.004 |     377 |       27.6 |      0.058 |    378 |      24.6 |     0.033 |
| TRIANGLE | crypto   | 4H   | retest_swing | trend=sideways |       662 |         41.7 |       -0.011 |     662 |       20.7 |     -0.226 |    662 |      18   |    -0.258 |
| TRIANGLE | crypto   | 4H   | retest_swing | vol=high-vol   |       503 |         41   |       -0.02  |     501 |       23.4 |     -0.11  |    503 |      17.1 |    -0.186 |
| TRIANGLE | crypto   | 4H   | retest_swing | vol=low-vol    |       855 |         42   |       -0.004 |     855 |       24.6 |     -0.072 |    854 |      21.5 |    -0.114 |
| TRIANGLE | forex    | 1H   | immediate    | fxvol=high-ATR |       724 |         38.3 |       -0.11  |     712 |       22.9 |     -0.152 |    724 |      40.2 |    -0.142 |
| TRIANGLE | forex    | 1H   | immediate    | fxvol=low-ATR  |      1067 |         38   |       -0.127 |    1044 |       20.9 |     -0.242 |   1063 |      38.2 |    -0.186 |
| TRIANGLE | forex    | 1H   | retest_lvl   | fxvol=high-ATR |       333 |         33.9 |       -0.327 |     332 |       22.3 |     -0.284 |    333 |      20.1 |    -0.35  |
| TRIANGLE | forex    | 1H   | retest_lvl   | fxvol=low-ATR  |       512 |         39.1 |       -0.22  |     512 |       23.8 |     -0.244 |    512 |      23   |    -0.276 |
| TRIANGLE | forex    | 1H   | retest_swing | fxvol=high-ATR |       333 |         33.3 |       -0.354 |     332 |       22.3 |     -0.296 |    333 |      19.5 |    -0.349 |
| TRIANGLE | forex    | 1H   | retest_swing | fxvol=low-ATR  |       512 |         38.1 |       -0.259 |     512 |       23.2 |     -0.282 |    512 |      22.9 |    -0.282 |
| TRIANGLE | forex    | 4H   | immediate    | fxvol=high-ATR |       183 |         40.4 |       -0.018 |     179 |       29.6 |      0.155 |    183 |      47   |     0.043 |
| TRIANGLE | forex    | 4H   | immediate    | fxvol=low-ATR  |       321 |         35.8 |       -0.14  |     307 |       20.2 |     -0.228 |    321 |      38   |    -0.165 |
| TRIANGLE | forex    | 4H   | retest_lvl   | fxvol=high-ATR |        93 |         51.6 |        0.208 |      93 |       33.3 |      0.251 |     93 |      29   |     0.092 |
| TRIANGLE | forex    | 4H   | retest_lvl   | fxvol=low-ATR  |       142 |         34.5 |       -0.234 |     141 |       21.3 |     -0.246 |    141 |      24.1 |    -0.133 |
| TRIANGLE | forex    | 4H   | retest_swing | fxvol=high-ATR |        93 |         44.1 |        0.02  |      93 |       33.3 |      0.251 |     93 |      26.9 |     0.018 |
| TRIANGLE | forex    | 4H   | retest_swing | fxvol=low-ATR  |       142 |         41.5 |       -0.061 |     142 |       23.2 |     -0.17  |    142 |      27.5 |    -0.001 |
| TRIPLE   | crypto   | 1H   | immediate    | trend=bear     |      1964 |         43.3 |        0.058 |    1827 |       23.5 |     -0.083 |   1992 |      59.8 |     0.058 |
| TRIPLE   | crypto   | 1H   | immediate    | trend=bull     |      2162 |         42.3 |        0.034 |    2094 |       25.2 |     -0.016 |   2187 |      58.6 |     0.034 |
| TRIPLE   | crypto   | 1H   | immediate    | trend=sideways |      4924 |         40.3 |       -0.022 |    4765 |       24.1 |     -0.065 |   4954 |      56.7 |    -0.008 |
| TRIPLE   | crypto   | 1H   | immediate    | vol=high-vol   |      3034 |         43.4 |        0.061 |    2865 |       23.4 |     -0.091 |   3069 |      60.3 |     0.063 |
| TRIPLE   | crypto   | 1H   | immediate    | vol=low-vol    |      6016 |         40.4 |       -0.018 |    5821 |       24.7 |     -0.041 |   6064 |      56.5 |    -0.007 |
| TRIPLE   | crypto   | 1H   | retest_lvl   | trend=bear     |       918 |         37.8 |       -0.136 |     918 |       22.3 |     -0.188 |    918 |      26.5 |    -0.092 |
| TRIPLE   | crypto   | 1H   | retest_lvl   | trend=bull     |      1069 |         44.4 |        0.032 |    1068 |       28.1 |      0.044 |   1071 |      30.8 |     0.001 |
| TRIPLE   | crypto   | 1H   | retest_lvl   | trend=sideways |      2274 |         41.3 |       -0.062 |    2274 |       27.1 |     -0.01  |   2274 |      29.5 |    -0.039 |
| TRIPLE   | crypto   | 1H   | retest_lvl   | vol=high-vol   |      1418 |         39   |       -0.104 |    1417 |       22.7 |     -0.173 |   1420 |      28.6 |    -0.073 |
| TRIPLE   | crypto   | 1H   | retest_lvl   | vol=low-vol    |      2843 |         42.5 |       -0.029 |    2843 |       28.2 |      0.034 |   2843 |      29.4 |    -0.024 |
| TRIPLE   | crypto   | 1H   | retest_swing | trend=bear     |       916 |         37.4 |       -0.155 |     916 |       22.6 |     -0.187 |    916 |      25.2 |    -0.126 |
| TRIPLE   | crypto   | 1H   | retest_swing | trend=bull     |      1062 |         42.3 |       -0.027 |    1061 |       25.6 |     -0.059 |   1064 |      28   |    -0.059 |
| TRIPLE   | crypto   | 1H   | retest_swing | trend=sideways |      2258 |         41.4 |       -0.069 |    2258 |       27   |     -0.024 |   2258 |      29   |    -0.021 |
| TRIPLE   | crypto   | 1H   | retest_swing | vol=high-vol   |      1411 |         38.8 |       -0.117 |    1410 |       22.7 |     -0.178 |   1413 |      28.5 |    -0.036 |
| TRIPLE   | crypto   | 1H   | retest_swing | vol=low-vol    |      2825 |         41.7 |       -0.057 |    2825 |       27.2 |     -0.013 |   2825 |      27.7 |    -0.062 |
| TRIPLE   | crypto   | 4H   | immediate    | trend=bear     |       362 |         35.6 |       -0.12  |     326 |       15.3 |     -0.398 |    377 |      55.7 |    -0.006 |
| TRIPLE   | crypto   | 4H   | immediate    | trend=bull     |       492 |         48   |        0.187 |     458 |       31.9 |      0.263 |    497 |      59.4 |     0.079 |
| TRIPLE   | crypto   | 4H   | immediate    | trend=sideways |       921 |         43.6 |        0.078 |     877 |       24.1 |     -0.051 |    923 |      59.2 |     0.063 |
| TRIPLE   | crypto   | 4H   | immediate    | vol=high-vol   |       497 |         42.3 |        0.045 |     453 |       24.5 |     -0.031 |    512 |      60.4 |     0.105 |
| TRIPLE   | crypto   | 4H   | immediate    | vol=low-vol    |      1278 |         43.6 |        0.077 |    1208 |       24.5 |     -0.033 |   1285 |      57.7 |     0.032 |
| TRIPLE   | crypto   | 4H   | retest_lvl   | trend=bear     |       157 |         45.9 |        0.111 |     155 |       22.6 |     -0.133 |    156 |      29.5 |    -0.019 |
| TRIPLE   | crypto   | 4H   | retest_lvl   | trend=bull     |       246 |         41.9 |        0.007 |     246 |       28   |      0.082 |    246 |      30.5 |     0.043 |
| TRIPLE   | crypto   | 4H   | retest_lvl   | trend=sideways |       414 |         39.4 |       -0.064 |     414 |       24.4 |     -0.072 |    414 |      23.9 |    -0.164 |
| TRIPLE   | crypto   | 4H   | retest_lvl   | vol=high-vol   |       245 |         40.4 |       -0.029 |     244 |       22.5 |     -0.138 |    245 |      26.1 |    -0.088 |
| TRIPLE   | crypto   | 4H   | retest_lvl   | vol=low-vol    |       572 |         41.8 |       -0     |     571 |       26.3 |      0.006 |    571 |      27.3 |    -0.068 |
| TRIPLE   | crypto   | 4H   | retest_swing | trend=bear     |       157 |         45.9 |        0.108 |     155 |       23.2 |     -0.11  |    156 |      25.6 |    -0.125 |
| TRIPLE   | crypto   | 4H   | retest_swing | trend=bull     |       247 |         40.1 |       -0.042 |     247 |       27.5 |      0.057 |    247 |      27.1 |    -0.033 |
| TRIPLE   | crypto   | 4H   | retest_swing | trend=sideways |       413 |         39   |       -0.076 |     413 |       24.2 |     -0.082 |    413 |      24.5 |    -0.094 |
| TRIPLE   | crypto   | 4H   | retest_swing | vol=high-vol   |       246 |         42.3 |        0.013 |     245 |       24.1 |     -0.081 |    246 |      24.8 |    -0.068 |
| TRIPLE   | crypto   | 4H   | retest_swing | vol=low-vol    |       571 |         39.9 |       -0.049 |     570 |       25.4 |     -0.03  |    570 |      25.8 |    -0.087 |
| TRIPLE   | forex    | 1H   | immediate    | fxvol=high-ATR |       505 |         41.6 |       -0.009 |     486 |       26.3 |      0.004 |    512 |      54.9 |    -0.062 |
| TRIPLE   | forex    | 1H   | immediate    | fxvol=low-ATR  |       753 |         40   |       -0.053 |     709 |       24   |     -0.095 |    755 |      56   |    -0.04  |
| TRIPLE   | forex    | 1H   | retest_lvl   | fxvol=high-ATR |       239 |         33.9 |       -0.337 |     239 |       24.3 |     -0.214 |    239 |      23.4 |    -0.207 |
| TRIPLE   | forex    | 1H   | retest_lvl   | fxvol=low-ATR  |       365 |         38.6 |       -0.234 |     365 |       26.3 |     -0.147 |    365 |      27.9 |    -0.117 |
| TRIPLE   | forex    | 1H   | retest_swing | fxvol=high-ATR |       239 |         28.9 |       -0.474 |     239 |       20.5 |     -0.375 |    239 |      23   |    -0.166 |
| TRIPLE   | forex    | 1H   | retest_swing | fxvol=low-ATR  |       365 |         35.6 |       -0.327 |     365 |       23.6 |     -0.275 |    365 |      24.1 |    -0.28  |
| TRIPLE   | forex    | 4H   | immediate    | fxvol=high-ATR |        93 |         41.9 |        0.028 |      79 |       29.1 |      0.143 |     94 |      61.7 |     0.089 |
| TRIPLE   | forex    | 4H   | immediate    | fxvol=low-ATR  |       246 |         29.3 |       -0.293 |     234 |       17.5 |     -0.324 |    247 |      47   |    -0.18  |
| TRIPLE   | forex    | 4H   | retest_lvl   | fxvol=high-ATR |        41 |         53.7 |        0.257 |      41 |       36.6 |      0.379 |     41 |      29.3 |     0.097 |
| TRIPLE   | forex    | 4H   | retest_lvl   | fxvol=low-ATR  |       104 |         51.9 |        0.199 |     104 |       27.9 |      0.017 |    104 |      30.8 |     0.04  |
| TRIPLE   | forex    | 4H   | retest_swing | fxvol=high-ATR |        41 |         61   |        0.442 |      41 |       36.6 |      0.381 |     41 |      36.6 |     0.475 |
| TRIPLE   | forex    | 4H   | retest_swing | fxvol=low-ATR  |       104 |         45.2 |        0.027 |     104 |       26   |     -0.064 |    104 |      27.9 |     0.026 |
| WEDGE    | crypto   | 1H   | immediate    | trend=bear     |      6425 |         42.6 |        0.006 |    6330 |       27   |      0.022 |   6432 |      34.6 |     0.039 |
| WEDGE    | crypto   | 1H   | immediate    | trend=bull     |      6656 |         42.5 |        0.006 |    6612 |       26.8 |      0.017 |   6654 |      35.3 |    -0.005 |
| WEDGE    | crypto   | 1H   | immediate    | trend=sideways |     16079 |         39.9 |       -0.072 |   15965 |       25.4 |     -0.054 |  16072 |      32.5 |    -0.065 |
| WEDGE    | crypto   | 1H   | immediate    | vol=high-vol   |      9388 |         40.1 |       -0.055 |    9276 |       25.3 |     -0.046 |   9381 |      33.3 |    -0.053 |
| WEDGE    | crypto   | 1H   | immediate    | vol=low-vol    |     19772 |         41.5 |       -0.028 |   19631 |       26.5 |     -0.009 |  19777 |      33.8 |    -0.016 |
| WEDGE    | crypto   | 1H   | retest_lvl   | trend=bear     |      2024 |         39.8 |       -0.086 |    2020 |       26.3 |     -0.029 |   2022 |      27.2 |    -0.033 |
| WEDGE    | crypto   | 1H   | retest_lvl   | trend=bull     |      2239 |         40.6 |       -0.057 |    2233 |       25.6 |     -0.047 |   2235 |      28.8 |    -0.013 |
| WEDGE    | crypto   | 1H   | retest_lvl   | trend=sideways |      5253 |         40.7 |       -0.072 |    5249 |       26   |     -0.048 |   5253 |      28.6 |    -0.02  |
| WEDGE    | crypto   | 1H   | retest_lvl   | vol=high-vol   |      3027 |         37.9 |       -0.128 |    3018 |       24.4 |     -0.101 |   3023 |      27.2 |    -0.069 |
| WEDGE    | crypto   | 1H   | retest_lvl   | vol=low-vol    |      6489 |         41.7 |       -0.045 |    6484 |       26.8 |     -0.017 |   6487 |      28.9 |     0.001 |
| WEDGE    | crypto   | 1H   | retest_swing | trend=bear     |      2014 |         39.7 |       -0.104 |    2014 |       27.8 |      0.017 |   2014 |      25.3 |    -0.011 |
| WEDGE    | crypto   | 1H   | retest_swing | trend=bull     |      2220 |         40.9 |       -0.059 |    2216 |       25.5 |     -0.065 |   2218 |      26.6 |     0.004 |
| WEDGE    | crypto   | 1H   | retest_swing | trend=sideways |      5176 |         40.2 |       -0.099 |    5174 |       25.7 |     -0.077 |   5176 |      25.7 |    -0.038 |
| WEDGE    | crypto   | 1H   | retest_swing | vol=high-vol   |      3011 |         36.7 |       -0.172 |    3007 |       24.8 |     -0.097 |   3009 |      24.1 |    -0.098 |
| WEDGE    | crypto   | 1H   | retest_swing | vol=low-vol    |      6399 |         41.9 |       -0.053 |    6397 |       26.7 |     -0.034 |   6399 |      26.7 |     0.014 |
| WEDGE    | crypto   | 4H   | immediate    | trend=bear     |      1498 |         40.5 |       -0.017 |    1487 |       23.1 |     -0.103 |   1498 |      34.6 |     0.02  |
| WEDGE    | crypto   | 4H   | immediate    | trend=bull     |      1508 |         43.7 |        0.065 |    1491 |       27.7 |      0.08  |   1502 |      36.8 |     0.097 |
| WEDGE    | crypto   | 4H   | immediate    | trend=sideways |      3808 |         42.5 |        0.028 |    3787 |       27.7 |      0.074 |   3794 |      35   |     0.07  |
| WEDGE    | crypto   | 4H   | immediate    | vol=high-vol   |      2286 |         43.7 |        0.065 |    2249 |       27.4 |      0.07  |   2267 |      37.6 |     0.136 |
| WEDGE    | crypto   | 4H   | immediate    | vol=low-vol    |      4528 |         41.6 |        0.007 |    4516 |       26.4 |      0.02  |   4527 |      34.2 |     0.029 |
| WEDGE    | crypto   | 4H   | retest_lvl   | trend=bear     |       464 |         47   |        0.137 |     464 |       33.6 |      0.308 |    464 |      33   |     0.213 |
| WEDGE    | crypto   | 4H   | retest_lvl   | trend=bull     |       509 |         41.3 |       -0.006 |     507 |       27   |      0.043 |    507 |      28.4 |     0.041 |
| WEDGE    | crypto   | 4H   | retest_lvl   | trend=sideways |      1205 |         40.5 |       -0.032 |    1204 |       26.5 |      0.015 |   1205 |      27.2 |     0.014 |
| WEDGE    | crypto   | 4H   | retest_lvl   | vol=high-vol   |       690 |         45.5 |        0.102 |     687 |       31.9 |      0.239 |    688 |      32.8 |     0.243 |
| WEDGE    | crypto   | 4H   | retest_lvl   | vol=low-vol    |      1488 |         40.5 |       -0.033 |    1488 |       26.4 |      0.012 |   1488 |      26.8 |    -0.02  |
| WEDGE    | crypto   | 4H   | retest_swing | trend=bear     |       464 |         45   |        0.081 |     464 |       32.3 |      0.248 |    464 |      31.5 |     0.219 |
| WEDGE    | crypto   | 4H   | retest_swing | trend=bull     |       509 |         40.9 |       -0.024 |     507 |       28.8 |      0.106 |    507 |      26.4 |     0.1   |
| WEDGE    | crypto   | 4H   | retest_swing | trend=sideways |      1205 |         40.2 |       -0.049 |    1204 |       25.2 |     -0.044 |   1205 |      24.3 |    -0.061 |
| WEDGE    | crypto   | 4H   | retest_swing | vol=high-vol   |       690 |         44.3 |        0.065 |     687 |       31.1 |      0.202 |    688 |      30.2 |     0.208 |
| WEDGE    | crypto   | 4H   | retest_swing | vol=low-vol    |      1488 |         40   |       -0.053 |    1488 |       25.9 |     -0.015 |   1488 |      24.5 |    -0.044 |
| WEDGE    | forex    | 1H   | immediate    | fxvol=high-ATR |      1875 |         40.2 |       -1.678 |    1867 |       25.1 |     -1.681 |   1877 |      32.8 |    -1.603 |
| WEDGE    | forex    | 1H   | immediate    | fxvol=low-ATR  |      3008 |         39.1 |       -0.316 |    2992 |       24.9 |     -0.301 |   3013 |      32   |    -0.235 |
| WEDGE    | forex    | 1H   | retest_lvl   | fxvol=high-ATR |       569 |         40.1 |       -0.172 |     569 |       22.8 |     -0.26  |    569 |      25.5 |    -0.181 |
| WEDGE    | forex    | 1H   | retest_lvl   | fxvol=low-ATR  |       945 |         38.5 |       -0.216 |     945 |       25.4 |     -0.164 |    945 |      25.9 |    -0.241 |
| WEDGE    | forex    | 1H   | retest_swing | fxvol=high-ATR |       569 |         40.9 |       -0.19  |     569 |       23.6 |     -0.272 |    569 |      23.2 |    -0.204 |
| WEDGE    | forex    | 1H   | retest_swing | fxvol=low-ATR  |       945 |         39.3 |       -0.246 |     945 |       26.1 |     -0.182 |    945 |      24.2 |    -0.185 |
| WEDGE    | forex    | 4H   | immediate    | fxvol=high-ATR |       475 |         37.9 |       -0.143 |     469 |       23.5 |     -0.153 |    474 |      29.1 |    -0.145 |
| WEDGE    | forex    | 4H   | immediate    | fxvol=low-ATR  |       792 |         38.5 |       -1.122 |     782 |       23.4 |     -1.166 |    793 |      32.8 |    -1.065 |
| WEDGE    | forex    | 4H   | retest_lvl   | fxvol=high-ATR |       171 |         47.4 |        0.109 |     171 |       31   |      0.164 |    171 |      32.7 |     0.387 |
| WEDGE    | forex    | 4H   | retest_lvl   | fxvol=low-ATR  |       276 |         41.3 |       -0.059 |     275 |       27.6 |      0.014 |    275 |      27.6 |    -0.078 |
| WEDGE    | forex    | 4H   | retest_swing | fxvol=high-ATR |       171 |         39.8 |       -0.104 |     171 |       30.4 |      0.118 |    171 |      26.9 |     0.211 |
| WEDGE    | forex    | 4H   | retest_swing | fxvol=low-ATR  |       276 |         40.2 |       -0.111 |     276 |       23.9 |     -0.16  |    275 |      22.9 |    -0.173 |