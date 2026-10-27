# DON20 exit research (2026-10-27, backtest only — live exits unchanged)
- fetch.py: top-150 Binance USDT coins by 24h quote volume (>$1M, no stablecoins / tokenised stocks), 1000 daily bars (data-api.binance.vision); kept 131 still trading.
- sim.py: DON20 entry exactly as live (close beyond prior 20-day high/low, entry at signal close, initial stop 3xATR(20), $1M daily volume floor, one position per coin), exit variants, 0.10%/side fees as don20._r. Daily bars: stop-first when stop and target touch the same bar, gaps fill at the open. Trades from 2024-02-01; season = BTC 200D SMA + 20d slope (same rule as backtest_all). Max DD = peak-to-trough of realised net R summed by exit day.
- live_mfe.py: run on the server against the live don20 table (MFE/MAE from daily highs/lows).
- out.txt: results.
