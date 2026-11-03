"""The candlestick patterns of the '21 Candlesticks' PDF, coded from its validity conditions (vectorised, no look-ahead).

Every detector returns a boolean array `raw[i]` = the pattern's LAST candle is bar i. `signals()` then applies the PDF's
next-candle confirmation where the PDF asks for it ("the day after ... one should witness continued buying/selling",
"confirmation is required by the candles that follow the Pattern"): the signal completes on bar i+1 if that candle closes
in the trade direction (bull: white and close > previous close; bear mirror). Entry = close of the completing bar.

Shared definitions (the PDF gives no numbers except 'shadow >= 2x body'):
  body = |c-o|, range = h-l, upper/lower shadow as usual; doji: body <= 10% of range; small/short body: <= 30% of range;
  long candle: body >= 1.2x the mean body of the previous 20 bars AND >= 50% of its range; "no / very small shadow": <= 10% of
  range (marubozu: <= 5%); "same level (more or less)": within 0.05 x ATR14.
  Prior trend ("definite uptrend / downtrend before the signal", PDF): on the bar BEFORE the pattern's first candle,
  close < SMA20 and close < close 10 bars earlier (downtrend); mirror for uptrend.
Gap rules: crypto trades 24/7, so the next candle opens at the previous close and the PDF's gap conditions (piercing opens
below the prior LOW, dark cloud above the prior HIGH, star gaps, kicker) almost never occur. Each gap pattern therefore exists
twice: '<NAME>' = PDF-exact, '<NAME>~' = gap rule relaxed to 'opens at/beyond the previous close/body'."""
import numpy as np, pandas as pd

def _sh(x, k):
    y = np.empty_like(x); 
    if x.dtype == bool: y[:k] = False
    else: y[:k] = np.nan
    y[k:] = x[:-k] if k else x; return y

def atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]; tr = np.maximum(h-l, np.maximum(abs(h-pc), abs(l-pc)))
    return pd.Series(tr).rolling(n, min_periods=1).mean().values

class F:
    """Candle features of one timeframe."""
    def __init__(s, df):
        o, h, l, c = (df[k].values.astype(float) for k in "ohlc")
        s.o, s.h, s.l, s.c = o, h, l, c
        s.body = abs(c-o); s.rng = np.maximum(h-l, 1e-12); s.top = np.maximum(o, c); s.bot = np.minimum(o, c)
        s.up = h - s.top; s.lo = s.bot - l; s.white = c > o; s.black = c < o
        mb = pd.Series(s.body).rolling(20, min_periods=5).mean().shift(1).values
        s.long = (s.body >= 1.2*mb) & (s.body >= 0.5*s.rng)
        s.doji = s.body <= 0.1*s.rng; s.small = s.body <= 0.3*s.rng
        s.atr = atr(h, l, c); s.mid = (o+c)/2; s.hl2 = (h+l)/2
        sma20 = pd.Series(c).rolling(20).mean().values; c10 = _sh(c, 10)
        s.DN = (c < sma20) & (c < c10); s.UP = (c > sma20) & (c > c10)
        s.sma200 = pd.Series(c).rolling(200).mean().values
    def p(s, a, k): return _sh(a, k)            # value k bars ago
    def tr_dn(s, n): return _sh(s.DN, n)         # downtrend before an n-bar pattern ending at i
    def tr_up(s, n): return _sh(s.UP, n)

def near(s, a, b): return abs(a - b) <= 0.05*s.atr

