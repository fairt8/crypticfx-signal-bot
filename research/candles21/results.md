# 21 Candlesticks — research summary (Nov 3 2026)

Full tables: `results_a.md` (standalone patterns) and `results_b.md` (filters on existing strategies). Net R after fees.

## A) Patterns as a standalone strategy — no edge
- Over all patterns, the base config (stop beyond the pattern extreme, 3R) loses money in every market and timeframe:

  | Market | 1h avg R | 4h avg R | 1D avg R |
  |-|-|-|-|
  | Crypto (pdf trend) | −0.085 | −0.040 | −0.041 |
  | Forex | −0.255 | −0.142 | −0.072 |

  The best block is crypto 4h with the 200-SMA filter, at about break-even (+0.008R per trade on 21.9k trades).
- In-sample selection used Y1 and Y2 only: both years positive, in-sample average ≥ +0.10R, and a minimum trade count. It picked 35 pattern×timeframe×config combinations. Only **16 of the 35 were positive in the 12-month hold-out**, about what a coin flip would give.
- CANDLE-21, the combination of all picks, failed out of sample:

  | Market | Trades | In-sample R (Y1 / Y2) | Hold-out Y3 R |
  |-|-|-|-|
  | Crypto | 8159 | +339 / +574 | **−36.8** (2835 trades) |
  | Forex | 1421 | +102 / +125 | **−0.6** (531 trades) |

- These held up out of sample, but they were noticed after the fact and are not a validated strategy:

  | Pattern | Market & timeframe | Config | Net R | Y3 R |
  |-|-|-|-|-|
  | GRAVESTONE | crypto 4h | pdf/x1/3R | +84.6 | +14.8 |
  | 3-LINE-STRIKE bear | crypto 4h | sma200/x1.5/3R | +44.1 | +10.9 |
  | EVENING_STAR~ | crypto 4h | sma200/2R | +66 | +15.7 |
  | Marubozu (follow-through) | crypto 1h | sma200/x1.5/3R | +210 per side | +54 per side |
  | SQUEEZE_ALERT | forex 4h | — | +49 | +24.7 |

## B) Pattern filter on existing strategies (baseline = prev_oct30 3-year trades)

| Strategy | Baseline: trades / win% / net / Y1 / Y2 / Y3 | Best filter: trades / win% / net / Y1 / Y2 / Y3 | Verdict |
|-|-|-|-|
| **BRK (cur, 3R)** | 5093 / 26.8 / +67.6 / −28.2 / +40.5 / +55.4 | **Block both** (opposite pattern on the 4h entry candle or 2 before, OR on the last 3 daily candles): 3272 / 27.7 / **+159.6** / +40.5 / +54.7 / +64.4 | **Improves.** Every year is positive (2023 +20, 2024 +29, 2025 +31, 2026 +80). It also works on BRK live (+55.6→+151.6), w1.5 (−20→+192) and w2 (−10→+147). A random drop of the same number of trades beats it only 2.7% of the time. |
| DON20 (live) | 1220 / 38.9 / +270.9 / +83 / +129 / +58 | Requiring a pattern leaves only 96–212 trades: average R rises to +0.5–0.6, but net falls to +48…+127. Blocking: about −9R. | **No change.** |
| MF-REJ forex (live) | 172 / 64.0 / +14.9 / +1.8 / −2.1 / +15.2 | blk_sig_2: 127 / 66.1 / +20.6, Y3 +14.1 | Small sample; no meaningful gain. |
| PAT-TRIPLE forex (live) | 165 / 49.1 / +22.4 / −17.3 / +13.3 / +26.3 | Block opposite on the last daily candle: 157 / 51.0 / +28.9 / −16.2 / +15.5 / +29.6 | Slightly better in every block, but only 8 trades are removed. Optional. |
| PAT-WEDGE (w1.5) | 2265 / 27.8 / +107.5 | Every filter is within ±5R, or worse. | No change. |
| CHK (live) | 14038 / −1117.9 | The best filter, a 4h same-direction pattern (req_htf_0), gives 1045 trades / −26.5. | Still negative; a filter does not rescue CHK. |
| FVG-D1 (live) | 2014 / −164.7 | req_htf_0: 160 trades / +2.3 | Break-even at best; no. |
| FVG-PLAN (w1.5) | 4604 / +16.3 | blk_sig_0: 4536 / +37.7, all blocks ≥ base | Noise-level gain. |
| PAT-TRIPLE crypto (w2) | 938 / +41.6 / Y3 −35.4 | Requiring a pattern leaves 37 trades / +25.3 | Too few trades. |
| FVG+TREND (c60) | 4293 / +17.1 / Y3 +37.7 | Some filters raise net R but lower Y3. | No. |

## Recommendations
1. **Do not launch CANDLE-21.** It made money in-sample and lost in the hold-out. Patterns on their own add nothing over 3 years.
2. **BRK + opposite-pattern block** (4h entry candle plus the 2 before, and the last 3 daily candles) is the one robust finding. Paper/shadow-test it before any live change.
3. Keep DON20, MF-REJ and PAT-WEDGE unchanged. The PAT-TRIPLE forex block on the last daily candle is optional: it is small but consistent.

## Caveats
- **PDF gap rules almost never trigger on 24/7 crypto.** Piercing, dark cloud, kicker, star and abandoned-baby gaps rarely occur, so "~" versions with the gap rule relaxed are also reported.
- **Many tests were run:** about 60 patterns × 3 timeframes × 8 configs in A, and 18 filters × 10 strategies in B. Some "wins" are expected by chance; the hold-out and sibling-variant checks are the guard.
- **No portfolio overlap control in A.** It runs one trade per symbol, pattern and config, and duplicates across patterns are removed for CANDLE-21.
- **Data:** forex is Yahoo 1H from 2024-01 (about 2.8 years); CHK only starts 2024-12. Stops are filled at the candle close, and when SL and TP fall in the same bar the trade counts as a stop-out.
