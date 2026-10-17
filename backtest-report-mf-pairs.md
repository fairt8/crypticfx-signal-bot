# MF-REJ pair expansion (one-home-currency rule)

Home currencies: Asian JPY AUD NZD CNH | London GBP EUR CHF | NY USD CAD; gold/silver have no home (USD/GBP/EUR leg decides). Candidate = exactly one currency at home. Universe: forex.FOREX_30 + CNH pairs with yfinance 1H data + synthetic XAUGBP/XAUEUR (GC=F / GBPUSD|EURUSD, wide highs/lows; bt_mfs/xau_cross.py).
Rules: exact live strong-zone MF-REJ (body Daily+4H bias, strong zone = 2+ 1H touches or 4H/Daily level, pad 0.5 ATR, next-zone TP ≥ 0.5R), 2 signals/day/pair. 1H 2024-10-15 → 2026-10-15, Y1 to 2025-10-15. Costs 0.02% USD majors, 0.03% crosses + CNH, 0.05% metals. Keep: R/trade ≥ −0.05 and not negative in both years.
User 2026-10-17: EURJPY removed and XAUUSD NY removed (blocked also for the dynamic strong pair; previously EURJPY Asian 8/−0.41R, London 6/−0.47R; XAUUSD NY 7/−0.71R).

## Top5 (designated)

|Pair|Session|n (2y)|Win%|Net R|R/trade|Y1 n/win/R|Y2 n/win/R|
|-|-|-|-|-|-|-|-|
|USDJPY|Asian|11|64|+0.96|+0.09|8/62%/+0.78|3/67%/+0.18|
|USDJPY|NY|7|71|+1.36|+0.19|5/80%/+2.34|2/50%/-0.98|
|GBPJPY|London|4|75|+2.46|+0.61|2/50%/+0.44|2/100%/+2.02|
|GBPJPY|NY|5|80|+0.28|+0.06|2/50%/-0.75|3/100%/+1.02|
|EURUSD|London|5|80|+4.80|+0.96|2/50%/+3.51|3/100%/+1.29|
|XAUUSD|London|12|50|-1.49|-0.12|4/0%/-5.04|8/75%/+3.55|

## Added

|Pair|Session|n (2y)|Win%|Net R|R/trade|Y1 n/win/R|Y2 n/win/R|
|-|-|-|-|-|-|-|-|
|AUDUSD|NY|5|80|+1.54|+0.31|1/0%/-1.11|4/100%/+2.65|
|NZDUSD|Asian|8|62|+0.22|+0.03|4/75%/+1.65|4/50%/-1.42|
|EURAUD|Asian|13|69|-0.01|-0.00|6/50%/-2.54|7/86%/+2.53|
|EURCAD|NY|3|100|+2.38|+0.79|2/100%/+1.63|1/100%/+0.75|
|EURNZD|London|7|86|+1.29|+0.18|3/100%/+1.03|4/75%/+0.25|
|GBPNZD|Asian|6|83|+0.20|+0.03|3/100%/+0.77|3/67%/-0.56|
|AUDCAD|Asian|3|67|-0.00|-0.00|1/0%/-1.06|2/100%/+1.05|
|NZDCAD|Asian|5|80|+0.90|+0.18|0/-%/+0.00|5/80%/+0.90|
|CADCHF|London|3|67|+0.06|+0.02|2/50%/-0.84|1/100%/+0.90|
|CADCHF|NY|3|100|+1.86|+0.62|2/100%/+1.14|1/100%/+0.72|
|GBPCNH|Asian|13|77|-0.10|-0.01|9/78%/-0.12|4/75%/+0.02|

## Excluded

