# MEXC auto-trade add-on

Separate add-on that only READS the signals the bot already generates (signals / don20 / don28 tables) and mirrors them
as MEXC and/or WEEX USDT-M perpetual orders (you pick: MEXC only, WEEX only, or both in either order). Signal generation, Telegram signal alerts, the dashboard and the Mini App signal lists
do not call it; if it or MEXC fails, signals continue unchanged. Code: `app/autotrade.py`, `app/mexc.py`, `app/weex.py`, `app/exchanges.py`; tests:
`tests/test_autotrade.py`.

Ships OFF: master switch off, no strategies enabled, dry-run on, no key.

## Adding the MEXC key (on the server only, never in chat)
1. MEXC ▸ API Management ▸ create key. Permissions: futures **Order Placing** + **View Order Details** only.
   No withdrawal / transfer permission. Bind IP **your server's public IP** (unbound keys expire after 90 days). KYC is required.
2. On the VM: `sudo nano /etc/fvg-signal-bot.env` and add two lines:
   `MEXC_API_KEY=...` and `MEXC_API_SECRET=...` (file stays root-owned, mode 600).
3. `sudo systemctl restart fvg-signal-bot` (no daemon-reload needed).
4. In the bot: `/autotrade` (or Mini App ▸ Auto) ▸ pick strategies ▸ Turn ON. It starts in dry-run; tap "Go LIVE…" to confirm.

## Controls
`/autotrade` panel (inline buttons) · `/autotrade off` stops new orders · `/flatten` (confirm) closes every auto position ·
numbers: `/autotrade risk 2`, `maxopen 3`, `lev 5`, `notional 100`, `dailyloss 20`, `cancelpct 70`, `maxwait 24` (hours), `timeout N` (minutes),
`bumprisk 2`, `bumpmargin 5`, `betrigger 30`, `belock 5` · exchanges: `/autotrade exchanges mexc|weex|mexc,weex|weex,mexc` · `/autotrade minbump on|off` ·
`/autotrade be on|off`.
Mini App ▸ Auto has the same settings plus open positions, pending limits and PnL (owner-only `/app/api/autotrade`).

## Exchange mode (t156u, 2026-11-10): MEXC only · WEEX only · MEXC → WEEX · WEEX → MEXC
Setting `exchanges` (a list, first = tried first) replaces the old primary / failover / per-exchange switches:

| Mode | `exchanges` | Command | Behaviour |
|---|---|---|---|
| MEXC only | `["mexc"]` | `/autotrade exchanges mexc` | never touches WEEX |
| WEEX only | `["weex"]` | `/autotrade exchanges weex` | never touches MEXC |
| MEXC → WEEX (default) | `["mexc","weex"]` | `/autotrade exchanges mexc,weex` | MEXC first, WEEX fallback |
| WEEX → MEXC | `["weex","mexc"]` | `/autotrade exchanges weex,mexc` | WEEX first, MEXC fallback |

Also `both` = `mexc,weex`. Telegram panel: four mode buttons (`at:em:…`); Mini App ▸ Auto ▸ Exchanges ▸ "Trade on".
Old commands keep working and are mapped onto the list: `/autotrade primary mexc|weex` (moves it first; in a single
mode it switches to that exchange), `/autotrade failover on|off|auto` (on/auto = both with the current first exchange
first, off = only the first), `/autotrade mexc|weex on|off` (adds at the end / removes; at least one stays). In LIVE
mode an exchange without its API key is skipped (WEEX until all three WEEX env vars exist).
Migration: saved settings without `exchanges` are converted on load from primary_exchange / failover / ex_on (Bybit →
WEEX): failover auto/on → both (primary first), off → primary only, disabled exchanges dropped. The live settings
(primary MEXC, failover auto, both on) became `["mexc","weex"]`; the old keys are removed on the next save;
enabled / dry_run are never touched.

## Sizing modes (t158u, 2026-11-10) — default `$ risk`, the others are inactive until picked
Setting `sizing_mode`: `risk` (default; all saved settings without it load as `risk`) · `margin` · `pct`.
`/autotrade sizing risk|margin|pct` · `/autotrade margin N` (fixed USDT margin per trade, default 1) ·
`/autotrade pct N` (% of balance risked at the stop, 0.01–20, default 1). Setting a number never switches the mode.
Telegram panel: three buttons (`at:sm:risk|margin|pct`); Mini App ▸ Auto ▸ Position sizing: mode selector + the three
number fields (saved with "Save numbers").

