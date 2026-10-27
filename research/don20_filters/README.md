# DON20 entry filters — backtest only (nothing changed live)

Setup: 131 Binance USDT coins (data-api.binance.vision daily, history extended back to ~2021 so 200D trends are known from Feb 2024),
entries 2024-02-01 .. 2026-10-26, live DON20 entry rules (close beyond prior 20D high/low, $1M volume), current exits
(3xATR20 stop, 3xATR chandelier trail, no TP), 0.1%/side fees. Filters use only data known at the signal close.
Walk-forward: in-sample = entries before 2025-07-01, out-of-sample = 2025-07-01 onward.
Live impact uses the 102 live DON20 trades (90 open) pulled from the VM DB (live.json from research/don20_exits, not committed: it has no secrets but is live data).

Run: `python fetch_ext.py` (needs d1/ + syms.json + live.json from ../don20_exits workflow), then `python filters.py > filters_out.txt`.

Note: baseline 2024 is higher than in don20_exits (+172R vs +75R) because the longer history lets trades start on 2024-02-01 instead of ~2024-02-22, catching the Feb–Mar 2024 rally.

## Key results (closed net R)
| variant | trades | win% | net R | avg R | max DD | 2024 | 2025 | 2026 | last120d | OOS R | live open blocked (their R) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| current (no filter) | 2488 | 37.2 | +218.1 | +0.088 | 164.9 | +172.3 | −70.4 | +116.2 | +129.7 | +99.9 | – |
| BTC strict (long bull / short bear) | 1325 | 37.3 | +220.9 | +0.167 | 158.6 | +180.1 | −69.1 | +109.9 | +37.3 | +94.3 | 76 (+13.7) |
| BTC soft (no counter-trend) | 1816 | 34.1 | +115.8 | +0.064 | 252.2 | +85.8 | −125.3 | +155.3 | +82.6 | +138.0 | 76 (+13.7) |
| BTC vs 200D SMA (no slope) | 1744 | 34.3 | +119.1 | +0.068 | 259.4 | +81.7 | −119.1 | +156.5 | +83.8 | +147.4 | 76 (+13.7) |
| coin soft (own 200D+slope) | 2007 | 38.0 | +216.3 | +0.108 | 150.2 | +154.0 | −71.3 | +133.6 | +92.5 | +100.4 | 33 (+3.4) |
| coin vs own 200D SMA | 1950 | 38.7 | +236.2 | +0.121 | 142.6 | +164.3 | −63.7 | +135.7 | +91.9 | +107.2 | 35 (+3.6) |
| stop ≤15% | 504 | 40.1 | +212.8 | +0.422 | 36.9 | +157.4 | −5.7 | +61.0 | +57.3 | +63.4 | 87 (+14.3) |
| stop ≤25% | 1801 | 33.3 | +227.8 | +0.126 | 143.5 | +189.5 | −66.6 | +105.0 | +123.3 | +108.7 | 61 (+8.5) |
| ATR pctl ≤80 | 2334 | 35.3 | +196.8 | +0.084 | 171.3 | +167.4 | −94.1 | +123.5 | +131.2 | +92.5 | 44 (+4.3) |
| coin vs own 200D + stop ≤25% | 1278 | 34.3 | +247.6 | +0.194 | 127.1 | +195.1 | −69.5 | +122.0 | +87.8 | +101.6 | 72 (+11.8) |

Walk-forward: choosing the volatility threshold (or any combo) on the in-sample period always picked a tight stop cap
(≤20% or ≤10%), and every pick then made LESS out of sample than no filter (+22 to +30R vs +99.9R).

## Conclusion
No filter is a clear, robust improvement. Only "coin vs its own 200D SMA" (longs only above, shorts only below) passes
"beats current in most years + out of sample", and the margin is small (+18R over 2.7 years, DD 143 vs 165), it lags
in the last 120 days (+92 vs +130R), and today it would block 35 of 90 open live trades that are net +3.6R.
Volatility caps raise avg R and cut drawdown a lot but lose net R out of sample and would block nearly all current
live signals (live stops are ~29% wide). Recommendation: keep current rules; revisit coin-200D after more live data.
