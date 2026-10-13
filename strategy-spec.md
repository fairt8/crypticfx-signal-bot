# Trade Signal Generator: Strategy Spec (v0.1, draft for review)

Labels: **[T]** = taken from a video transcript · **[PDF]** = from the PDF · **[I]** = my own inference or a coding decision (needs confirmation)

## 1. Sources actually used
**YouTube, @AtifHussainOG** (I listed 335 channel videos with yt-dlp; ~15 have FVG in the title.)
Transcripts I actually got (YouTube auto-captions):
- "4H FVG + 5M FVG = Profitability": https://www.youtube.com/watch?v=FXcb5zLbgT4
- "I Backtested FVGs 500 Times… The Results Changed Everything": https://www.youtube.com/watch?v=qiknUGADPIs

Titles only. I tried these, but YouTube blocked the caption download with its "sign in to confirm you're not a bot" check:
- Every Trader Should Know This 4H FVG Strategy (-EEoeVVaO6M)
- I Built a Stupidly Simple 4H FVG Strategy (0QO-vB0MjUw)
- Become Profitable: 4H FVG + 5M FVG (eLI8BPFKFSI)
- Unfortunately, You Need to Know This FVG Trading Strategy (yg94t7WigEw)
- Once You Understand Fair Value Gaps, Trading Becomes... (F4OFeC3thEY)
- Liquidity + FVGs = The Most Powerful Setup in Trading (WYtAtXOLj2U)
- Not attempted: The 4H + 15M FVG Strategy That Actually Works on Gold (DbrXjAgG8lM), The Dark Side of FVG Trading (aeMzsu8L0qE), Order Blocks vs FVGs (-378Z2OUjYo)

Both transcripts point viewers to a free PDF trading plan in the creator's pinned comment. I could not get that PDF.

**PDF provided:** Zerodha Varsity, "Module 2 – Technical Analysis" (19 chapters: candlesticks, S&R, volume, moving averages, RSI/MACD/Bollinger, Fibonacci, Dow theory, the "Grand Checklist", RRR).

## 2. FVG definition
- An FVG is made of **three candles** [T]. The transcripts never give the exact gap formula.
- Coded definition, the standard ICT form [I]:
  - Bullish FVG: `low[c3] > high[c1]`. Zone = [high[c1], low[c3]].
  - Bearish FVG: `high[c3] < low[c1]`. Zone = [high[c3], low[c1]].
- Size doesn't matter: "a small FVG, big FVG… as long as there's a fair value gap, you're good" [T]. I'd add a tiny minimum size to filter out noise [I].
- The HTF gap must be the **most recent** one, "not an old one, not a partially filled one" [T].

## 3. Core model: 4H FVG + LTF FVG
1. **Bias (4H)** [T]: Mark the most recent unfilled 4H FVG. A bullish one means look only for longs; a bearish one means look only for shorts. No other daily-bias analysis is needed ("We are done on the 4-hour chart").
2. **Wait for the tap** [T]: Price must actually trade into the 4H FVG zone. Never anticipate the move.
   - [I] Tap = an LTF candle's high (for bearish) or low (for bullish) enters the zone. A 4H close straight through the far edge cancels the zone ("smash right through").
3. **Confirmation (LTF)** [T]: After the tap, wait for the **first new FVG in the same direction** on the entry timeframe. Ignore opposite-direction FVGs.
   - Entry timeframe: 5M is the main example. 1M and 15M are also allowed ("doesn't really matter") [T]. Default: 5M [I].
4. **Entry** [T]: "Enter on the fair value gap." [I] Code it as a limit order at the near edge of the LTF FVG (option: market order on the close of candle 3). It needs confirming.
5. **Session filter** [T]: The LTF FVG may form at any time, but the **entry must fall in a major session** (London, ~2:00 AM New York time, or New York) for the "A+" setup. Entries outside a session are allowed but have a lower win rate. [I] Proposed windows: London 02:00–05:00 ET, NY 07:00–10:00 ET (configurable). Signals outside them get a "B" grade.
6. **Stop loss** [T]: Beyond the 3-candle FVG. Short: the high of the 3 candles. Long: the low of the 3 candles. "Or the old high/low"; don't use a very tight stop.
7. **Take profit** [T]: Fixed RR. **3:1 default**, 2:1 allowed, never above 3:1 unless there is an obvious liquidity target. No moving the stop.
8. **Invalidation** [I]: Cancel the setup if the 4H zone is fully closed through before confirmation, a newer opposite 4H FVG forms, or no confirmation comes within N hours (e.g. 24).

