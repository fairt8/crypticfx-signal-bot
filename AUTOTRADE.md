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
numbers: `/autotrade risk 2`, `maxopen 3`, `lev 5`, `notional 100`, `dailyloss 20`, `timeout 5|10|15|0`,
`bumprisk 2`, `bumpmargin 5` · exchanges: `/autotrade exchanges mexc|weex|mexc,weex|weex,mexc` · `/autotrade minbump on|off`.
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

## Leverage MAX, max position size, Limit → Market (t142u)
- Leverage: `cap` (≤ N x, `/autotrade lev 5`) or `max` (`/autotrade lev max`): the exchange's highest leverage for the coin
  AND the order's size tier (MEXC contract risk tiers by volume; WEEX /capi/v3/market/riskLimits notional brackets). In both
  modes a guard steps leverage down 1x at a time while the estimated isolated liquidation price
  (entry × (1 ∓ 1/lev ± maintenance-margin rate)) is at or inside the stop; this is logged and saved in the row note. Size is
  always risk ÷ stop distance; leverage only changes the margin used.
- "Max position size (USDT)" (formerly "max notional"; `/autotrade size 100`, 0 = off) caps qty × price per trade.
- Order types: Limit · Limit → Market · Market. Limit → Market places the limit at entry; at the 5/10/15-min timeout it is
  cancelled and re-entered at market on the SAME exchange only if the signal is still valid and price is within 0.5R of the
  entry (not beyond SL/TP), re-sized at the live price; otherwise it is skipped. A partial fill before the cancel is kept.

## 📐 Size line on crypto signal alerts (t144u)
`app/sizing.py` appends one line ("📐 Size  qty BASE · $position · risk $ · leverage/margin") to every crypto signal alert and
DON20/DON28 entry, from the same sizing settings, even when auto-trade is off. Additive only: no other alert content,
signal generation or timing changes, and the line is omitted on any failure. `/autotrade sizeline on|off` (default on).
