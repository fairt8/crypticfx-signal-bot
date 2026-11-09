# MEXC auto-trade add-on

Separate add-on that only READS the signals the bot already generates (signals / don20 / don28 tables) and mirrors them
as MEXC USDT-M perpetual orders. Signal generation, Telegram signal alerts, the dashboard and the Mini App signal lists
do not call it; if it or MEXC fails, signals continue unchanged. Code: `app/autotrade.py`, `app/mexc.py`; tests:
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

## Bybit backup exchange (failover)
Code: `app/bybit.py` (V5 client), `app/exchanges.py` (MEXC + Bybit adapters, one interface). Settings: primary exchange
(default MEXC), failover (default: on once Bybit keys exist), per-exchange on/off — `/autotrade primary mexc|bybit`,
`/autotrade failover on|off|auto`, `/autotrade bybit on|off`, or the panel buttons / Mini App ▸ Auto ▸ Exchanges.

Rules for a NEW order:
- The backup is used only when the primary can't take it with nothing executed there: failed health check, unreachable /
  5xx / maintenance before or on placement (MEXC is asked by client order id first when it answers), or the coin isn't
  tradable on the primary.
- If the primary's state is unknown (timeout after sending), the signal is NOT sent to the backup (no double position);
  it is resolved by client order id on the next ticks. Business rejections (e.g. balance) never fail over.
- One auto trade per signal, on one exchange. It is managed (fills, SL/TP updates, partial close, exits) only on the
  exchange it was opened on. If that exchange is down, exits retry every minute; the exchange-side SL/TP still protect it.
- Bybit: category linear, one-way (hedge index used automatically if the account is in hedge mode), account-default
  margin mode, leverage set per symbol, SL/TP attached with tpslMode Full, reduce-only market closes, orderLinkId ids.

### Adding the Bybit key (on the server only, never in chat)
Bybit ▸ API ▸ Create New Key ▸ System-generated ▸ "API Transaction". Permissions: **Contract (Derivatives) → Orders +
Positions** (read-write). Leave Withdraw, Transfer/Asset exchange, Earn, Spot-margin, Copy-trading etc. unticked. Bind IP
**your server's public IP**. Then add `BYBIT_API_KEY=...` and `BYBIT_API_SECRET=...` to `/etc/fvg-signal-bot.env` and
`sudo systemctl restart fvg-signal-bot`. Note: the server IP geolocates to the UK; Bybit's public API answers from it, but
private (trading) calls can still be refused by Bybit's region rules (codes 10009 / 10024 / HTTP 403). The first `/autotrade`
dry-run / health check after adding the key shows this.

### MEXC balance permission
If the MEXC key lacks "View Account Details" (MEXC code 700007), auto-trade shows a note in Telegram (max every 12 h) and
the Mini App, skips its own margin pre-check, and lets MEXC reject an order if margin is short.