def detect(s):
    """name -> (direction, n_bars, needs_confirmation, raw bool array)."""
    P, R = s.p, {}
    o, h, l, c = s.o, s.h, s.l, s.c
    o1, h1, l1, c1 = P(o, 1), P(h, 1), P(l, 1), P(c, 1)
    w1, b1, L1 = P(s.white, 1), P(s.black, 1), P(s.long, 1)
    # 1 Doji star: a doji after a long candle in the trend direction (PDF: 'tug of war'); exact = star body gaps away
    for gap, nm in ((True, "DOJI_STAR"), (False, "DOJI_STAR~")):
        gb = (s.top < c1) if gap else np.ones_like(s.doji); gs = (s.bot > c1) if gap else np.ones_like(s.doji)
        R[nm + "_BULL"] = ("long", 2, True, s.tr_dn(2) & b1 & L1 & s.doji & gb)
        R[nm + "_BEAR"] = ("short", 2, True, s.tr_up(2) & w1 & L1 & s.doji & gs)
    # 2 Long-legged doji: doji, both shadows long, a 'dramatic' (>= 1.3 ATR) range; in an uptrend a close below the midpoint = weakness
    ll = s.doji & (s.up >= 0.3*s.rng) & (s.lo >= 0.3*s.rng) & (s.rng >= 1.3*P(s.atr, 1))
    R["LL_DOJI_BEAR"] = ("short", 1, True, s.tr_up(1) & ll & (c < s.hl2))
    R["LL_DOJI_BULL"] = ("long", 1, True, s.tr_dn(1) & ll & (c > s.hl2))
    # 3 Gravestone doji (bearish after a rally) / 4 Dragonfly doji (bullish after a decline)
    R["GRAVESTONE"] = ("short", 1, True, s.tr_up(1) & s.doji & (s.lo <= 0.1*s.rng) & (s.up >= 0.7*s.rng))
    R["DRAGONFLY"] = ("long", 1, True, s.tr_dn(1) & s.doji & (s.up <= 0.1*s.rng) & (s.lo >= 0.7*s.rng))
    # 5 Hanging man / 6 Hammer: definite up/down trend, lower shadow >= 2x body, no or very small upper shadow, next candle confirms
    hm = (s.lo >= 2*s.body) & (s.lo >= 0.6*s.rng) & (s.up <= 0.1*s.rng)
    R["HANGING_MAN"] = ("short", 1, True, s.tr_up(1) & hm)
    R["HAMMER"] = ("long", 1, True, s.tr_dn(1) & hm)
    # 7 Inverted hammer / 8 Shooting star: upper shadow >= 2x body, no or very small lower shadow, next candle confirms
    ss = (s.up >= 2*s.body) & (s.up >= 0.6*s.rng) & (s.lo <= 0.1*s.rng)
    R["INV_HAMMER"] = ("long", 1, True, s.tr_dn(1) & ss)
    R["SHOOTING_STAR"] = ("short", 1, True, s.tr_up(1) & ss)
    # 9/10 Engulfing: white opens below the prior (black) close and closes above its open; bearish mirror. ~ = opens AT the prior close too
    for st, nm in ((True, "ENGULF"), (False, "ENGULF~")):
        lt = (o < c1) if st else (o <= c1); gt = (o > c1) if st else (o >= c1)
        R[nm + "_BULL"] = ("long", 2, False, s.tr_dn(2) & b1 & s.white & lt & (c > o1))
        R[nm + "_BEAR"] = ("short", 2, False, s.tr_up(2) & w1 & s.black & gt & (c < o1))
    # 11/12 Harami: large prior body, second candle of the opposite colour opens above the prior close and closes below the prior open (inside the body)
    for st, nm in ((True, "HARAMI"), (False, "HARAMI~")):
        gt = (o > c1) if st else (o >= c1); lt = (o < c1) if st else (o <= c1)
        R[nm + "_BULL"] = ("long", 2, False, s.tr_dn(2) & b1 & L1 & s.white & gt & (c < o1))
        R[nm + "_BEAR"] = ("short", 2, False, s.tr_up(2) & w1 & L1 & s.black & lt & (c > o1))
    # 13 Piercing: fairly large black, white opens below the prior LOW (~: at/below the prior close), closes > halfway into the black body (not above its open)
    # 14 Dark cloud cover: white, black opens above the prior HIGH (~: at/above the prior close), closes > halfway into the white body
    for st, nm in ((True, ""), (False, "~")):
        R["PIERCING" + nm] = ("long", 2, False, s.tr_dn(2) & b1 & L1 & s.white & ((o < l1) if st else (o <= c1)) & (c > P(s.mid, 1)) & (c < o1))
        R["DARK_CLOUD" + nm] = ("short", 2, False, s.tr_up(2) & w1 & ((o > h1) if st else (o >= c1)) & s.black & (c < P(s.mid, 1)) & (c > o1))
    # 15 Morning star / 16 Evening star: long body, small-bodied star (exact: its body gaps beyond the first close), long opposite candle reaching >= halfway into the first body
    b2, w2, L2, c2, mid2 = P(s.black, 2), P(s.white, 2), P(s.long, 2), P(c, 2), P(s.mid, 2)
    sm1, top1, bot1 = P(s.small, 1), P(s.top, 1), P(s.bot, 1)
    for st, nm in ((True, ""), (False, "~")):
        R["MORNING_STAR" + nm] = ("long", 3, False, s.tr_dn(3) & b2 & L2 & sm1 & ((top1 < c2) if st else True) & s.white & s.long & (c >= mid2))
        R["EVENING_STAR" + nm] = ("short", 3, False, s.tr_up(3) & w2 & L2 & sm1 & ((bot1 > c2) if st else True) & s.black & s.long & (c <= mid2))
    # 17 Three white soldiers: after a decline, three long white candles, each opening within the prior body / upper half of its range, closing near the high
    ws = s.white & (s.body >= 0.5*s.rng) & (s.up <= 0.2*s.rng)
    op_in = (o >= P(s.hl2, 1)) & (o <= c1)
    R["3_SOLDIERS"] = ("long", 3, False, s.tr_dn(3) & ws & P(ws, 1) & P(ws, 2) & op_in & P(op_in, 1) & (c > c1) & (c1 > c2))
    # 18 Three black crows: after a rally, three long black candles, each opening above the prior close (within its body) and closing at a new low
    bc = s.black & (s.body >= 0.5*s.rng)
    op_c = (o > c1) & (o <= o1)
    R["3_CROWS"] = ("short", 3, False, s.tr_up(3) & bc & P(bc, 1) & P(bc, 2) & op_c & P(op_c, 1) & (c < c1) & (c1 < c2))
    # 19 Tweezer bottom / top: two consecutive candles with (nearly) identical lows / highs, then the bounce (confirmation)
    R["TWEEZER_BOT"] = ("long", 2, True, s.tr_dn(2) & near(s, l, l1) & (P(s.lo, 1) + s.lo > 0))
    R["TWEEZER_TOP"] = ("short", 2, True, s.tr_up(2) & near(s, h, h1) & (P(s.up, 1) + s.up > 0))
    # 20 Marubozu: long candle with no shadows; follow-through next candle -> trend in the same direction (no prior-trend rule in the PDF)
    mz = s.long & (s.up <= 0.05*s.rng) & (s.lo <= 0.05*s.rng)
    R["MARUBOZU_BULL"] = ("long", 1, True, mz & s.white)
    R["MARUBOZU_BEAR"] = ("short", 1, True, mz & s.black)
    # 21 Kicker: in a decline the last black candle closes at the bottom of its range, next candle gaps above the prior high and close (~: opens above the prior open) and is white
    R["KICKER_BULL"] = ("long", 2, False, s.tr_dn(2) & b1 & (P(s.lo, 1) <= 0.1*P(s.rng, 1)) & s.white & (o > h1))
    R["KICKER_BEAR"] = ("short", 2, False, s.tr_up(2) & w1 & (P(s.up, 1) <= 0.1*P(s.rng, 1)) & s.black & (o < l1))
    R["KICKER~_BULL"] = ("long", 2, False, s.tr_dn(2) & b1 & (P(s.lo, 1) <= 0.1*P(s.rng, 1)) & s.white & s.long & (o >= o1))
    R["KICKER~_BEAR"] = ("short", 2, False, s.tr_up(2) & w1 & (P(s.up, 1) <= 0.1*P(s.rng, 1)) & s.black & s.long & (o <= o1))
    # ---- extra PDF patterns with clear rules (continuation / multi-candle)
    # Rising / falling three methods: long candle, three small counter-trend candles inside its range, 5th long candle closing beyond the 1st close
    c4, o4, h4, l4, L4 = P(c, 4), P(o, 4), P(h, 4), P(l, 4), P(s.long, 4)
    inside = lambda k: (P(h, k) <= h4) & (P(l, k) >= l4)
    smallmid = (P(s.body, 1) < P(s.body, 4)) & (P(s.body, 2) < P(s.body, 4)) & (P(s.body, 3) < P(s.body, 4))
    ins = inside(1) & inside(2) & inside(3) & smallmid
    R["RISING_3"] = ("long", 5, True, s.tr_up(5) & P(s.white, 4) & L4 & ins & (c1 <= P(c, 3)) & s.white & s.long & (c > c4))
    R["FALLING_3"] = ("short", 5, True, s.tr_dn(5) & P(s.black, 4) & L4 & ins & (c1 >= P(c, 3)) & s.black & s.long & (c < c4))
    # Three-line strike (continuation): 3 rising white candles, then a long black opening above the last close and closing below the first open
    w3 = P(s.white, 3) & P(s.white, 2) & w1 & (c2 > P(c, 3)) & (c1 > c2)
    b3 = P(s.black, 3) & P(s.black, 2) & b1 & (c2 < P(c, 3)) & (c1 < c2)
    R["3_LINE_STRIKE_BULL"] = ("long", 4, True, s.tr_up(4) & w3 & s.black & (o >= c1) & (c < P(o, 3)))
    R["3_LINE_STRIKE_BEAR"] = ("short", 4, True, s.tr_dn(4) & b3 & s.white & (o <= c1) & (c > P(o, 3)))
    # Stick sandwich: black (new low), white with body above the first close, black closing at the first close
    R["STICK_SANDWICH_BULL"] = ("long", 3, True, s.tr_dn(3) & b2 & (P(s.lo, 2) <= 0.1*P(s.rng, 2)) & w1 & (o1 >= c2) & s.black & (o >= c1) & near(s, c, c2))
    R["STICK_SANDWICH_BEAR"] = ("short", 3, True, s.tr_up(3) & w2 & (P(s.up, 2) <= 0.1*P(s.rng, 2)) & b1 & (o1 <= c2) & s.white & (o <= c1) & near(s, c, c2))
    # Homing pigeon: long black, then a shorter black whose body sits inside the first body; Matching low: two blacks closing at the same level
    R["HOMING_PIGEON"] = ("long", 2, True, s.tr_dn(2) & b1 & L1 & s.black & (o < o1) & (c > c1) & (s.body < P(s.body, 1)))
    R["MATCHING_LOW"] = ("long", 2, True, s.tr_dn(2) & b1 & L1 & s.black & (o > c1) & near(s, c, c1))
    # Bullish squeeze alert: black candle, then two candles each with a lower high and a higher low
    R["SQUEEZE_ALERT"] = ("long", 3, False, s.tr_dn(3) & b2 & (h1 < P(h, 2)) & (l1 > P(l, 2)) & (h < h1) & (l > l1))
    for k, v in R.items(): R[k] = (v[0], v[1], v[2], np.nan_to_num(np.asarray(v[3], dtype=float)).astype(bool))
    return R

