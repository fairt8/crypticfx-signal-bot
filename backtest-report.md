> **Correction (added 13 Oct, v2):** because of a bug in my edit, the v1 backtest below ran on **5-minute** entry data (cached 5m klines, 5m yfinance) even though the reasons text says 15m. The confirmation window was 2 bars (10 min), not 30 min. Its numbers describe the 5m variant. The true 15m results and the refitted calibration are in `backtest-report-v2.md`, which supersedes this file.

# Backtest report: 4H FVG + 15m FVG, 1:3 RR (13 Oct 2026)

**Bottom line:** the strategy as coded has **no demonstrated edge**. The win rate is ~25%, which is exactly break-even for 1:3 *before* costs. After an estimated fee/spread every variant tested loses. The confluence-based confidence score does **not** meaningfully predict winners.

## Method
- `app/backtest.py` calls the **live** `strategy.analyze()` (same rules and scoring) walk-forward: at every 15m bar where a 15m FVG completes, it passes only the data known at that moment (last 300 closed 4H bars, last 400 15m bars). Each confirmation is deduplicated.
- Fills via the live `outcomes.simulate()`: limit entry; pending expires after 48h; TP 3R / SL 1R; **if TP and SL fall in the same candle, it counts as SL**; the fill candle can also stop out. Horizon 100h.
- Costs (assumptions): crypto 0.10% round trip, FX 0.02%, gold/silver 0.05%, converted to R via each trade's stop distance.
- Universe: top 79 Binance USDT pairs by 48h volume (incl. BTC, ETH), 15m + 4h klines, 11 Jul–13 Oct 2026 (~92 days). Forex: 30 yfinance instruments, 15m data 23 Jul–13 Oct (~82 days; Yahoo caps 15m history at 60 trading days); 4H built from 1h; gold/silver use futures. FX strength ranking rebuilt hourly from 1h closes (an approximation of the live calc).
- These results come from runs **before** the new 0.3% crypto minimum stop was added (that filter is analysed below).
- Caveats: signals overlap in time and are correlated across coins, so the counts overstate independence; R is per trade with no position limits; DD = max drawdown of cumulative net R in signal order; the universe is chosen with today's volume ranking (survivorship bias).

## Headline (closed trades)
| | trades | win % | gross exp. (R) | net exp. (R) | net total R | max DD (R) | median stop |
|---|---|---|---|---|---|---|---|
| all | 5214 | 25.4 | +0.016 | −0.366 | −1908 | 1908 | 0.32% |
| crypto | 4628 | 25.5 | +0.019 | −0.367 | −1700 | 1701 | 0.36% |
| crypto, stop ≥0.3% | 2739 | 26.1 | +0.043 | −0.146 | −399 | 416 | 0.54% |
| forex+metals | 586 | 24.7 | −0.010 | −0.356 | −209 | 211 | 0.07% |

Unfilled/expired: 125 signals; still open at the end: 37 (excluded).


### Overall by market

|        |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:-------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| all    |      5376 |     5214 |        125 |         37 |  25.4 |       0.016 |    -0.366 |     -1908.2 |    1908.2 |      0.318 |
| crypto |      4753 |     4628 |         98 |         27 |  25.5 |       0.019 |    -0.367 |     -1699.7 |    1700.8 |      0.358 |
| forex  |       623 |      586 |         27 |         10 |  24.7 |      -0.01  |    -0.356 |      -208.5 |     211.2 |      0.069 |

### crypto: by confidence bucket

|       |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| <55   |      1323 |     1289 |         30 |          4 |  23.8 |      -0.047 |    -0.438 |      -564.4 |     569.8 |      0.354 |
| 55-64 |      1482 |     1450 |         27 |          5 |  24.8 |      -0.007 |    -0.398 |      -576.4 |     588.6 |      0.349 |
| 65-74 |      1095 |     1065 |         18 |         12 |  28.4 |       0.134 |    -0.247 |      -262.8 |     269.7 |      0.363 |
| 75+   |       853 |      824 |         23 |          6 |  25.5 |       0.019 |    -0.359 |      -296   |     296.9 |      0.383 |

### crypto: in vs outside London/NY session

|       |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| False |      2086 |     2041 |         39 |          6 |  24.3 |      -0.03  |    -0.438 |      -894.3 |     894.3 |      0.337 |
| True  |      2667 |     2587 |         59 |         21 |  26.4 |       0.058 |    -0.311 |      -805.3 |     816.1 |      0.379 |

### crypto: long vs short

|       |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| long  |      2428 |     2356 |         62 |         10 |  26.2 |       0.048 |    -0.323 |      -761.2 |     777   |      0.377 |
| short |      2325 |     2272 |         36 |         17 |  24.7 |      -0.011 |    -0.413 |      -938.4 |     947.9 |      0.34  |

### crypto: minimum stop distance filter

|        |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:-------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| >=0%   |      4753 |     4628 |         98 |         27 |  25.5 |       0.019 |    -0.367 |     -1699.7 |    1700.8 |      0.358 |
| >=0.3% |      2827 |     2739 |         65 |         23 |  26.1 |       0.043 |    -0.146 |      -398.8 |     416.1 |      0.538 |
| >=0.5% |      1567 |     1515 |         32 |         20 |  25.4 |       0.017 |    -0.113 |      -170.9 |     175.9 |      0.747 |
| >=1.0% |       459 |      432 |         11 |         16 |  23.8 |      -0.046 |    -0.119 |       -51.3 |      78.3 |      1.334 |

### forex: by confidence bucket

