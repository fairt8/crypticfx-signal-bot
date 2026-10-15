import os
from pathlib import Path
try:
    from dotenv import load_dotenv; load_dotenv()
except Exception:
    pass
E = os.getenv
BASE = Path(__file__).resolve().parent.parent
DB_PATH = E("DB_PATH", str(BASE / "signals.db"))
DATABASE_URL = E("DATABASE_URL", "")  # Postgres (e.g. Neon) when set; SQLite fallback otherwise
BINANCE_BASE = E("BINANCE_BASE", "https://data-api.binance.vision")  # public market-data mirror; api.binance.com also works
BINANCE_API_KEY = E("BINANCE_API_KEY", "")
CRYPTO_TOP_N = int(E("CRYPTO_TOP_N", "300"))
FOREX_PROVIDER = E("FOREX_PROVIDER", "yfinance")  # yfinance | twelvedata
TWELVEDATA_API_KEY = E("TWELVEDATA_API_KEY", "")
def _clean_token(t):
    t = "".join((t or "").split()).strip("'\"`")   # drop whitespace/newlines anywhere and surrounding quotes
    if t.lower().startswith("bot") and ":" in t: t = t[3:]
    return t
TELEGRAM_BOT_TOKEN = _clean_token(E("TELEGRAM_BOT_TOKEN", ""))
TELEGRAM_CHAT_ID = E("TELEGRAM_CHAT_ID", "")
TELEGRAM_MODE = E("TELEGRAM_MODE", "auto")          # auto | webhook | polling
TELEGRAM_WEBHOOK_SECRET = E("TELEGRAM_WEBHOOK_SECRET", "")
PUBLIC_URL = E("PUBLIC_URL", "") or E("RENDER_EXTERNAL_URL", "")   # Render sets RENDER_EXTERNAL_URL automatically
SCAN_WORKERS = int(E("SCAN_WORKERS", "8"))
LLM_API_KEY = E("LLM_API_KEY", "")
LLM_BASE_URL = E("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = E("LLM_MODEL", "gpt-4o-mini")
RR = float(E("RR", "3.0"))
SCAN_MINUTES = int(E("SCAN_MINUTES", "5"))
FETCH_BUDGET_S = int(E("FETCH_BUDGET_S", "150"))    # max wall time for the whole crypto kline batch
YF_BUDGET_S = int(E("YF_BUDGET_S", "90"))           # max wall time per yfinance batch download
SCAN_WATCHDOG_S = int(E("SCAN_WATCHDOG_S", "420"))  # a scan running longer than this is abandoned
UNIVERSE_REFRESH_HOURS = int(E("UNIVERSE_REFRESH_HOURS", "6"))
LTF = E("LTF", "15m")  # entry/confirmation timeframe (user choice: 15m)
LTF_FREQ = {"5m":"5min","15m":"15min","1m":"1min"}[LTF]
MAX_CONFIRM_AGE_BARS = int(E("MAX_CONFIRM_AGE_BARS", "2"))  # LTF FVG must have completed within the last N LTF bars (2x15m = 30 min)
PENDING_EXPIRY = E("PENDING_EXPIRY", "48h")  # unfilled limit orders expire
ENABLE_SCHEDULER = E("ENABLE_SCHEDULER", "1") == "1"
MIN_POST_SCORE = int(E("MIN_POST_SCORE", "70"))  # live: only crypto FVG setups with raw setup score >= this are saved/posted (backtest v3)
MIN_CONFIDENCE_TO_POST = int(E("MIN_CONFIDENCE_TO_POST", "0"))
# --- Backtest-derived (backtest-report.md, 13 Oct 2026, 15m entry) ---
MIN_STOP_PCT_CRYPTO = float(E("MIN_STOP_PCT_CRYPTO", "0.3"))  # skip crypto setups whose stop is closer than this % (fees dominate)
MIN_STOP_PCT_FOREX = float(E("MIN_STOP_PCT_FOREX", "0"))
# confidence % = logistic(a + b*raw_setup_score), fitted on closed backtest trades. Forex slope was negative/noise -> flat base rate.
EXPERIMENTAL_MARKETS = set(E("EXPERIMENTAL_MARKETS", "crypto").split(","))  # backtest edge (if any) was crypto-only
ENABLE_CHK = E("ENABLE_CHK", "1") == "1"
CHK_CONFIDENCE = int(E("CHK_CONFIDENCE", "27"))  # observed CHK crypto win rate across the whole backtest (~27%: 22.4% IS, 30.7% OOS)
FVG_STOP = E("FVG_STOP", "fvg")  # "fvg" = beyond the 3 FVG candles (video); "swing" = swing low/high of the leg (creator PDF plan)
DAILY_REFRESH_HOURS = float(E("DAILY_REFRESH_HOURS", "6"))
ENABLE_D1 = E("ENABLE_D1", "1") == "1"
CALIB = {"crypto": (-1.3039, 0.00523), "forex": (-1.0018, 0.0)}  # refit 13 Oct on 15m FVG backtest (backtest-report-v2.md)
ENABLE_MF = E("ENABLE_MF", "1") == "1"   # MF-REJ [EXPERIMENTAL] forex zone rejection (strategy.MF_PAIRS)
ENABLE_DON20 = E("ENABLE_DON20", "1") == "1"   # DON20 [EXPERIMENTAL] daily Donchian-20 crypto breakout