## 4. PDF concepts as optional filters/scores [PDF → I]
They score or rank a signal. They do not replace the core rules (the creator says no extra analysis is needed).
- **RRR ≥ 1.5** (Ch 18.5), already met by 2:1 and 3:1.
- **Dow trend alignment** (Ch 17, Grand Checklist): primary trend = 50/200 EMA on 4H/Daily. Add points if the trade goes with it.
- **Support/Resistance** (Ch 11): add points if the 4H FVG overlaps a recent swing S/R level.
- **Volume** (Ch 12): add points if confirmation-candle volume is above its 20-period average. Crypto only; spot FX has no real volume.
- **Indicators confirm** (Ch 13–15): RSI not stretched against the trade (e.g. <70 for longs), MACD agrees. The checklist says these confirm a trade but shouldn't veto it.
- **Candlestick confirmation** (Ch 5–10): add points for an engulfing, hammer, or shooting-star candle at the tap.
- **Fibonacci** (Ch 16): add points if the zone sits in the 50–61.8% retracement of the last swing.

## 4b. Added from the two new PDFs (both image-only; no text layer, OCR not installed, so I read the pages visually)
**[P-CDL]** "5 Most Profitable Candlesticks You Should Know", Knowledge of Stockmarket / KSM Academy (7 pp, diagrams only; last page is an ad for their free course).
Families: Doji (standard, long-legged, dragonfly, gravestone, 4-price); Hammer, Inverted Hammer, Shooting Star, Hanging Man; Tweezer Bottom/Top; Three Inside Up/Down; Morning/Evening Star.
→ Use as an optional **confirmation score** at the 4H FVG tap, alongside the PDF Ch 5–10 patterns [I]. Bullish set for longs: hammer, inverted hammer, dragonfly, tweezer bottom, three inside up, morning star. Bearish set for shorts: shooting star, hanging man, gravestone, tweezer top, three inside down, evening star. There are no thresholds in the PDF, so I'd reuse Varsity's (e.g. lower wick ≥ 2× body).

**[P-CHT]** Untitled chart-pattern cheat sheet (22 pp, diagrams; "Forexbee" logo on one page).
Patterns: ascending/descending/symmetrical triangle, cup & handle, broadening, bull/bear flag, diamond top/bottom, double/triple top & bottom, ascending/descending/horizontal channel, bump-and-run, rising/falling wedge, impulse–correction structure (Fib 61.8 retrace → 161.8 extension), HH/HL trendline drawing (correct vs wrong).
Codeable rules shown in the diagrams:
- Double/triple top & bottom: entry on the neckline break (or its retest); SL beyond the support/resistance zone; TP = pattern height projected from the neckline.
- Cup & handle: entry on the handle breakout; SL below the handle; TP1 = Fib 1.618, TP2 = Fib 2.618.
- Wedges/flags: entry on the trendline break; TP = pattern height.
- Trend structure: HH+HL = uptrend, LH+LL = downtrend; 61.8% retracement as a pullback zone.
→ Proposed use [I]: (a) HTF structure (HH/HL vs LH/LL on 4H) as a **trend-alignment score**, consistent with Dow theory; (b) mark the 4H FVG as higher quality if it sits at a neckline/S&R/channel line or near the 61.8% retrace; (c) optionally, a **separate pattern-breakout signal module later**. Automatic pattern detection (triangles, wedges, diamonds) is noisy; start with double/triple tops and bottoms only.

