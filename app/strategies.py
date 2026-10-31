"""Single source of truth for strategy tier + labels (Telegram, dashboard, mini app, stats, summaries).
Two live tiers (user 2026-10-31): ⭐ PRIMARY and 🔷 SECONDARY – both get live signals + alerts.
retired = no new signals, history kept, code kept (monthly backtest app.backtest_all).
Stop/target variants of the live strategies are in app/variants.py (research/stop_variants_3r)."""
STATUS = {
    # ⭐ PRIMARY
    "DON20": "primary", "MF-REJ": "primary", "PAT-TRIPLE": "primary", "PAT-WEDGE": "primary", "BRK": "primary",
    # 🔷 SECONDARY
    "CHK": "secondary", "FVG-D1": "secondary", "FVG-PLAN": "secondary", "PAT-TRIPLE-C": "secondary", "FVG+TREND": "secondary",
    # 🗄 RETIRED (no live signals; monthly backtest only). MF-REJ crypto and DON28 were never live: research scripts only.
    "FVG": "retired", "PAT-CUP": "retired",
}
TIERS = ("primary", "secondary")
LABEL = {"primary": "⭐ PRIMARY", "secondary": "🔷 SECONDARY", "retired": "🗄 RETIRED"}
NAME = {"DON20": "DON20 · daily Donchian-20 breakout, 3×ATR trail",
        "MF-REJ": "FOREX MF-REJ · Market Fluidity zone rejection (1H)",
        "PAT-TRIPLE": "PAT-TRIPLE · 4H forex triple top/bottom retest",
        "PAT-WEDGE": "PAT-WEDGE · 4H crypto wedge retest · 1.5× stop · 3R",
        "BRK": "BRK · 4H crypto neckline/trendline breakout · 3R",
        "CHK": "CHK · Varsity checklist (1H)",
        "FVG-D1": "FVG-D1 · 4H→15m FVG with daily-bias filter",
        "FVG-PLAN": "FVG-PLAN · FVG creator plan · 1.5× swing stop · 3R",
        "PAT-TRIPLE-C": "PAT-TRIPLE crypto · 4H triple top/bottom retest · 2× stop · 3R",
        "FVG+TREND": "FVG+TREND · FVG with EMA50/200 trend · 1h-candle stop · 3R",
        "FVG": "FVG (old live) · 4H→15m FVG", "PAT-CUP": "PAT-CUP · 4H cup & handle retest"}
SHORT = {"PAT-TRIPLE": "PAT-TRIPLE FX", "PAT-TRIPLE-C": "PAT-TRIPLE crypto", "MF-REJ": "MF-REJ FX"}
ORDER = ["primary", "secondary", "retired"]
RETIRE_CLOSE = ("FVG",)   # open/pending trades of these are closed at market by trades.retire_close() (FVG+TREND is live again)
def eff(strategy, tags=()):
    """Effective strategy of a signal row: legacy FVG rows tagged FVG-D1 count as FVG-D1 (the promoted strategy)."""
    if strategy == "FVG" and "FVG-D1" in (tags or ()): return "FVG-D1"
    return strategy or "FVG"
def status(k): return STATUS.get(k, "retired")
def paused(k):
    """Active strategy with new live signals switched off by its env flag (open trades still tracked, backtest kept)."""
    if k == "CHK":
        from . import config as C; return not C.ENABLE_CHK
    return False
def label(k): return LABEL[status(k)] + (" (paused)" if paused(k) else "")
def active(k): return status(k) != "retired"
def name(k): return NAME.get(k, k)
def short(k): return SHORT.get(k, k)
def full(k): return f"{label(k)} · {name(k)}"
def main_stats(k): return status(k) in TIERS   # headline stats: PRIMARY + SECONDARY
def listing(): return [dict(key=k, short=short(k), status=status(k), label=label(k), name=name(k), paused=paused(k)) for s in ORDER for k in STATUS if STATUS[k] == s]
