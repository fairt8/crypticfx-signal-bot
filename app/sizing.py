"""'Size:' line for crypto signal alerts (user 2026-11-09, t144u) – additive only, for copying the trade by hand on
Binance / MEXC / WEEX or any exchange. Uses the same sizing settings as auto-trade (risk USDT ÷ stop distance, capped by the max
position size, leverage cap or MAX) and is shown even when auto-trade is off. Pure arithmetic, no exchange calls; any
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
def calc(entry, sl, s):
    """dict(qty, notional, risk, lev, margin) from the settings, or None."""
    entry, sl = float(entry), float(sl); dist = abs(entry - sl)
    if entry <= 0 or dist <= 0: return None
    risk = float(s.get("risk_usdt") or 1.0); qty = risk / dist; notional = qty * entry
    cap = float(s.get("max_notional_usdt") or 0)
    if cap > 0 and notional > cap: qty = cap / entry; notional = cap; risk = qty * dist
    lev = None if s.get("lev_mode") == "max" else int(s.get("leverage") or 5)
    return dict(qty=qty, notional=notional, risk=risk, lev=lev, margin=(notional / lev) if lev else None)
def line(symbol, entry, sl, market="crypto"):
    """'📐 Size' HTML line or None (off / not crypto / anything fails)."""
    try:
        if market != "crypto": return None
        s = _settings()
        if s.get("size_line") is False: return None
        z = calc(entry, sl, s)
        if not z: return None
        base = str(symbol).upper(); base = base[:-4] if base.endswith("USDT") else base
        lev = f"≤{z['lev']}x → margin ~${z['margin']:,.2f}" if z["lev"] else "MAX lev (per exchange)"
        return f"📐 <b>Size</b>  {_q(z['qty'])} {base} · ${z['notional']:,.2f} position · risk ${z['risk']:,.2f} · {lev}"
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
