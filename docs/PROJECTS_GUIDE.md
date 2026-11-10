# CrypticFx — Project Guide

One place for each project: what counts as "complete", where its code lives, and its shareable bot template.
Projects that aren't finished don't get a published template.

_Generated 10 Nov 2026. This guide has no secrets, keys, server addresses or private links._

## CrypticFx (this repo)

A crypto and forex signal generator: a Telegram bot and scanner, a web dashboard and Telegram Mini App, an optional auto-trade add-on, and a research and backtesting workflow. Educational, not financial advice. Auto-trade never stops, filters or changes signal generation or alerts.

**Projects, type and what each produces:**

| Project | Type | Produces |
|---|---|---|
| CrypticFx signal bot (Telegram bot and scanner) | App | 1. Live crypto and forex signals in PRIMARY and SECONDARY tiers, with background-only strategies kept off the alert feed. 2. Telegram alerts as setups appear, plus a PnL and position summary every 6 hours. 3. A continuously running scanner hosted on a private server. |
| Web dashboard and Telegram Mini App | App | 1. Signal lists with outcomes. 2. Strategy stats. 3. Equity cards (in dollars and in R). |
| Auto-trade | App feature | 1. Exchange selection: MEXC only, WEEX only, or both in either order. 2. Three sizing modes (dollar risk, fixed margin, percent of balance), a min-order bump, Limit / Market / Limit-to-Market orders, and max leverage with a liquidation guard. 3. Auto-trade alerts that show position size and dollar risk. |
| Research and backtesting | Workflow | 1. Multi-year backtests (at least 3 years where the data allows) of live and candidate rules. 2. A monthly backtest routine that replays the live code paths. 3. A weekly strategy report (not yet successfully delivered). |

### 1. CrypticFx signal bot

**Type:** App (Python service: scanner, Telegram bot, and strategy engines).

**Produces:**

1. Live crypto and forex signals, tiered as PRIMARY and SECONDARY.
2. Telegram alerts, plus a PnL and position summary every 6 hours.
3. Continuous scanning hosted on a private server.

**Complete means:** the bot scans and posts reliably on the private server, the live tiers match the approved list, the 6-hour summary goes out, and no strategy or tier is changed without the owner's approval.

- [x] Live on a private server (scanner and Telegram bot).
- [x] PRIMARY: DON20, MF-REJ forex, PAT-TRIPLE forex (with the opposite-candle filter), PAT-WEDGE at 1.5×, BRK (with the opposite-candle filter).
- [x] SECONDARY: CHK, FVG-D1, FVG-PLAN at 1.5×, PAT-TRIPLE crypto at 2×, FVG+TREND with a 1-hour candle stop, DON28.
- [x] Background-only / retired: FVG, PAT-CUP, and MF-REJ crypto (research only). No new live alerts from these.
- [x] Telegram alerts and a PnL summary every 6 hours.
- [x] Auto-trade cannot change signal generation or alerts.
- [ ] Pending strategy decisions (see below) still need an owner choice.
- [ ] DON28 coins with fewer than 200 daily bars currently pass through unfiltered (same as the research default).

### 2. Web dashboard and Telegram Mini App

**Type:** App (web desk plus an owner-only Telegram Mini App).

**Produces:**

1. Signal lists with outcomes.
2. Strategy stats.
3. Equity cards (in dollars and in R).

**Complete means:** both views are hosted on a private server, stay in sync with live signals, and show outcomes, strategy stats and equity.

- [x] Web dashboard: signals, outcomes, strategy stats and equity cards.
- [x] Owner-only Mini App with the same cards, plus an Auto tab for auto-trade settings.
- [x] Hosted on a private server.
- [x] Current scope is complete. Further changes follow new owner requests.

### 3. Auto-trade

**Type:** App feature (a separate add-on that only reads already-generated signals and may place exchange orders).

**Produces:**

1. Exchange selection: MEXC only, WEEX only, or both in either order (default is MEXC first, WEEX as fallback).
2. Three sizing modes, a min-order bump, Limit / Market / Limit-to-Market (5, 10 or 15 minute window), and max leverage with a liquidation guard.
3. Auto-trade alerts that show position size and dollar risk (and the old versus new size when a min-order bump is used).

