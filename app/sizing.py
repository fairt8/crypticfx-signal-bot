"""'Size:' line for crypto signal alerts (user 2026-11-09, t144u) – additive only, for copying the trade by hand on
Binance / MEXC / WEEX or any exchange. Uses the same sizing settings as auto-trade ($ risk ÷ stop distance, fixed margin × leverage,
or % of the last-read balance; capped by the max position size; leverage cap or MAX) and is shown even when auto-trade is off. Pure arithmetic, no exchange calls; any
failure returns None and the alert is sent exactly as before. Setting: size_line (default on)."""
import json, time
from . import db

KEY = "auto" + "trade:settings"   # same kv key the auto-trade settings live in (read-only here)
_C = {"t": 0, "v": None}
def _settings(max_age=120):
    if _C["v"] is not None and time.time() - _C["t"] < max_age: return _C["v"]
    try: raw = db.kv_get(KEY); v = json.loads(raw) if raw else {}
    except Exception:
        if _C["v"] is not None: return _C["v"]
        raise
    _C.update(t=time.time(), v=v); return v
def _q(x):
    x = float(x)
    if x >= 100: return f"{x:,.0f}"
    if x >= 1: return f"{x:,.3f}".rstrip("0").rstrip(".")
    return f"{x:.4g}"
BAL = "auto" + "trade:balance"     # last available-USDT read per exchange, written by the auto-trade add-on (read-only here)
MMR = 0.005
def _bal(s):
    """(exchange label, balance) of the last read for the first exchange in the user's order, or (None, None)."""
    try:
        raw = db.kv_get(BAL); d = json.loads(raw) if raw else {}
        for ex in list(s.get("exchanges") or []) + sorted(d):
            if ex in d and d[ex].get("v") is not None: return ex.upper(), float(d[ex]["v"])
    except Exception: pass
    return None, None
def calc(entry, sl, s):
    """dict(qty, notional, risk, lev, margin, mode, note) from the settings, or None. Modes (user 2026-11-10):
    risk = risk_usdt / stop; margin = margin_usdt x leverage (MAX: estimated from the liquidation guard); pct = risk_pct %
    of the last balance the auto-trade add-on read (qty None if no balance has been read yet)."""
    entry, sl = float(entry), float(sl); dist = abs(entry - sl)
    if entry <= 0 or dist <= 0: return None
    mode = s.get("sizing_mode") or "risk"; cap = float(s.get("max_notional_usdt") or 0)
    lev = None if s.get("lev_mode") == "max" else int(s.get("leverage") or 5); note = None
    if mode == "margin":
        m = float(s.get("margin_usdt") or 1)
        lv = lev or max(1, int(1 / (dist / entry + MMR)))          # MAX: highest leverage whose est. liquidation is beyond the stop
        notional = m * lv; qty = notional / entry
        if cap > 0 and notional > cap: notional = cap; qty = cap / entry
        z = dict(qty=qty, notional=notional, risk=qty * dist, lev=lev, margin=notional / lv, mode=mode)
        if not lev: z["note"] = f"margin ${m:g} × ~{lv}x est."
        return z
    if mode == "pct":
        ex, b = _bal(s); pct = float(s.get("risk_pct") or 1)
        if b is None: return dict(qty=None, notional=None, risk=None, lev=lev, margin=None, mode=mode, note=f"risk {pct:g}% of balance (balance not read yet)")
        risk = b * pct / 100; note = f"{pct:g}% of {ex} ${b:,.2f}"
    else:
        risk = float(s.get("risk_usdt") or 1.0)
    qty = risk / dist; notional = qty * entry
    if cap > 0 and notional > cap: qty = cap / entry; notional = cap; risk = qty * dist
    return dict(qty=qty, notional=notional, risk=risk, lev=lev, margin=(notional / lev) if lev else None, mode=mode, note=note)
def line(symbol, entry, sl, market="crypto"):
    """'📐 Size' HTML line or None (off / not crypto / anything fails)."""
    try:
        if market != "crypto": return None
        s = _settings()
        if s.get("size_line") is False: return None
        z = calc(entry, sl, s)
        if not z: return None
        if z.get("qty") is None: return f"📐 <b>Size</b>  {z['note']}"
        base = str(symbol).upper(); base = base[:-4] if base.endswith("USDT") else base
        if z.get("mode") == "margin" and not z["lev"]: lev = z["note"] + " (MAX lev per exchange)"
        else: lev = f"≤{z['lev']}x → margin ~${z['margin']:,.2f}" if z["lev"] else "MAX lev (per exchange)"
        extra = f" ({z['note']})" if z.get("mode") == "pct" and z.get("note") else ""
        return f"📐 <b>Size</b>  {_q(z['qty'])} {base} · ${z['notional']:,.2f} position · risk ${z['risk']:,.2f}{extra} · {lev}"
    except Exception:
        return None
def add(text, symbol, entry, sl, market="crypto"):
    """Insert the line before the 'Not financial advice' footer (or append). Returns text unchanged on any failure."""
    try:
        l = line(symbol, entry, sl, market)
        if not l: return text
        foot = "\n\n<i>Not financial advice.</i>"
        return text.replace(foot, "\n" + l + foot, 1) if foot in text else text + "\n" + l
    except Exception:
        return text
