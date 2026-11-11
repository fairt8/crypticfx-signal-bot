"""Weekly strategy report + systemd timer units (mocked DB / Telegram).
Run: python -m pytest -q tests/test_weekly_report.py
Does not call Telegram, Neon, Binance or Yahoo."""
import os, sys, re
os.environ.update(DATABASE_URL="", TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="1",
                  MEXC_API_KEY="", MEXC_API_SECRET="", WEEX_API_KEY="", WEEX_API_SECRET="", WEEX_API_PASSPHRASE="",
                  AUTOTRADE_WORKER="0", ENABLE_SCHEDULER="0",
                  OPENMARKET_API_KEY="", OPENMARKET_ENABLED="0")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone, timedelta
from pathlib import Path
import pytest
from app import config as C, db, don20, telegram, weekly_report as WR

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 11, 8, 53, tzinfo=timezone.utc)   # 09:53 WAT


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(C, "DATABASE_URL", "")
    monkeypatch.setattr(C, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(C, "TELEGRAM_CHAT_ID", "1")
    db.PG = False
    db.init(); don20.init()
    yield


def _sig(*, symbol="BTCUSDT", strategy="BRK", direction="long", entry=100000.0, sl=99000.0,
         status="tp", result_r=1.5, created=None, closed=None, confirm=None):
    created = created or NOW.isoformat()
    confirm = confirm or created
    s = dict(symbol=symbol, market="crypto", direction=direction, entry=entry, sl=sl,
             tp=entry + (3 if direction == "long" else -3) * abs(entry - sl), rr=3.0,
             confidence=50, in_session=1, reasons=["x"], htf_top=None, htf_bottom=None,
             htf_time=None, tap_time=None, confirm_time=confirm, price_now=entry,
             strategy=strategy, tags=[strategy], experimental=0, status="pending", filled_at=None)
    i = db.insert(s)
    assert i is not None
    kw = dict(created_at=created)
    if status in db.CLOSED:
        kw.update(status=status, result_r=result_r, closed_at=(closed or created),
                  filled_at=created)
    elif status in ("open", "pending"):
        kw.update(status=status, filled_at=created if status == "open" else None)
    else:
        kw.update(status=status)
    db.update(i, **kw)
    return i


def _don(*, symbol="ETHUSDT", k="DON20", status="closed", net_r=0.5, result_r=0.6,
         opened=None, closed=None, direction="long"):
    opened = opened or NOW.isoformat()
    day = opened[:10]
    with db.conn() as c:
        c.execute(
            f"INSERT INTO {don20.TABLE[k]}(symbol,direction,signal_day,opened_at,entry,init_stop,stop,atr,best_close,"
            f"status,closed_at,exit_price,result_r,net_r,posted) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (symbol, direction, day, opened, 2000.0, 1900.0, 1900.0, 10.0, 2000.0,
             status, closed if status == "closed" else None,
             2050.0 if status == "closed" else None,
             result_r if status == "closed" else None,
             net_r if status == "closed" else None, 0))


def test_week_vs_alltime_and_dollar_pnl(fresh, monkeypatch):
    monkeypatch.setattr(WR, "_mark_open", lambda rows: rows)
    week_ago = (NOW - timedelta(days=3)).isoformat()
    old = (NOW - timedelta(days=40)).isoformat()
    # BRK: one win this week (+1.5R gross; net after 0.10% crypto cost on 1% stop = 1.5 - 0.1 = 1.4)
    # and one older loss, plus one open this week
    _sig(strategy="BRK", symbol="BTCUSDT", result_r=1.5, created=week_ago, closed=week_ago, confirm="c-brk-w")
    _sig(strategy="BRK", symbol="SOLUSDT", result_r=-1.0, created=old, closed=old, confirm="c-brk-o")
    _sig(strategy="BRK", symbol="ADAUSDT", status="open", created=week_ago, confirm="c-brk-open")
    # DON20: one win this week (net_r already stored), one older closed, one open
    _don(symbol="ETHUSDT", net_r=2.0, result_r=2.2, opened=week_ago, closed=week_ago, status="closed")
    _don(symbol="BNBUSDT", net_r=-1.0, result_r=-0.9, opened=old, closed=old, status="closed")
    _don(symbol="XRPUSDT", status="open", opened=week_ago, net_r=None, result_r=None)
    profit = {"BRK": dict(profitable=False, verdict="📉 not profitable (live 30d: -5.00R, 12 trades)"),
              "DON20": dict(profitable=True, verdict="💰 profitable")}
    data = WR.collect(now=NOW, profit_table=profit)
    brk_w = data["week"]["strategies"]["BRK"]
    brk_a = data["all_time"]["strategies"]["BRK"]
    assert brk_w["signals"] == 2 and brk_w["closed"] == 1 and brk_w["open"] == 1
    assert brk_a["signals"] == 3 and brk_a["closed"] == 2 and brk_a["open"] == 1
    # net_r on the week win: 1.5 - 0.001/0.01 = 1.4
    assert brk_w["net_r"] == 1.4 and brk_w["pnl_usd"] == 14.0
    assert brk_w["win_rate"] == 100.0
    # all-time: 1.4 + (-1.0 - 0.1) = 0.3
    assert brk_a["closed"] == 2 and brk_a["net_r"] == pytest.approx(0.3) and brk_a["pnl_usd"] == pytest.approx(3.0)
    don_w = data["week"]["strategies"]["DON20"]
    don_a = data["all_time"]["strategies"]["DON20"]
    assert don_w["closed"] == 1 and don_w["net_r"] == 2.0 and don_w["pnl_usd"] == 20.0 and don_w["open"] == 1
    assert don_a["closed"] == 2 and don_a["net_r"] == 1.0 and don_a["pnl_usd"] == 10.0
    assert data["unprofitable"] and data["unprofitable"][0]["key"] == "BRK"
    assert data["account"] == dict(start=1000, risk=10)
    text = WR.format_report(data, now=NOW)
    assert "Weekly strategy report" in text
    assert "BRK" in text and "DON20" in text
    assert "PRIMARY" in text and "SECONDARY" in text
    assert "$1,000 account, $10 / 1R" in text
    assert "not profitable" in text
    assert "week:" in text and "all-time:" in text
    assert "Signal generation and alerts are unchanged" in text
    # WAT label on the header
    assert "WAT" in text