**Status:** built and deployed, but the master switch is OFF and dry-run is on. Dollar-risk sizing is the default; fixed-margin and percent-of-balance modes are built and stay off until the owner picks one.

**Complete means:** WEEX credentials are installed and tested, a dry-run period has finished, and the owner has decided whether to go live. Until then, auto-trade must stay off and in dry-run.

- [x] Built and deployed: exchange modes, three sizing modes, min-order bump (on by default; cap is 2× the trade's own risk unless a custom cap is set), Limit / Market / Limit-to-Market, max leverage with a liquidation guard.
- [x] Master switch off, dry-run on. If auto-trade or an exchange fails, signals and alerts continue unchanged.
- [x] MEXC adapter in place; a read-only balance check has been run. The MEXC balance is small (about $6).
- [ ] The WEEX API key, secret and passphrase still need installing and testing (a read-only check, then a dry-run order test).
- [ ] Dry-run for a few days, then the owner decides whether to go live.
- [ ] Small MEXC balance (about $6): fund the account, or accept the limit, before any live trading.

A new order is never opened on two exchanges. The fallback is used only when nothing was executed on the first exchange. If the first exchange's state is unknown, the signal is not sent to the other one. Exits stay on the exchange that opened the trade.

### 4. Research and backtesting

**Type:** Workflow (research scripts under `research/`, plus a monthly replay of the live code).

**Produces:**

1. Multi-year backtests, at least 3 years where the data allows (forex 1-hour history is shorter than 3 years on the current data source).
2. A monthly backtest routine that replays live code paths (`python -m app.backtest_all`).
3. A weekly strategy report for the owner.

**Complete means:** the 3-year and monthly backtests are in the repo, no live strategy is changed without a backtest and owner approval, and the weekly report has had at least one successful run.

- [x] 3-year (or longest available) backtests for the live strategies, including the November 2026 stop-variant study, the opposite-candle filter study, and the DON28 study.
- [x] Monthly backtest routine that replays live code paths, with costs applied.
- [x] Research folders in this repo: `research/candles21`, `research/don20_exits`, `research/don20_filters`, `research/fvg_plan_v2`, `research/stop_variants_3r`.
- [ ] The weekly strategy report routine failed on 9 Nov 2026 because usage ran out. It still needs one successful run.

### Pending strategy decisions for the owner

No strategy or tier change is made without approval. Open questions:

- Promote CHK to PRIMARY?
- Demote PAT-WEDGE?
- Trim the Neon database quota?
- DON28 coins with under 200 daily bars currently pass through unfiltered. Keep that, or skip them?

## Template

No shareable template is published, because the project is not complete. A draft "Futures Trader" template was staged and left unpublished.

**Needed before publishing it:**

- The WEEX API key, secret and passphrase are installed and tested.
- Auto-trade has had a dry-run for a few days, and the owner has decided whether to go live.
- The weekly strategy report has had one successful run.
- The pending strategy decisions above have been answered (CHK, PAT-WEDGE, the Neon quota, and the DON28 young-coin filter).

**Run it without the assistant:** [README](../README.md), [AUTOTRADE.md](../AUTOTRADE.md), [strategy-spec.md](../strategy-spec.md), and the research READMEs under `research/`.

## Summary

| Project | Type | Produces | Complete? | Template |
|---|---|---|---|---|
| CrypticFx signal bot | App | Signals, Telegram alerts, 6-hour PnL summary | No (pending owner decisions) | Draft "Futures Trader", unpublished |
| Web dashboard and Mini App | App | Signals, outcomes, stats, equity cards | Yes (current scope) | Part of Futures Trader |
| Auto-trade | App feature | Exchange selection, sizing, orders (dry-run) | No (credentials, dry-run, go-live decision) | Part of Futures Trader |
| Research and backtesting | Workflow | 3-year and monthly backtests; weekly report | No (weekly report needs one successful run) | Part of Futures Trader |
