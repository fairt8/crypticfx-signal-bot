"""Single source of truth for strategy status + labels (Telegram, dashboard, stats, summaries).
primary / normal / experimental = active (new signals); retired = no new signals, history kept, code kept (backtest_all)."""
STATUS = {
    "DON20": "primary",
    "CHK": "experimental",   # user 2026-10-18: PRIMARY -> EXPERIMENTAL (paper test; posts again)
    "FVG-D1": "normal", "FVG-PLAN": "normal",
    "MF-REJ": "experimental", "BRK": "experimental", "PAT-TRIPLE": "experimental",
    "FVG": "retired", "FVG+TREND": "retired", "PAT-WEDGE": "retired", "PAT-CUP": "retired",
}
LABEL = {"primary": "⭐ PRIMARY", "normal": "✅ NORMAL", "experimental": "🧪 EXPERIMENTAL", "retired": "🗄 RETIRED"}
NAME = {"CHK": "CHK · Varsity checklist (1H)", "DON20": "DON20 · daily Donchian-20 breakout",
        "FVG-D1": "FVG-D1 · 4H→15m FVG with daily-bias filter", "FVG-PLAN": "FVG-PLAN · FVG creator plan (swing stop)",
        "MF-REJ": "FOREX MF-REJ · Market Fluidity zone rejection (1H)", "BRK": "BRK · 4H crypto neckline/trendline breakout",
        "PAT-TRIPLE": "PAT-TRIPLE · 4H FX triple top/bottom retest", "FVG": "FVG (live) · 4H→15m FVG",
        "FVG+TREND": "FVG + 4H trend filter", "PAT-WEDGE": "PAT-WEDGE · 4H wedge retest", "PAT-CUP": "PAT-CUP · 4H cup & handle retest"}
ORDER = ["primary", "normal", "experimental", "retired"]
RETIRE_CLOSE = ("FVG", "FVG+TREND")   # open/pending trades of these are closed at market by trades.retire_close()
def eff(strategy, tags=()):
    """Effective strategy of a signal row: legacy FVG rows tagged FVG-D1 count as FVG-D1 (the promoted strategy)."""
    if strategy == "FVG" and "FVG-D1" in (tags or ()): return "FVG-D1"
    return strategy or "FVG"
def status(k): return STATUS.get(k, "experimental")
def label(k): return LABEL[status(k)]
def active(k): return status(k) != "retired"
def name(k): return NAME.get(k, k)
def full(k): return f"{label(k)} · {name(k)}"
def main_stats(k): return status(k) in ("primary", "normal")   # dashboard/summary headline stats: PRIMARY + NORMAL only
def listing(): return [dict(key=k, status=status(k), label=label(k), name=name(k)) for s in ORDER for k in STATUS if STATUS[k] == s]