|Pair|Session|n (2y)|Win%|Net R|R/trade|Y1 n/win/R|Y2 n/win/R|
|-|-|-|-|-|-|-|-|
|GBPUSD|London|4|50|-1.01|-0.25|4/50%/-1.01|0/-%/+0.00|
|GBPUSD|NY|6|50|-0.32|-0.05|5/60%/+0.77|1/0%/-1.09|
|USDCHF|London|0|-|-|-|-|-|
|USDCHF|NY|6|50|-0.84|-0.14|4/75%/+1.60|2/0%/-2.44|
|AUDUSD|Asian|6|50|-1.93|-0.32|1/0%/-1.18|5/60%/-0.75|
|NZDUSD|NY|3|67|-0.33|-0.11|1/0%/-1.15|2/100%/+0.82|
|EURAUD|London|7|57|-0.58|-0.08|4/50%/-0.81|3/67%/+0.23|
|EURCAD|London|6|50|-1.28|-0.21|4/25%/-3.21|2/100%/+1.94|
|EURNZD|Asian|13|38|-6.18|-0.48|8/38%/-3.89|5/40%/-2.29|
|GBPAUD|Asian|7|29|-5.83|-0.83|3/33%/-2.30|4/25%/-3.54|
|GBPAUD|London|3|33|-2.01|-0.67|1/0%/-1.20|2/50%/-0.81|
|GBPCAD|London|5|60|-1.56|-0.31|2/50%/-0.82|3/67%/-0.74|
|GBPCAD|NY|5|40|-2.30|-0.46|2/100%/+1.24|3/0%/-3.54|
|GBPNZD|London|3|33|-2.32|-0.77|1/0%/-1.28|2/50%/-1.04|
|AUDCAD|NY|2|0|-2.29|-1.14|0/-%/+0.00|2/0%/-2.29|
|AUDCHF|Asian|7|14|-6.46|-0.92|3/33%/-1.89|4/0%/-4.57|
|AUDCHF|London|5|20|-3.67|-0.73|2/50%/-0.28|3/0%/-3.39|
|NZDCAD|NY|2|0|-2.54|-1.27|0/-%/+0.00|2/0%/-2.54|
|NZDCHF|Asian|6|17|-5.39|-0.90|5/20%/-4.20|1/0%/-1.19|
|NZDCHF|London|3|0|-3.64|-1.21|3/0%/-3.64|0/-%/+0.00|
|CADJPY|Asian|9|44|-4.92|-0.55|4/25%/-3.46|5/60%/-1.46|
|CADJPY|NY|6|17|-5.92|-0.99|2/50%/-0.67|4/0%/-5.25|
|CHFJPY|Asian|13|54|-2.27|-0.17|10/50%/-1.91|3/67%/-0.37|
|CHFJPY|London|5|40|-2.86|-0.57|3/33%/-2.40|2/50%/-0.47|
|XAGUSD|NY|0|-|-|-|-|-|
|USDCNH|Asian|11|36|-9.45|-0.86|0/-%/+0.00|11/36%/-9.45|
|USDCNH|NY|6|33|-5.67|-0.94|5/40%/-3.81|1/0%/-1.85|
|EURCNH|Asian|7|43|-1.53|-0.22|4/75%/+2.72|3/0%/-4.25|
|EURCNH|London|4|25|-3.10|-0.77|3/33%/-1.83|1/0%/-1.26|
|GBPCNH|London|6|33|-6.47|-1.08|3/33%/-3.10|3/33%/-3.38|
|CHFCNH|Asian|7|29|-6.40|-0.91|4/25%/-3.14|3/33%/-3.27|
|CHFCNH|London|8|38|-3.84|-0.48|2/50%/-0.04|6/33%/-3.80|
|CADCNH|Asian|21|43|-9.42|-0.45|5/80%/+3.39|16/31%/-12.81|
|CADCNH|NY|9|56|-2.37|-0.26|4/50%/-1.49|5/60%/-0.88|
|XAUGBP|London|21|52|-3.06|-0.15|5/0%/-6.11|16/69%/+3.05|
|XAUEUR|London|19|37|-8.86|-0.47|6/50%/-1.53|13/31%/-7.33|
