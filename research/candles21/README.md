# candles21 — "21 Candlesticks" PDF research

Live since 2026-11-03: the BRK (blk_sig_all_2 + blk_htf_all_2) and PAT-TRIPLE forex (blk_htf_all_0) opposite-pattern blocks run in `app/candles21.py`. See the main README, "Opposite-candle filters".

- `patterns.py` — detectors coded from the PDF:
  - Prior-trend rule: close vs SMA20 and vs the close 10 bars back, checked on the bar before the pattern.
  - Body and shadow ratios.
  - Next-candle confirmation where the PDF asks for it.
  - "~" = gap rule relaxed for 24/7 markets.
- `bt_standalone.py` — part A. Each pattern on 1h, 4h and 1D for 50 crypto coins (sim on 15m bars) and 19 forex pairs (sim on 1H bars).
  - Stop: pattern extreme ± 0.1 ATR, also ×1.5.
  - Target: 3R or 2R.
  - Trend: pdf, or + 200-SMA.
  - Same fees, 0.3% minimum stop and $1M volume gate as stop_variants_3r.
  - Writes out/*.pkl.
- `report_a.py` → `results_a.md` / `results_a.json` / `top_families.json`. Picks use Y1+Y2 only; CANDLE-21 is tested on the Y3 hold-out.
- `filter_b.py` → out/filter_b_rows.pkl. It tags the prev_oct30 trades with same- or opposite-direction patterns on the signal timeframe and the next timeframe up.
- `report_b.py` → `results_b.md` / `results_b.json`.
- `results.md` — summary and recommendations. `results.json` — combined numbers.

Run order, one process at a time (about 1 minute in total):
`python3 bt_standalone.py && python3 report_a.py && python3 filter_b.py && python3 report_b.py`
- `brk_refresh.py` — re-checks the BRK block on the Nov 2026 refresh (`stop_variants_3r/out3y`) → `brk_refresh.json`.
- `parity_live.py` — live filter (`app/candles21.check` on live-sized 4H windows) vs the research filter. It must print `PARITY OK`. Takes about 75 s and handles one symbol at a time.
