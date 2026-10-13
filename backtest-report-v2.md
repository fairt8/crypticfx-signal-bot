# Backtest report v2: extra strategies and FVG variants (15m entry), 13 Oct 2026

**Bottom line:** none of the strategies or variants is robustly profitable after costs. A few crypto variants are net-positive in the out-of-sample (OOS) third, but every one of them was net-negative in-sample (IS), and the OOS gains come mostly from longs in that period (FVG longs +0.10R vs shorts −0.17R). That looks like a market regime, not an edge. Forex is negative in every variant. **No new strategy was added to the live app.**

## Data, costs, method (same as v1, now truly 15m)
- 79 Binance USDT pairs (top by 48h volume today, incl. BTC/ETH): 15m + 4h klines, ~92 days. 30 forex/metals via yfinance: 15m (~60 trading days, Yahoo's limit) + 1h→4h.
- Costs: crypto 0.10% round trip (spot taker), FX 0.02%, metals 0.05%. "Futures fees" variant: crypto entry limit maker 0.02% + exit TP maker 0.02% / SL taker 0.05%.
- Fills: live `outcomes.simulate` (limit fill, 48h expiry, 3R/1R, same-candle = SL). The FVG code is the live `strategy.analyze`.
- Split: IS 13 Jul → 13 Sep 2026, OOS 13 Sep → 13 Oct (UTC). Parameters chosen on IS net expectancy only (n ≥ 100), a few grid points each.
- **v1 correction:** the v1 report actually ran on 5m data (see the note added at its top). These are the first true 15m results.

## Strategies
**FVG (live):** 4H FVG → tap → first same-direction 15m FVG; limit entry; SL beyond the 3 candles; TP 3R; crypto stop ≥ 0.3%.
Variants: 2R (comparison only), 4H trend as a hard filter (EMA50>EMA200 aligned), minimum 4H gap size (IS grid 0.2/0.5/1.0% → **0.2%** picked), futures fees.

**CHK: Zerodha Varsity "Grand Checklist" (Ch 18.6), on 1H candles with 4H trend.** Items used (quoted):
1. "The stock should form a recognisable candlestick pattern" → engulfing, hammer/shooting star, morning/evening star, three inside, tweezer, doji variants, marubozu (live `candle_pattern` + marubozu body ≥ 90% of range).
2. "S&R should confirm to the trade. The stoploss price should be around S&R … For a long trade, the low of the pattern should be around the support" → pattern low within X·ATR(14) of a confirmed pivot low (k=5, last 200 bars); mirrored for shorts. IS grid X ∈ {0.5, 1.0} → 0.5.
3. "Volumes should confirm … Ensure above average volumes" → pattern bar volume > 20-bar average (crypto only; FX has no real volume).
4. "Look at the trade from the Dow Theory perspective … Primary, secondary trends" → 4H EMA50>EMA200 and close>EMA50 for longs (mirror for shorts).
5. "Indicators should confirm … If the indicators do not confirm go ahead with the original plan" → RSI/MACD agreement used only as a score (0–2).
6. "RRR should be satisfactory … at least 1.5" → user rule: 3R.
Entry at the pattern-bar close; SL at the pattern low (high) of the last 3 bars (Varsity: "low of the pattern acting as the stoploss"); TP 3R. Min-stop grid {0, 0.3%} → 0.3%.

**SWEEP: liquidity sweep → FVG,** from the creator's transcripts "Liquidity + FVGs = The Most Powerful Setup in Trading" (WYtAtXOLj2U) and "The Liquidity Sweep Strategy Most ICT Traders Get Completely Wrong" (v9LtLfYmtvg), both obtained this time:
- [T] Have the higher-timeframe bias first; trade only with it → 4H EMA trend [I: how bias is measured].
- [T] Liquidity = stops at "the previous high and the previous low" / the previous session's high and low → [I] lowest low (highest high) of the previous N 15m bars, N ∈ {48 (12h), 96 (24h)} → 48 picked.
- [T] Wait for price to sweep it "with a wick or even a candlestick body close".
- [T] Then the first FVG in the trade direction → limit order at the FVG; [I] it must form within 12 bars (3h).
- [T] "Stop loss should be above the old swing high that was swept" → SL at the sweep extreme.
- [T] 3:1 target in the FVG video. Note: the sweep video recommends **2:1** for intraday indices; tested only as a comparison.
- Min-stop grid {0, 0.3%} → 0.3%.

## Results (closed trades; R per trade; net = after costs)
|                                                  |   IS_n |   IS_win |   IS_gross |   IS_net |   IS_maxdd |   OOS_n |   OOS_win |   OOS_gross |   OOS_net |   OOS_net_tot |   OOS_maxdd |
|:-------------------------------------------------|-------:|---------:|-----------:|---------:|-----------:|--------:|----------:|------------:|----------:|--------------:|------------:|
| ('FVG raw (no min stop)', 'crypto')              |   2282 |     26   |      0.039 |   -0.215 |      544.2 |    1279 |      28.5 |       0.138 |    -0.078 |         -99.9 |       214   |
| ('FVG raw (no min stop)', 'forex')               |    279 |     28.3 |      0.133 |   -0.097 |       52.5 |     190 |      24.7 |      -0.011 |    -0.277 |         -52.7 |        62.7 |
| ('FVG live (crypto stop>=0.3%)', 'crypto')       |   1805 |     26.4 |      0.057 |   -0.106 |      247.7 |    1091 |      28.7 |       0.148 |     0.01  |          10.7 |       126.4 |
| ('FVG live (crypto stop>=0.3%)', 'forex')        |    279 |     28.3 |      0.133 |   -0.097 |       52.5 |     190 |      24.7 |      -0.011 |    -0.277 |         -52.7 |        62.7 |
| ('FVG live, 2R (comparison)', 'crypto')          |   1805 |     37   |      0.11  |   -0.053 |      150   |    1093 |      35.2 |       0.057 |    -0.081 |         -88.3 |       153.1 |
| ('FVG live, 2R (comparison)', 'forex')           |    279 |     35.1 |      0.054 |   -0.176 |       57   |     193 |      33.7 |       0.01  |    -0.255 |         -49.3 |        55.9 |
| ('FVG + 4H trend hard filter', 'crypto')         |    937 |     26.8 |      0.072 |   -0.087 |      126.6 |     556 |      31.3 |       0.252 |     0.117 |          65   |        58.8 |
| ('FVG + 4H trend hard filter', 'forex')          |    122 |     25.4 |      0.016 |   -0.213 |       34.2 |     104 |      26   |       0.038 |    -0.236 |         -24.6 |        37.6 |
| ('FVG + 4H gap >=0.2%', 'crypto')                |   1519 |     26.6 |      0.064 |   -0.096 |      189   |     960 |      29.3 |       0.171 |     0.036 |          34.8 |        87.8 |
| ('FVG + 4H gap >=0.2%', 'forex')                 |     67 |     32.8 |      0.313 |    0.097 |       15.9 |      50 |      18   |      -0.28  |    -0.5   |         -25   |        29.8 |
| ('FVG live, futures maker/taker fees', 'crypto') |   1805 |     26.4 |      0.057 |   -0.044 |      152.5 |    1091 |      28.7 |       0.148 |     0.063 |          68.9 |        90.8 |
| ('FVG live, futures maker/taker fees', 'forex')  |    279 |     28.3 |      0.133 |   -0.097 |       52.5 |     190 |      24.7 |      -0.011 |    -0.277 |         -52.7 |        62.7 |
| ('SWEEP lb=48,minstop=0.3%', 'crypto')           |   3247 |     25.3 |      0.01  |   -0.111 |      367.5 |    1496 |      27.1 |       0.083 |    -0.021 |         -31   |       121.4 |
| ('SWEEP lb=48,minstop=0.3%', 'forex')            |    496 |     23.8 |     -0.048 |   -0.302 |      167.8 |     347 |      27.4 |       0.095 |    -0.13  |         -45.2 |        65.3 |
| ('SWEEP, 2R (comparison)', 'crypto')             |   3268 |     34.1 |      0.022 |   -0.099 |      330.4 |    1501 |      35.6 |       0.067 |    -0.036 |         -54.2 |       110.8 |
| ('SWEEP, 2R (comparison)', 'forex')              |    500 |     31.4 |     -0.058 |   -0.31  |      164.4 |     355 |      34.4 |       0.031 |    -0.191 |         -67.8 |        69.8 |
| ('SWEEP, futures fees', 'crypto')                |   3247 |     25.3 |      0.01  |   -0.066 |      219.5 |    1496 |      27.1 |       0.083 |     0.019 |          28   |       114.7 |
| ('SWEEP, futures fees', 'forex')                 |    496 |     23.8 |     -0.048 |   -0.302 |      167.8 |     347 |      27.4 |       0.095 |    -0.13  |         -45.2 |        65.3 |
| ('CHK S/R<=0.5ATR,minstop=0.3%', 'crypto')       |   2111 |     22.4 |     -0.104 |   -0.204 |      470.9 |    1052 |      30.7 |       0.228 |     0.156 |         163.9 |       191.8 |
| ('CHK S/R<=0.5ATR,minstop=0.3%', 'forex')        |   1458 |     16.2 |     -0.353 |   -0.577 |      844.1 |    1098 |      19.6 |      -0.217 |    -0.413 |        -453   |       460.6 |
| ('CHK, 2R (comparison)', 'crypto')               |   2149 |     31.1 |     -0.067 |   -0.167 |      396.8 |    1071 |      39.5 |       0.185 |     0.113 |         121.3 |       131.1 |
| ('CHK, 2R (comparison)', 'forex')                |   1501 |     24.1 |     -0.278 |   -0.498 |      750.5 |    1112 |      27.2 |      -0.183 |    -0.377 |        -419.2 |       425.7 |
| ('CHK, futures fees', 'crypto')                  |   2111 |     22.4 |     -0.104 |   -0.167 |      407.7 |    1052 |      30.7 |       0.228 |     0.184 |         193.7 |       179.3 |
| ('CHK, futures fees', 'forex')                   |   1458 |     16.2 |     -0.353 |   -0.577 |      844.1 |    1098 |      19.6 |      -0.217 |    -0.413 |        -453   |       460.6 |

Parameter grid (IS only):
- FVG min 4H gap IS grid >=0.2%: n=1586, net=-0.088
- FVG min 4H gap IS grid >=0.5%: n=1146, net=-0.124
- FVG min 4H gap IS grid >=1.0%: n=679, net=-0.108
- SWEEP params IS grid lb=48,minstop=0%: n=4003, net=-0.174
- SWEEP params IS grid lb=48,minstop=0.3%: n=3743, net=-0.137
- SWEEP params IS grid lb=96,minstop=0%: n=2222, net=-0.163
- SWEEP params IS grid lb=96,minstop=0.3%: n=2109, net=-0.152
- CHK params IS grid S/R<=0.5ATR,minstop=0%: n=3732, net=-0.556
- CHK params IS grid S/R<=0.5ATR,minstop=0.3%: n=3569, net=-0.356
- CHK params IS grid S/R<=1.0ATR,minstop=0%: n=5063, net=-0.516
- CHK params IS grid S/R<=1.0ATR,minstop=0.3%: n=4854, net=-0.357

## Confidence calibration
**FVG live: OOS win % by score**

| score     |   n |   win |
|:----------|----:|------:|
| (0, 54]   | 329 |  25.8 |
| (54, 64]  | 411 |  28   |
| (64, 74]  | 320 |  31.6 |
| (74, 100] | 221 |  26.7 |

**CHK: OOS win % by score**

| score   |    n |   win |
|:--------|-----:|------:|
| (0, 1]  | 1145 |  24.4 |
| (1, 2]  | 1005 |  25.8 |

**FVG live: OOS by session/direction**

|                  |   n |   win |   gross |    net |   net_tot |   maxdd |
|:-----------------|----:|------:|--------:|-------:|----------:|--------:|
| in_session=False | 548 |  27.4 |   0.095 | -0.077 |     -42.1 |    85.8 |
| in_session=True  | 733 |  28.6 |   0.146 |  0     |       0.1 |   106.7 |
| direction=long   | 640 |  31.2 |   0.25  |  0.102 |      65   |    74.7 |
| direction=short  | 641 |  25   |  -0.002 | -0.167 |    -107   |   171.9 |

**SWEEP: OOS by session/direction**

|                  |    n |   win |   gross |    net |   net_tot |   maxdd |
|:-----------------|-----:|------:|--------:|-------:|----------:|--------:|
| in_session=False |  675 |  26.1 |   0.043 | -0.092 |     -62.4 |   105.8 |
| in_session=True  | 1168 |  27.7 |   0.11  | -0.012 |     -13.8 |    84   |
| direction=long   | 1417 |  28   |   0.121 |  0.017 |      24.1 |   115.5 |
| direction=short  |  426 |  24.2 |  -0.033 | -0.235 |    -100.3 |   122.3 |

**CHK: OOS by session/direction**

|                  |    n |   win |   gross |    net |   net_tot |   maxdd |
|:-----------------|-----:|------:|--------:|-------:|----------:|--------:|
| in_session=False |  732 |  25   |   0     | -0.176 |    -128.7 |   145.1 |
| in_session=True  | 1418 |  25   |   0.001 | -0.113 |    -160.4 |   250.4 |
| direction=long   | 1450 |  24.6 |  -0.018 | -0.12  |    -173.4 |   382.9 |
| direction=short  |  700 |  26   |   0.04  | -0.165 |    -115.8 |   165.2 |
The score still barely separates winners (FVG OOS buckets 25.8 / 28.0 / 31.6 / 26.7%; CHK 24.4 vs 25.8%). The live calibration was refit on these 15m FVG trades: crypto p = 1/(1+e^−(−1.3039 + 0.00523·score)) → about 25–29%; forex flat 26.9% (the fitted slope was negative again).

## Reading the results honestly
- **FVG live** crypto: IS −0.11R, OOS +0.01R per trade, i.e. break-even. Futures-style fees turn OOS to +0.06R but IS is still −0.04R. Forex −0.10 / −0.28.
- **4H trend hard filter** is the best FVG variant OOS (+0.12R net, 31% win, 556 trades) but was −0.09R IS. **Gap ≥0.2%**: −0.10 IS / +0.04 OOS.
- **CHK** crypto flipped from −0.20R IS to +0.16R OOS (gross win 22% → 31%). Forex loses heavily in both (−0.58 / −0.41). A sign flip like that is the typical signature of regime luck.
- **SWEEP** about −0.11 IS / −0.02 OOS crypto; negative forex.
- **2R** didn't beat 3R after costs except FVG IS; it raises the win rate to ~35–37% but not the expectancy.
- Session: in-session trades are modestly better for FVG and SWEEP. Longs beat shorts strongly OOS in FVG/SWEEP: a rising market in Sep–Oct, not a rule to rely on.
- Trades overlap and coins are correlated, so effective sample sizes are much smaller than the counts; the universe is picked by today's volume (survivorship bias); yfinance forex is approximate.

## Live-app decision
The rule was "add only if net-positive OOS". CHK (crypto) and FVG + trend filter (crypto) technically pass that bar, but both lost clearly in-sample. Adding them would just be picking whatever happened to work last month, so I **did not add them**. Recommendation: forward-test (paper trade) the crypto-only "FVG + 4H trend filter" and "CHK" for 4–8 weeks via the bot before trusting either. Changes made: the calibration was refit on the true 15m data; the dashboard header text was corrected to 15m; the v1 report was annotated.

Files: `app/backtest2.py`, `analyze_bt2.py`, `backtest2_trades.csv`, `bt2_tables.md`, `comparison_chart.png`.