def base_name(nm):
    """Pattern family (one of the 21 + extras), e.g. ENGULF~_BULL -> ENGULF."""
    return nm.replace("~", "").replace("_BULL", "").replace("_BEAR", "")

CORE21 = ["DOJI_STAR", "LL_DOJI", "GRAVESTONE", "DRAGONFLY", "HANGING_MAN", "HAMMER", "INV_HAMMER", "SHOOTING_STAR", "ENGULF", "HARAMI",
          "PIERCING", "DARK_CLOUD", "MORNING_STAR", "EVENING_STAR", "3_SOLDIERS", "3_CROWS", "TWEEZER_BOT", "TWEEZER_TOP", "MARUBOZU", "KICKER"]

def signals(s, R=None):
    """Completed signals: list of (name, direction, i_complete, i_first) with the PDF confirmation applied."""
    R = R or detect(s); out = []
    bull_conf = s.white & (s.c > _sh(s.c, 1)); bear_conf = s.black & (s.c < _sh(s.c, 1))
    for nm, (d, n, conf, raw) in R.items():
        if conf:
            cf = bull_conf if d == "long" else bear_conf
            idx = np.where(_sh(raw, 1) & cf)[0]; first = idx - n
        else:
            idx = np.where(raw)[0]; first = idx - n + 1
        for i, f in zip(idx, first):
            if f >= 1: out.append((nm, d, int(i), int(f)))
    return out