|       |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| <55   |        98 |       88 |          5 |          5 |  19.3 |      -0.227 |    -0.581 |       -51.2 |      54.7 |      0.068 |
| 55-64 |       167 |      161 |          5 |          1 |  31.7 |       0.267 |    -0.095 |       -15.3 |      25.5 |      0.072 |
| 65-74 |       180 |      169 |          9 |          2 |  25.4 |       0.018 |    -0.322 |       -54.5 |      56.5 |      0.07  |
| 75+   |       178 |      168 |          8 |          2 |  20.2 |      -0.19  |    -0.522 |       -87.6 |      90.3 |      0.068 |

### forex: in vs outside London/NY session

|       |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| False |       278 |      263 |          8 |          7 |  26.6 |       0.065 |    -0.314 |       -82.7 |      85.6 |      0.064 |
| True  |       345 |      323 |         19 |          3 |  23.2 |      -0.071 |    -0.39  |      -125.9 |     129.9 |      0.071 |

### forex: long vs short

|       |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| long  |       312 |      287 |         19 |          6 |  25.8 |       0.031 |    -0.296 |       -84.9 |      88.9 |      0.069 |
| short |       311 |      299 |          8 |          4 |  23.7 |      -0.05  |    -0.414 |      -123.7 |     123.7 |      0.069 |

### forex: minimum stop distance filter

|        |   signals |   trades |   unfilled |   open_end |   win |   gross_exp |   net_exp |   net_total |   maxdd_r |   med_risk |
|:-------|----------:|---------:|-----------:|-----------:|------:|------------:|----------:|------------:|----------:|-----------:|
| >=0%   |       623 |      586 |         27 |         10 |  24.7 |      -0.01  |    -0.356 |      -208.5 |     211.2 |      0.069 |
| >=0.3% |        32 |       27 |          2 |          3 |  22.2 |      -0.111 |    -0.21  |        -5.7 |      16.1 |      0.408 |
| >=0.5% |         9 |        7 |          1 |          1 |  14.3 |      -0.429 |    -0.497 |        -3.5 |       6.4 |      0.662 |
| >=1.0% |         1 |        1 |          0 |          0 |   0   |      -1     |    -1.029 |        -1   |       1   |      1.704 |

### Win rate with / without each confluence factor (closed trades, all markets)

|                   |   n_with |   win_with |   n_without |   win_without |
|:------------------|---------:|-----------:|------------:|--------------:|
| trend EMA         |     2688 |       25   |        2526 |          25.9 |
| HH/HL aligned     |     1472 |       25   |        3742 |          25.5 |
| structure against |     1419 |       25.9 |        3795 |          25.2 |
| S/R               |     3262 |       26.1 |        1952 |          24.1 |
| RSI ok            |     4758 |       25.5 |         456 |          24.1 |
| MACD              |     2686 |       25.3 |        2528 |          25.5 |
| candle            |      659 |       22.8 |        4555 |          25.8 |
| Fib               |     1694 |       27.2 |        3520 |          24.5 |
| volume            |      694 |       26.9 |        4520 |          25.2 |
| session           |     2910 |       26.1 |        2304 |          24.5 |
| priority          |       81 |       21   |        5133 |          25.5 |
| bias agrees       |      441 |       24.9 |        4773 |          25.4 |

## Does higher confidence win more?
Not reliably. Crypto buckets: 23.8 / 24.8 / **28.4** / 25.5% (non-monotonic). Forex: 19.3 / 31.7 / 25.4 / 20.2%. Every single confluence factor shifts the win rate by ≤ ±3 points (Fib 50–78.6% +2.7, S/R +2.0, session +1.6; candlestick pattern −3.0). On a time split (first 2/3 train, last 1/3 test), a logistic fit of win ~ score predicted 23–27% on the test set, and the test quartiles were not monotone. Treat the score as a description, not an edge.

## Session, direction
- Crypto: in London/NY 26.4% vs outside 24.3% (small help). Forex: in session 23.2% vs outside 26.6% (the opposite, small sample).
- Long slightly better than short in both (26.2 vs 24.7 crypto; 25.8 vs 23.7 FX), within noise.

## Minimum stop distance
The creator's stop (beyond the 3 FVG candles) is very tight on 15m, so fees eat 0.3–0.4R per trade. Requiring a crypto stop ≥0.3% cut the net loss per trade from −0.37R to −0.15R; it held on the time split (train −0.14, test −0.16). ≥0.5% gives −0.11R. The gain is mechanical (cost ÷ risk), not curve-fit, but it is **still negative**. For forex the median stop is 0.07%; filters left too few trades and train/test disagreed, so no forex filter was applied.

## Changes applied to the live app
1. **Min stop 0.3% for crypto** (`MIN_STOP_PCT_CRYPTO`, env-configurable); none for forex.
2. **Confidence recalibrated** to the observed win probability: `p = 1/(1+exp(-(a + b·raw)))`, crypto a=−1.5335, b=0.00785 (raw 45→24%, 90→30%); forex flat 25% (the fitted slope was negative, i.e. noise). The raw setup score is kept in the reasons list. The dashboard and Telegram now say "Est. win probability", with break-even at 25% before fees.
3. Entry timeframe is 15m (user request); confirmation must be ≤2 bars (30 min) old; pending expiry is 48h.

## What might actually help (untested ideas, not applied)
A fixed 2R target instead of 3R, a minimum 4H FVG size, a higher-timeframe trend filter as a hard rule rather than a score, liquidity-sweep prerequisites (the creator's other videos), or maker-fee limit orders. Each needs its own out-of-sample test; tuning on these same 3 months would overfit.

Files: `backtest_trades.csv` (every simulated signal), `equity_curve.png`, `analyze_bt.py`.
