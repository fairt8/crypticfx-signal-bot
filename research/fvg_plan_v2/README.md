# FVG creator plan v2 — backtest (research only, no live change)

Question: does the 6-step "HTF liquidity → LTF sweep → FVG/OB/OTE entry" plan beat, or improve, the current FVG-PLAN?

## Rules tested (V2)
1. **4H direction** – confirmed 4H pivots (k=3): last 2 highs AND last 2 lows rising = bull, both falling = bear, otherwise **no trade**. Variant: close vs EMA50 + EMA50 slope.
2. **Equal highs/lows** – two adjacent confirmed pivots within tol (0.05/0.1/0.2%), still untouched. Source 15m (5-day lookback) or 1H (10-day).
3. **Unfilled FVGs** – unfilled 4H FVGs are used as TP targets and as an optional "sweep inside same-direction 4H FVG" filter.
4. **Sweep** – wick beyond the EQ level and close back inside, against the bias (sell-side sweep for longs, buy-side for shorts).
5. **15M FVG confirmation** – first bias-direction 15m FVG within 16 bars, sweep extreme not broken.
6. **SL/TP** – SL = sweep wick ± 0.1×ATR14. TP = nearest liquidity (4H swing / opposing 4H FVG / 15m EQ, 1–10R), 4H-only liquidity, 2R or 3R.
Entries: FVG near edge, OB (last opposite candle), OTE 62% / 70.5%. Optional London/NY session filter. 1536 configs in total.

Conventions match `scripts/backtest_all`: fee 0.001/stop-fraction in R, 48h limit expiry, same-bar SL first, 400-bar follow window, BTC season (200D SMA + slope, day before), $1M rolling 24h volume floor.

## Data
Binance public klines, 30 coins (today's top 30 by volume, stock tokens/stables removed), 15m from 2025-08-17 to 2026-10-29 (~438 days). IS = first 2/3, **OOS = from 2026-06-05**.

## Results (net R after fees)
| Strategy | Trades | Win% | Net R | Avg R | Max DD | IS avg | OOS R (avg) |
|-|-|-|-|-|-|-|-|
| Current FVG-PLAN | 1141 | 27.4 | −42.5 | −0.037 | 120.1 | −0.075 | +19.0 (+0.058) |
| FVG-PLAN + 15m EQ sweep (0.1%, last 4h) | 275 | 29.8 | **+7.9** | +0.029 (90% CI −0.16..+0.21) | **42.5** | −0.042 | +0.207 |
| FVG-PLAN + 4H structure bias | 575 | – | −13.9 | −0.024 | 79 | −0.045 | +0.026 |
| FVG-PLAN + EQ sweep + liquidity TP | 275 | – | +8.4 | +0.031 | 59 | −0.053 | +0.241 |
| FVG-PLAN, TP 2R | 1141 | – | −68.6 | – | – | – | – |
| Full V2 plan (structure bias, 15m EQ 0.1%, FVG entry, liq TP) | 1480 | 29.7 | −121.4 | −0.082 | 173.9 | IS −52.6 | −68.7 |
| Best named V2 (OTE 62% + 3R) | – | – | −54.6 | – | – | – | +3.0 |
| V2 with no 4H bias | – | – | −460 | – | – | – | – |

Walk-forward: the in-sample-best V2 config (+159.7R IS) lost −196.8R OOS; most top-10 IS picks lose OOS; only 24% of configs are OOS-positive → curve-fit noise.
Fees are decisive: V2 gross is +0.044 R/trade but fees cost ~0.126 R/trade (median stop 0.90%).

Seasons: FVG-PLAN bull +13.8 / bear −71.7 / range +15.4; V2 −34.5 / −79.4 / −7.4; FVG-PLAN+EQ sweep +16.2 / −13.9 / +5.6.
Full month and grid tables: `results.md`, `grid.csv`, `results.json`.

## Verdict
- **Do not replace FVG-PLAN with V2** – worse in-sample, out-of-sample and in every season.
- The 4H direction step helps V2 a lot (no bias −460R) but adds little to FVG-PLAN, which already scores 4H structure.
- Only add-on worth watching: **"15m equal-high/low sweep in the 4h before the setup"**. It's better per trade in both halves and cuts DD 120→42R, but it isn't statistically significant and leaves ~19 trades/month. Track it as a paper tag in the monthly backtest; no live change yet.

## Limits
Single 2/3–1/3 split over ~14.5 months; survivorship bias (today's top 30); volume floor approximated from klines; HYPE/XAUT/PUMP have short histories; forex not tested (FVG-PLAN runs crypto-only); open trades marked at 400 bars; my own coding of discretionary rules (EQ tolerance, sweep and OB definitions).

## Run
`python3 fetch.py; W=4 python3 bt.py; python3 report.py` (box only, ~85 MB per worker).
