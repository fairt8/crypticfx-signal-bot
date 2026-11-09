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