**Agreement and conflict with the FVG core**
- Neither PDF mentions FVGs, sessions, timeframes or entry-chart rules. The core model in §3 is unchanged, and none of the open questions are answered.
- Agrees: SL beyond the structure (zone/handle), the same idea as SL beyond the 3-candle FVG; the trend and S&R filters match Varsity.
- Conflicts (only if the patterns become their own signals): pattern TP = measured move or Fib 1.618/2.618 vs the creator's fixed 2–3R, with a max of 3R unless there's a liquidity target. Pattern entries are breakouts, while FVG entries are pullbacks into a gap. Recommendation: keep FVG signals on fixed 3R, and use the pattern targets only in a separate pattern module (or as the "obvious liquidity target" exception allowing >3R).

## 5. Open questions for Abiodun
1. Entry timeframe: 5M (default), 1M, or 15M? Should "4H + 15M" (gold video) be a separate mode?
2. Entry: limit at the FVG edge, its midpoint, or market at confirmation?
3. Stop: the 3-candle FVG high/low, or the "old swing high/low"?
4. Take profit: 3:1 or 2:1? Any partial closes?
5. Sessions: which ones, and should signals outside them be sent (flagged) or suppressed?
6. Which pairs? (e.g. BTC, ETH, EURUSD, GBPUSD, XAUUSD)
7. Should the PDF filters be scores only or hard filters?
8. Do you have the creator's free PDF trading plan (pinned comment)? It may answer 2–3 above. I couldn't get it.
9. Should the "liquidity sweep" videos (e.g. WYtAtXOLj2U) be added later? I couldn't get transcripts for them.
10. New: should chart patterns stay as score filters only, or also become a separate signal type with their own measured-move targets?

## 6. Creator's written plan (FVG Trading Strategy, 4H and 15 Min; .docx + identical 4-page PDF, received 13 Oct) [PLAN]
Rules quoted from the plan:
- "Wait for a Fair Value Gap (FVG) to form on the 4H chart." / "Wait for price to return to the 4H FVG on the 15 min chart. Price should quickly shoot off once hitting the 4H FVG and leave a new smaller FVG on the 15 minute chart."
- "Enter on that 15 min FVG that is formed." The chart shows a limit order at the near edge of the 15m FVG.
- "Your stop loss should be at the swing low" (bearish: "at the swing high"). In the USDJPY chart the stop sits under the swing low that tapped the 4H FVG, wider than the 3 FVG candles.
- "Target at most a 3RR. A 2RR is also great."; "Both the 4H and 15 min FVG should be in the same direction."; "Risk at most 1% per trade"; the bearish example "consolidates before dropping in the London session. This is normal."

Differences vs the live spec:
| Item | Live (from the videos) | Plan | Action |
|---|---|---|---|
| Entry timeframe | 15m (user choice) | 15m | same |
| Stop | high/low of the 3 FVG candles | swing low/high of the leg (tap → 15m FVG) | tested as FVG-PLAN |
| Reaction speed | none (first FVG after tap, any time) | "quickly shoot off" | [I] ≤16 15m bars from tap to FVG (chosen in-sample from 4/8/16) |
| Target | 3R | ≤3R, 2R fine | 3R kept (user rule); 2R comparison |
| Session | entry in a major session = A+ | not required (London only in an example) | unchanged (score only) |
| Risk | not specified | max 1% per trade | added to the README/messages as guidance |

Backtest (same split and costs; `backtest3`, `bt3_tables.md`), crypto net R/trade, in-sample (IS) / out-of-sample (OOS): LIVE −0.106 / +0.010; PLAN swing stop −0.103 / −0.003; PLAN + quick −0.083 / +0.001. Forex: PLAN is worse than LIVE in both periods. **Not at least as good OOS, so the live FVG is not changed. FVG-PLAN (swing stop + quick ≤16 bars) was added as an EXPERIMENTAL crypto paper-trading strategy.**

## 7. Live strategy set (13 Oct 2026)
- FVG (live): §3, 15m entry, crypto stop ≥0.3%, calibrated win probability.
- FVG+TREND [EXPERIMENTAL]: a tag on FVG signals (crypto) when the 4H EMA50/200 trend agrees (same row, same post).
- FVG-PLAN [EXPERIMENTAL]: §6 (crypto); a separate row for tracking, posted in the same Telegram message as the FVG setup when both appear together.
- CHK [EXPERIMENTAL]: Varsity Grand Checklist on 1H (backtest-report-v2.md), crypto, market entry at the 1H close.