def test_unprofitable_note_when_none_flagged(fresh, monkeypatch):
    monkeypatch.setattr(WR, "_mark_open", lambda rows: rows)
    data = WR.collect(now=NOW, profit_table={"MF-REJ": dict(profitable=True), "BRK": dict(profitable=None)})
    text = WR.format_report(data, now=NOW)
    assert "None of the live strategies with enough data are flagged as unprofitable" in text
    assert "Retired" in text and "FVG" in text


def test_build_and_main_no_telegram(fresh, monkeypatch):
    monkeypatch.setattr(WR, "_mark_open", lambda rows: rows)
    sent = []
    monkeypatch.setattr(telegram, "send_long", lambda *a, **k: sent.append(a) or True)
    monkeypatch.setattr(telegram, "enabled", lambda: True)
    monkeypatch.setattr(C, "TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(C, "TELEGRAM_BOT_TOKEN", "x")
    text = WR.build(now=NOW, profit_table={})
    assert "Weekly strategy report" in text
    assert WR.main(["--no-telegram"]) == 0
    assert sent == []


def test_main_sends_and_records(fresh, monkeypatch):
    monkeypatch.setattr(WR, "_mark_open", lambda rows: rows)
    sent = []
    monkeypatch.setattr(telegram, "send_long", lambda text, chat_id=None, html=False: sent.append(dict(text=text, html=html)) or True)
    monkeypatch.setattr(telegram, "enabled", lambda: True)
    monkeypatch.setattr(C, "TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(C, "TELEGRAM_BOT_TOKEN", "dummy")
    monkeypatch.setattr(WR, "build", lambda: "hello report")
    assert WR.main([]) == 0
    assert sent and sent[0]["html"] is True and sent[0]["text"] == "hello report"
    assert db.kv_get(WR.KV_LAST)


def test_main_fails_when_unconfigured_or_send_fails(fresh, monkeypatch):
    monkeypatch.setattr(WR, "_mark_open", lambda rows: rows)
    monkeypatch.setattr(WR, "build", lambda: "x")
    monkeypatch.setattr(telegram, "enabled", lambda: False)
    monkeypatch.setattr(C, "TELEGRAM_CHAT_ID", "1")
    assert WR.main([]) == 1
    monkeypatch.setattr(telegram, "enabled", lambda: True)
    monkeypatch.setattr(C, "TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(telegram, "send_long", lambda *a, **k: False)
    assert WR.main([]) == 1


def test_systemd_units():
    d = ROOT / "deploy" / "systemd"
    weekly_s = (d / "fvg-weekly-report.service").read_text()
    weekly_t = (d / "fvg-weekly-report.timer").read_text()
    monthly_s = (d / "fvg-monthly-backtest.service").read_text()
    monthly_t = (d / "fvg-monthly-backtest.timer").read_text()
    for text in (weekly_s, monthly_s):
        assert "User=fvg" in text
        assert "EnvironmentFile=/etc/fvg-signal-bot.env" in text
        assert "WorkingDirectory=/opt/fvg-signal-bot/app" in text
        assert "/opt/fvg-signal-bot/venv/bin/python" in text
        assert "MemoryMax=" in text
        assert "TimeoutStartSec=" in text
        assert "Nice=" in text
    assert "python -m app.weekly_report" in weekly_s
    assert "python -m app.backtest_all" in monthly_s
    assert "--days 1096" in monthly_s and "--workers 1" in monthly_s
    assert "Persistent=true" in weekly_t and "Persistent=true" in monthly_t
    assert "OnCalendar=Mon *-*-* 09:53:00 Africa/Lagos" in weekly_t
    assert "OnCalendar=*-*-01 09:00:00 Africa/Lagos" in monthly_t
    blob = weekly_s + weekly_t + monthly_s + monthly_t
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", blob)
    assert "sslip" not in blob.lower()
    assert "TELEGRAM_BOT_TOKEN=" not in blob
    assert "DATABASE_URL=" not in blob
    assert "BEGIN" not in blob and "PRIVATE KEY" not in blob


def test_backtest_all_default_is_at_least_3_years():
    src = (ROOT / "app" / "backtest_all.py").read_text()
    m = re.search(r'add_argument\("--days".*?default=(\d+)', src)
    assert m and int(m.group(1)) >= 1095
    # unit also pins the same floor
    unit = (ROOT / "deploy" / "systemd" / "fvg-monthly-backtest.service").read_text()
    m2 = re.search(r"--days\s+(\d+)", unit)
    assert m2 and int(m2.group(1)) >= 1095