| Mode | Size | $ risk at the stop |
|---|---|---|
| $ risk | qty = risk_usdt ÷ \|entry − stop\| | ≈ risk_usdt (rounded DOWN to the step) |
| Fixed margin | notional = margin_usdt × leverage, qty = notional ÷ price | qty × stop distance = margin × leverage × stop % (varies per trade) |
| % of balance | risk_usdt = risk_pct % × available USDT on the opening exchange, then as $ risk | ≈ that % of the balance |

- % of balance is the "% risked at the stop" design (not % as margin): it keeps risk per trade constant as the account
  grows/shrinks. The balance is read live (`usdt_available`, a read-only private call) from the exchange that would open
  the trade, once per exchange per tick, and reused for the margin check. This read also happens in dry-run (the only
  private call dry-run makes, and only in this mode). If it can't be read (no key, missing balance permission, read
  error) the exchange is skipped with the reason, the next exchange in the route is tried, and if none works Telegram
  gets "⏭️ AUTO · skipped (balance)". In LIVE mode an unreachable exchange fails over as usual.
- Fixed margin: leverage is found first (cap: min(cap, coin max); MAX: the coin's highest tier), the size is computed,
  then the tier + liquidation guard is checked for that size and leverage is lowered until it fits (lower leverage →
  smaller position → never a higher tier). Rounding is DOWN, so margin never exceeds the setting (except a min-order bump).
- In every mode the same steps follow: exchange step / minimum + min-order bump (auto cap = 2× that trade's own risk in
  margin/% modes, or `bumprisk`; `bumpmargin`), max position size, maxVol, leverage cap / MAX + liquidation guard, live
  balance check (margin + 5%), price sanity. Every auto alert shows the position (qty and $ value) and the $ risk at the
  stop; margin / % trades add a "📏" line (e.g. "Fixed margin $20 × 5x → $100.00 position · margin $20.00 · risk $1.00 at
  the stop" or "1% of MEXC balance $640.00 = $6.40 risk → …"). The row note keeps `sizing`.
- 📐 Size line on signal alerts: margin mode = margin × leverage cap (MAX: estimated as the highest leverage whose
  liquidation is beyond the stop, labelled "est."); % mode = % of the last balance auto-trade read (kv `autotrade:balance`),
  or "risk N% of balance (balance not read yet)" before any read.

## Minimum-order bump (t156u, 2026-11-10)
If the size from your risk (risk USDT ÷ stop distance, rounded DOWN to the exchange step, capped by max position size)
is below that contract's minimum order (MEXC `minVol` contracts / WEEX `minOrderSize`, one volume step, and
`minNotional` where an exchange has one), the order is rounded UP to the smallest allowed size, only if:
- its risk at the stop ≤ the bump risk cap: `bump_max_risk_usdt` (`/autotrade bumprisk N`; default 0 = auto = 2 × risk per trade),
- its margin at the chosen leverage ≤ `bump_max_margin_usdt` (`/autotrade bumpmargin N`; default 0 = off),
- its value ≤ max position size (when set), and (live) the exchange's available USDT covers the margin (+5%).
Otherwise the signal is skipped on that exchange; in a two-exchange mode the other exchange is tried (nothing was sent,
so this is safe), and if none fits, Telegram gets "⏭️ AUTO · skipped (minimum order)" with the reason. Bumped orders
show "⬆️ Min-order bump: original → bumped size · risk $orig → $bumped (cap …)" on the placed / filled / Limit→Market
alerts, the row note (`bump`) and a pill in the Mini App list. `min_bump` default ON (`/autotrade minbump on|off`,
panel button, Mini App ▸ Auto ▸ Settings); OFF = below-minimum sizes are skipped (with the alert). Sizes above the
minimum are never changed. Only the $-risk sizing mode exists in the code; the 📐 Size line on signal alerts is not
affected (it has no exchange data).

## WEEX exchange
Bybit was removed on 2026-11-09 (user request): `app/bybit.py` is deleted, no route, setting, command or Mini App button
refers to it, and saved settings that mentioned it are migrated to WEEX on load (auto-trade on/off and dry-run untouched).

Code: `app/weex.py` (WEEX Futures V3 client, `https://api-contract.weex.com/capi/v3`), `app/exchanges.py` (MEXC + WEEX
adapters, one interface). Until all three WEEX env vars exist, WEEX is skipped automatically in LIVE mode.

Rules for a NEW order (both modes; "first" / "second" = the order in `exchanges`):
- The second exchange is used only when the first can't take it with nothing executed there: failed health check, unreachable /
  5xx / maintenance before or on placement (the first is asked by client order id first when it answers), the coin
  isn't tradable on the first (not listed, API trading not allowed, not enabled), or its minimum order is above the bump cap.
- If the first exchange's state is unknown (timeout after sending), the signal is NOT sent to the fallback (no double position);
  it is resolved by client order id on the next ticks. Business rejections (e.g. balance) never fail over.
- One auto trade per signal, on one exchange. It is managed (fills, SL/TP updates, partial close, exits) only on the
  exchange it was opened on. If that exchange is down, exits retry every minute; the exchange-side SL/TP still protect it.
- WEEX specifics: quantity in base coin (step = `contractVal`, min `minOrderSize`, max min(`maxOrderSize`,
  `marketOpenLimitSize`)), only pairs in `/capi/v3/market/apiTradingSymbols` are traded; `side` BUY/SELL + `positionSide`
  LONG/SHORT (works in combined and separated mode); account-default margin mode, leverage set per symbol
  (`/capi/v3/account/leverage`); SL/TP attached to the entry (`slTriggerPrice`/`tpTriggerPrice`), later moved with
  `/capi/v3/modifyTpSlOrder` (or placed full-position with `/capi/v3/placeTpSlOrder`); reduce-only market closes;
  `newClientOrderId` (≤ 36 chars) looked up via open orders + order history. Leverage MAX uses `/capi/v3/market/riskLimits`.

### Adding the WEEX key (on the server only, never in chat)
WEEX ▸ API Management (https://www.weex.com/account/newapi) ▸ create key with a passphrase. Permissions: **Read** +
**Futures/Contract trade** only — no withdrawal / transfer. Bind IP **your server's public IP**. Then add three lines to
`/etc/fvg-signal-bot.env`: `WEEX_API_KEY=...`, `WEEX_API_SECRET=...`, `WEEX_API_PASSPHRASE=...` and
`sudo systemctl restart fvg-signal-bot` (no daemon-reload needed). The passphrase can't be recovered; if lost, make a new key.

### MEXC balance permission
If the MEXC key lacks "View Account Details" (MEXC code 700007), auto-trade shows a note in Telegram (max every 12 h) and
the Mini App, skips its own margin pre-check, and lets MEXC reject an order if margin is short.

## Leverage MAX, max position size (t142u)
- Leverage: `cap` (≤ N x, `/autotrade lev 5`) or `max` (`/autotrade lev max`): the exchange's highest leverage for the coin
  AND the order's size tier (MEXC contract risk tiers by volume; WEEX /capi/v3/market/riskLimits notional brackets). In both
  modes a guard steps leverage down 1x at a time while the estimated isolated liquidation price
  (entry × (1 ∓ 1/lev ± maintenance-margin rate)) is at or inside the stop; this is logged and saved in the row note. Size is
  always risk ÷ stop distance; leverage only changes the margin used.
- "Max position size (USDT)" (formerly "max notional"; `/autotrade size 100`, 0 = off) caps qty × price per trade.
- Order types: see "Entry type follows the signal" below (the Limit → Market type was removed on 2026-11-10).

## 📐 Size line on crypto signal alerts (t144u)
`app/sizing.py` appends one line ("📐 Size  qty BASE · $position · risk $ · leverage/margin") to every crypto signal alert and
DON20/DON28 entry, from the same sizing settings, even when auto-trade is off. Additive only: no other alert content,
signal generation or timing changes, and the line is omitted on any failure. `/autotrade sizeline on|off` (default on).

## Entry type follows the signal; limits never become market orders (t160u, 2026-11-10)
User rules: "if the limit orders does not fills don't use market order, only use market order if the order/signal is
market order" and "Limit orders cancel once it is not filled and the trade has reached 70% proposed profit already".

Entry type per strategy (`ENTRY_TYPE` in `app/autotrade.py`, from how each strategy enters in the bot itself):

| Strategy | Entry | Why |
|---|---|---|
| FVG-D1, FVG-PLAN, FVG+TREND (and FVG) | **limit** | entry at the 15m/5m FVG edge, away from price; the signal is saved `pending` and the tracker fills it only when price comes back |
| DON20, DON28 | **market** | daily Donchian breakout entered at the live price when the position opens |
| BRK, PAT-WEDGE, PAT-TRIPLE crypto | **market** | 4H breakout / pattern entered at the 4H close (signal saved `open`, filled at creation) |
| CHK | **market** | 1H checklist entry at the 1H close (saved `open`) |

Any strategy not in the map is treated as limit (it never chases price).

Order type setting `order_type`:
- `auto` = **Follow the signal** (default and live): limit-entry signals get a limit at the entry only; market-entry
  signals get a market order, skipped if price already moved more than 0.5R from the signal entry (drift check).
- `limit` = **Limit only** (manual): every signal, market-entry ones too, gets a limit at its entry. Never a market order.
- The old `market` and `limit_market` (Limit → Market) types are gone. Saved settings, `/autotrade market`,
  `/autotrade limit_market` and old panel buttons all map to `auto`. Live: `limit_market` → `auto`.

When an unfilled limit is cancelled (checked every monitor tick, `AUTOTRADE_POLL_S`, 60 s), in this order:
1. Price hits the stop before the fill → cancelled (signal invalidated).
2. Price moved at least `cancel_pct` (default **70%**) of the distance from the entry to the target in the trade's
   direction without filling → cancelled, alert "limit cancelled, price reached 70% of target without fill". The target is
   TP1 (1.5R) for the 50%-at-TP1 strategies (CHK, FVG-D1), else the signal's TP. With no target (DON) this rule doesn't apply.
   A new limit isn't placed at all if price is already past that point.
3. Max wait (`limit_timeout_min`, safety net, default **24 h**; 0 = off) → "limit not filled, cancelled".
4. The bot's own signal ends first (expired / closed / retired) → cancelled.
Never converted to market. A partial fill is kept as the position (size and $ risk scaled to the filled part, exits
managed as usual) and the unfilled rest is cancelled: "limit partly filled, rest cancelled".
The old 5/10/15-min windows are no longer the default: a saved 5/10/15 (or no value) migrates once to 24 h (flag
`wait_v2`); any wait set after that is kept. Commands: `/autotrade auto` · `/autotrade limit` · `/autotrade cancelpct N`
(10–100) · `/autotrade maxwait H` (hours, 0 = off) · `/autotrade timeout N` (minutes, 0–10080). Telegram panel: Follow
the signal / Limit only and max-wait buttons; Mini App ▸ Auto ▸ Settings: order type, cancel % field (saved with "Save
numbers"), max-wait chips; each strategy chip shows limit / market.

## Breakeven+ stop (t163u, 2026-11-11)
For each **filled** auto-trade position, once price has travelled `be_trigger_pct` (default **30%**) of the way from the
fill to the **furthest/final** take-profit (the signal's TP field, not TP1), the exchange stop is moved once to
entry + `be_lock_pct` (default **5%**) of that same distance (the mirror for shorts). That locks in a small profit.
It runs only if the new stop is better than the current one; a stop is never loosened. Done once per trade (flag in the
row note). Strategies with no target (DON trailing stop) are skipped. This does not change signal generation, signal
alerts, or the signal outcome tracker.

On MEXC the existing plan/stop order is amended with `/api/v1/private/stoporder/change_plan_price` (or placed with
`/api/v1/private/stoporder/place` if none is open). On WEEX the attached TP/SL algo is amended with
`/capi/v3/modifyTpSlOrder` (or placed full-position with `/capi/v3/placeTpSlOrder`). If the amend fails, the old stop is
kept (the position stays protected), the failure is logged, and Telegram alerts the owner; it is retried next tick. In
dry-run the move is only simulated, with a log/alert "would move SL to X". A successful move (or dry-run simulation)
alerts: symbol, exchange, old SL, new SL, and the profit locked in USDT.

Defaults (applied in memory on load when the keys are missing; enabled / dry-run are never touched): ON, trigger 30, lock 5.
Commands: `/autotrade be on|off` · `/autotrade betrigger N` (10–90) · `/autotrade belock N` (0–50, must be below the
trigger). Shown on the `/autotrade` panel (toggle button) and Mini App ▸ Auto ▸ Settings (on/off + the two fields, saved
with "Save numbers").
