# Compounding simulation: 7 best setups of the 3-year backtest (research only, no live change)

Trades replayed in real time order: 2023-10-01 → 2026-10-30. Start $1,000. Risk % of the realised balance when each trade opens (compounding); open trades share the balance; PnL realised at exit; net R is after fees. Balance ≤ $0 = blown up.

|Setup|Trades|Net R|Risk|End balance|Return|Max DD|Longest losing streak|Fell below 10% of peak|Worst month|Per-year return|
|-|-|-|-|-|-|-|-|-|-|-|
|DON20, current rules|1220|+270.9|1%|$4,254|+325%|55%|26|no|2024-08 -23%|2023: -0% 2024: +196% 2025: -17% 2026: +74%|
|DON20, current rules|1220|+270.9|10%|**$0 — blown up 2023-10-13** after 12 trades|-100%|100%|12|yes|2023-10 -100%|2023: -100%|
|PAT-WEDGE, 1.5x stop 3R|2265|+107.5|1%|$1,616|+62%|63%|31|no|2024-05 -27%|2023: +7% 2024: +22% 2025: -6% 2026: +31%|
|PAT-WEDGE, 1.5x stop 3R|2265|+107.5|10%|**$0 — blown up 2023-11-09** after 61 trades|-100%|100%|14|yes|2023-11 -100%|2023: -100%|
|BRK, current stop 3R|5093|+67.6|1%|$150|-85%|92%|53|yes|2024-05 -58%|2023: -8% 2024: -27% 2025: -81% 2026: +17%|
|BRK, current stop 3R|5093|+67.6|10%|**$0 — blown up 2024-01-09** after 302 trades|-100%|100%|19|yes|2024-01 -100%|2023: -100% 2024: -100%|
|PAT-TRIPLE forex, current rules|165|+22.4|1%|$1,230|+23%|26%|15|no|2024-12 -5%|2024: -23% 2025: +38% 2026: +15%|
|PAT-TRIPLE forex, current rules|165|+22.4|10%|$1,970|+97%|96%|15|yes|2024-12 -43%|2024: -94% 2025: +1,394% 2026: +133%|
|FVG+TREND, 1h candle stop 3R|4293|+17.1|1%|$325|-68%|91%|32|yes|2026-04 -66%|2023: -10% 2024: +72% 2025: -68% 2026: -34%|
|FVG+TREND, 1h candle stop 3R|4293|+17.1|10%|**$0 — blown up 2024-04-14** after 677 trades|-100%|100%|16|yes|2024-04 -100%|2023: -100% 2024: -100%|
|FVG-PLAN, 1.5x stop 3R|4604|+16.3|1%|$205|-80%|92%|46|yes|2026-04 -61%|2023: +12% 2024: +5% 2025: -66% 2026: -49%|
|FVG-PLAN, 1.5x stop 3R|4604|+16.3|10%|**$0 — blown up 2023-10-26** after 82 trades|-100%|100%|11|yes|2023-10 -100%|2023: -100%|
|MF-REJ forex, current rules|172|+14.9|1%|$1,146|+15%|10%|5|no|2025-08 -4%|2024: +5% 2025: -5% 2026: +14%|
|MF-REJ forex, current rules|172|+14.9|10%|$1,228|+23%|70%|5|no|2025-08 -33%|2024: -2% 2025: -58% 2026: +199%|

Fixed $10 per trade, no compounding (sanity check: end = $1,000 + $10 × net R): DON20, current rules $3,709 (max DD 32%); PAT-WEDGE, 1.5x stop 3R $2,075 (max DD 70%); BRK, current stop 3R **$0 — blown up 2024-06-15** after 908 trades (max DD 100%); PAT-TRIPLE forex, current rules $1,224 (max DD 29%); FVG+TREND, 1h candle stop 3R $1,171 (max DD 78%); FVG-PLAN, 1.5x stop 3R $1,163 (max DD 91%); MF-REJ forex, current rules $1,149 (max DD 10%)

## All 7 in one shared account

|Sizing|Trades|End balance|Return|Max DD|Longest losing streak|Most trades open at once|Max notional / balance|Fell below 10% of peak|Worst month|Per-year return|
|-|-|-|-|-|-|-|-|-|-|-|
|1% compounding|17812|$27|-97%|100%|85|103|171.8×|yes|2025-05 -97%|2023: +2% 2024: +15% 2025: -97% 2026: -14%|
|10% compounding|23|**$0 — blown up 2023-10-02** after 23 trades|-100%|100%|13|27|166.6×|yes|2023-10 -100%|2023: -100%|
|Fixed $10 / trade|17812|$6,167|+517%|86%|85|103|95.0×|no|2023-11 -82%|2023: +26% 2024: +316% 2025: -27% 2026: +60%|
|Fixed $100 / trade|28|**$0 — blown up 2023-10-03** after 28 trades|-100%|100%|18|27|585.4×|yes|2023-10 -100%|2023: -100%|

## Assumptions and caveats
- Same trades, fees and rules as results3y.md (net R per trade after the backtest fee model; no extra slippage or funding).
- Crypto 3R-variant exits are stamped at the close of the 15m exit bar; forex live exits from fx_exits.py (1H / 4H bar close); DON20 at the daily close.
- Trades still open at the follow horizon / end of data are closed at their marked-to-market R (as in results3y.md).
- Risk is a % of the REALISED balance at entry; unrealised PnL of open trades is not counted. Drawdown is on the realised balance at each close.
- No cap on concurrent trades or leverage; 'max notional / balance' shows the position size the stops imply (risk ÷ stop %).
- Signals that the live bot would have skipped (cooldowns, duplicates across strategies on the same coin) are all taken here.
- Backtest on today's top-50 coins (some survivorship), forex 2.77 years (Yahoo 1H limit). Not a forecast.
