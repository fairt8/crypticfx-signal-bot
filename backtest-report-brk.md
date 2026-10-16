# BRK and PAT-* live-code backtest (research; signals run live as EXPERIMENTAL – paper)

Same code the live scan uses (`app/patterns_live.py`, `bt_brk.py`): 2y Oct 2024–Sep 2026, 4H, 44 Binance coins + 7 FX majors, EURJPY, GBPJPY, XAUUSD.
Costs 0.1% crypto, 0.02% majors, 0.03% JPY crosses, 0.05% XAU; crypto stops <0.3% dropped; one signal per symbol/strategy/bar; same-bar stop+target = loss.
IS = Oct 2024–Sep 2025, OOS = Oct 2025–Sep 2026.

BRK = fresh 4H close beyond a strong horizontal body S/R level (2+ body pivots within 0.25 ATR, mf.py zone logic) or a pattern neckline/trendline,
volume > 20-bar avg (Yahoo FX has no volume -> filter skipped), close in outer 30% of candle; crypto immediate entry, forex retest entry; stop level ∓ 0.5 ATR.

| strategy | market | half | n | win% 1:1.5 | R/tr 1:1.5 | win% 1:3 | R/tr 1:3 |
|---|---|---|---|---|---|---|---|
| BRK | crypto | IS | 8648 | 41.3 | -0.022 | 27.5 | +0.045 |
| BRK | crypto | OOS | 8640 | 40.2 | -0.059 | 26.0 | -0.024 |
| BRK | forex | IS | 1458 | 40.3 | -0.079 | 25.7 | -0.057 |
| BRK | forex | OOS | 1436 | 40.4 | -0.100 | 25.4 | -0.093 |
| PAT-WEDGE | crypto | IS | 770 | 38.8 | -0.067 | 25.5 | -0.020 |
| PAT-WEDGE | crypto | OOS | 831 | 42.1 | +0.006 | 29.0 | +0.113 |
| PAT-TRIPLE | forex | IS | 49 | 46.9 | +0.098 | 28.6 | +0.067 |
| PAT-TRIPLE | forex | OOS | 76 | 59.2 | +0.374 | 32.9 | +0.210 |
| PAT-CUP | crypto | IS | 33 | 51.5 | +0.250 | 33.3 | +0.296 |
| PAT-CUP | crypto | OOS | 36 | 36.1 | -0.143 | 22.2 | -0.157 |

BRK split: crypto pattern-neckline breaks IS +0.071R / OOS +0.032R at 1:1.5 (n 870/1001), but horizontal-level breaks (90% of BRK) lose (-0.033/-0.071R).

**Verdict:** BRK does not have an edge (crypto ≈ break-even at 1:3, forex losing). Once overlapping signals are deduped to one per coin/bar, PAT-WEDGE is slightly negative in IS and PAT-CUP is negative in OOS. Only PAT-TRIPLE (FX) stays positive in both halves, and its sample is small. All four run as EXPERIMENTAL – paper only.

Replay of the live functions bar-by-bar, Jul–Sep 2026 (54 symbols, 300-bar 4H window): BRK 2,380, PAT-WEDGE 228, PAT-TRIPLE 15, PAT-CUP 7 signals (before the live cap of 3 per strategy per scan). Cost about 0.065 s per symbol per scan.

## Live setting (16 Oct 2026)
BRK limited to crypto neckline/trendline breaks (`BRK_MARKETS=crypto`, `BRK_LEVELS=pattern`). 1:3: IS n=869, 26.8% win, +0.034R; OOS n=989, 27.9%, +0.069R. 1:1.5: IS n=870, 44.4%, +0.071R; OOS n=1001, 43.2%, +0.032R. Neither target is better in both halves, so 1:3 is tracked (higher pooled net R: +0.053 vs +0.050). Confidence 27%.

Update 16 Oct 2026: live = PAT-TRIPLE + BRK (crypto neckline/trendline only). PAT-WEDGE and PAT-CUP are off by default (`PAT_ENABLED=PAT-TRIPLE`).
