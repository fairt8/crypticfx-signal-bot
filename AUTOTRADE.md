# MEXC auto-trade add-on

Separate add-on that only READS the signals the bot already generates (signals / don20 / don28 tables) and mirrors them
as MEXC USDT-M perpetual orders (WEEX as the fallback). Signal generation, Telegram signal alerts, the dashboard and the Mini App signal lists
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
numbers: `/autotrade risk 2`, `maxopen 3`, `lev 5`, `notional 100`, `dailyloss 20`, `timeout 5|10|15|0`.
Mini App ▸ Auto has the same settings plus open positions, pending limits and PnL (owner-only `/app/api/autotrade`).

## WEEX fallback exchange (failover) — exchange order: MEXC (primary) → WEEX (fallback)
Bybit was removed on 2026-11-09 (user request): `app/bybit.py` is deleted, no route, setting, command or Mini App button
refers to it, and saved settings that mentioned it are migrated to WEEX on load (auto-trade on/off and dry-run untouched).

Code: `app/weex.py` (WEEX Futures V3 client, `https://api-contract.weex.com/capi/v3`), `app/exchanges.py` (MEXC + WEEX
adapters, one interface). Settings: primary exchange (default MEXC), failover (default: on once WEEX keys exist),
per-exchange on/off — `/autotrade primary mexc|weex`, `/autotrade failover on|off|auto`, `/autotrade weex on|off`, or the
panel buttons / Mini App ▸ Auto ▸ Exchanges. Until all three WEEX env vars exist, WEEX is skipped automatically.

Rules for a NEW order:
- The fallback is used only when the primary can't take it with nothing executed there: failed health check, unreachable /
  5xx / maintenance before or on placement (the primary is asked by client order id first when it answers), or the coin
  isn't tradable on the primary (not listed, API trading not allowed, not enabled).
- If the primary's state is unknown (timeout after sending), the signal is NOT sent to the fallback (no double position);
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
