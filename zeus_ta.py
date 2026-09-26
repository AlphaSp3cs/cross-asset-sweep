"""
zeus_ta.py — pure-Python technical analysis module. Zero external dependencies.

Every indicator computes from OHLCV as list of rows:
    row = (ts, open, high, low, close, volume)
    ts is epoch seconds (int); others are float.

Functions return float or list[float]; missing data returns None.
Designed for scanning: pass a window of ~200 candles and read off features.

Author: Hermes agent (built for zeus-brain)
"""

from __future__ import annotations
import math
from typing import List, Optional, Tuple, Dict, Any


Row = Tuple[int, float, float, float, float, float]  # ts, o, h, l, c, v


# ── helpers ────────────────────────────────────────────────────────────────────

def _closes(rows: List[Row]) -> List[float]:
    return [r[4] for r in rows]


def _closes_tail(rows: List[Row]) -> List[float]:
    """Last n closes using the most recent n rows."""
    return [r[4] for r in rows]


def _sma(values: List[float], n: int) -> Optional[float]:
    if len(values) < n or n < 1:
        return None
    return sum(values[-n:]) / n


def _ema(values: List[float], n: int, alpha: Optional[float] = None) -> Optional[float]:
    """Exponential moving average. alpha = 2/(n+1) by default (textbook)."""
    if alpha is None:
        alpha = 2.0 / (n + 1)
    if len(values) < n:
        return None
    ema = values[0]
    for v in values[1:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def _wilder_smooth(values: List[float], n: int) -> float:
    """Wilder smoothing average (alpha = 1/n)."""
    if not values:
        return None
    alpha = 1.0 / n
    s = values[0]
    for v in values[1:]:
        s = alpha * v + (1 - alpha) * s
    return s


def _typical(rows: List[Row]) -> List[float]:
    return [(r[2] + r[3] + r[4]) / 3.0 for r in rows]


def _hlc(rows: List[Row]) -> List[float]:
    return [(r[2] + r[3] + r[4]) / 3.0 for r in rows]


def _ohlc_average(rows: List[Row]) -> float:
    return sum(r[1] + r[2] + r[3] + r[4] for r in rows) / (4.0 * len(rows))


def _true_range(rows: List[Row]) -> List[float]:
    tr = []
    prev_close = None
    for i, r in enumerate(rows):
        h, l, c = r[2], r[3], r[4]
        if i == 0:
            tr.append(h - l)
        else:
            pc = prev_close
            tr.append(max(h - l, abs(h - pc), abs(l - pc)))
        prev_close = c
    return tr


# ── trend indicators ───────────────────────────────────────────────────────────

def sma(rows: List[Row], period: int) -> Optional[float]:
    """Simple moving average of closes."""
    if period < 1 or len(rows) < period:
        return None
    return sum(r[4] for r in rows[-period:]) / period


def ema(rows: List[Row], period: int) -> Optional[float]:
    """Exponential moving average of closes (alpha = 2/(period+1))."""
    if period < 1 or len(rows) < period:
        return None
    closes = _closes(rows)
    alpha = 2.0 / (period + 1)
    ema_val = closes[0]
    for c in closes[1:]:
        ema_val = alpha * c + (1 - alpha) * ema_val
    return ema_val


def macd(rows: List[Row], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, Optional[float]]:
    """Return MACD line, signal line, and histogram."""
    if len(rows) < slow:
        return {"macd": None, "signal": None, "histogram": None}
    closes = _closes(rows)
    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    if fast_ema is None or slow_ema is None:
        return {"macd": None, "signal": None, "histogram": None}
    macd_line = fast_ema - slow_ema
    # signal line = EMA of macd line
    # compute macd history for signal
    macd_hist = []
    for i in range(slow, len(closes) + 1):
        f = _ema(closes[:i], fast)
        s = _ema(closes[:i], slow)
        if f is not None and s is not None:
            macd_hist.append(f - s)
    if len(macd_hist) < signal:
        return {"macd": macd_line, "signal": None, "histogram": None}
    sig = _ema(macd_hist, signal)
    if sig is None:
        return {"macd": macd_line, "signal": None, "histogram": None}
    return {"macd": macd_line, "signal": sig, "histogram": macd_line - sig}


def psar(rows: List[Row], step: float = 0.02, max_step: float = 0.2) -> Optional[float]:
    """Parabolic SAR. Returns current PSAR value. Direction: +1 (uptrend) or -1 (downtrend)."""
    if len(rows) < 2:
        return None
    # initialize
    psar_val = rows[0][3]       # start at first low
    ep = rows[0][2]             # extreme point = first high
    trend = 1                   # 1 = uptrend, -1 = downtrend
    af = step
    for i in range(1, len(rows)):
        h, l = rows[i][2], rows[i][3]
        if trend == 1:
            psar_val = psar_val + af * (ep - psar_val)
            if l < psar_val:
                # reversal
                trend = -1
                psar_val = ep
                ep = l
                af = step
            else:
                if h > ep:
                    ep = h
                    af = min(af + step, max_step)
        else:
            psar_val = psar_val + af * (ep - psar_val)
            if h > psar_val:
                # reversal
                trend = 1
                psar_val = ep
                ep = h
                af = step
            else:
                if l < ep:
                    ep = l
                    af = min(af + step, max_step)
    return psar_val


# ── momentum indicators ────────────────────────────────────────────────────────

def rsi(rows: List[Row], period: int = 14) -> Optional[float]:
    """Relative Strength Index (Wilder smoothing)."""
    if len(rows) < period + 1:
        return None
    closes = _closes(rows)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    if not gains or not losses:
        return 50.0
    avg_gain = _wilder_smooth(gains, period)
    avg_loss = _wilder_smooth(losses, period)
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def stoch(rows: List[Row], period: int = 14, smooth_k: int = 3, smooth_d: int = 3) -> Dict[str, Optional[float]]:
    """Stochastic Oscillator (%K smoothed, %D smoothed-K)."""
    if len(rows) < period:
        return {"k": None, "d": None}
    highs = [r[2] for r in rows]
    lows = [r[3] for r in rows]
    closes = _closes(rows)
    k_raw = []
    for i in range(period - 1, len(closes)):
        hh = max(highs[i - period + 1:i + 1])
        ll = min(lows[i - period + 1:i + 1])
        if hh == ll:
            k_raw.append(50.0)
        else:
            k_raw.append(100.0 * (closes[i] - ll) / (hh - ll))
    if len(k_raw) < smooth_k:
        return {"k": k_raw[-1] if k_raw else None, "d": None}
    k_smooth_vals = []
    for i in range(smooth_k - 1, len(k_raw)):
        k_smooth_vals.append(sum(k_raw[i - smooth_k + 1:i + 1]) / smooth_k)
    if len(k_smooth_vals) < smooth_d:
        return {"k": k_smooth_vals[-1] if k_smooth_vals else None, "d": None}
    d_vals = []
    for i in range(smooth_d - 1, len(k_smooth_vals)):
        d_vals.append(sum(k_smooth_vals[i - smooth_d + 1:i + 1]) / smooth_d)
    return {"k": k_smooth_vals[-1] if k_smooth_vals else None, "d": d_vals[-1] if d_vals else None}


def williams_r(rows: List[Row], period: int = 14) -> Optional[float]:
    """Williams %R. Range -100..0."""
    if len(rows) < period:
        return None
    highs = [r[2] for r in rows[-period:]]
    lows = [r[3] for r in rows[-period:]]
    close = rows[-1][4]
    hh = max(highs)
    ll = min(lows)
    if hh == ll:
        return 0.0
    return -100.0 * (hh - close) / (hh - ll)


def cci(rows: List[Row], period: int = 20) -> Optional[float]:
    """Commodity Channel Index."""
    if len(rows) < period:
        return None
    tp = _typical(rows[-period:])
    mean_tp = sum(tp) / len(tp)
    md = sum(abs(t - mean_tp) for t in tp) / len(tp)
    if md == 0:
        return 0.0
    c = (tp[-1] - mean_tp) / (0.015 * md)
    return c


def roc(rows: List[Row], period: int = 14) -> Optional[float]:
    """Rate of change (%)."""
    if len(rows) < period + 1:
        return None
    return 100.0 * (rows[-1][4] - rows[-period - 1][4]) / rows[-period - 1][4]


# ── volatility indicators ──────────────────────────────────────────────────────

def atr(rows: List[Row], period: int = 14) -> Optional[float]:
    """Average True Range."""
    if len(rows) < period + 1:
        return None
    tr = _true_range(rows)
    return _wilder_smooth(tr[-len(tr):], period) if tr else None


def bollinger_bands(rows: List[Row], period: int = 20, std_mult: float = 2.0) -> Dict[str, Optional[float]]:
    """Return middle, upper, lower bands and %B."""
    if len(rows) < period:
        return {"mid": None, "upper": None, "lower": None, "pct_b": None}
    closes = _closes(rows[-period:])
    mid = sum(closes) / len(closes)
    variance = sum((c - mid) ** 2 for c in closes) / len(closes)
    std = math.sqrt(variance)
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    current = rows[-1][4]
    if upper == lower:
        pct_b = 0.5
    else:
        pct_b = (current - lower) / (upper - lower)
    return {"mid": mid, "upper": upper, "lower": lower, "pct_b": pct_b}


def keltner_channels(rows: List[Row], period: int = 20, atr_mult: float = 2.0) -> Dict[str, Optional[float]]:
    """Keltner Channels using EMA middle + ATR bands."""
    if len(rows) < period + 1:
        return {"mid": None, "upper": None, "lower": None}
    mid = ema(rows, period)
    atr_val = atr(rows, period)
    if mid is None or atr_val is None:
        return {"mid": None, "upper": None, "lower": None}
    return {"mid": mid, "upper": mid + atr_mult * atr_val, "lower": mid - atr_mult * atr_val}


def donchian(rows: List[Row], period: int = 20) -> Dict[str, Optional[float]]:
    """Donchian Channel upper/lower (highest high / lowest low over period)."""
    if len(rows) < period:
        return {"upper": None, "lower": None, "mid": None}
    highs = [r[2] for r in rows[-period:]]
    lows = [r[3] for r in rows[-period:]]
    upper = max(highs)
    lower = min(lows)
    return {"upper": upper, "lower": lower, "mid": (upper + lower) / 2.0}


# ── volume indicators ──────────────────────────────────────────────────────────

def obv(rows: List[Row]) -> Optional[float]:
    """On-Balance Volume. Cumulative. Returns current OBV."""
    if not rows:
        return None
    obv_val = 0.0
    prev_close = None
    for r in rows:
        c, v = r[4], r[5]
        if prev_close is None:
            obv_val = v
        elif c > prev_close:
            obv_val += v
        elif c < prev_close:
            obv_val -= v
        prev_close = c
    return obv_val


def ad(rows: List[Row]) -> Optional[float]:
    """Accumulation/Distribution Line."""
    if not rows:
        return None
    ad_val = 0.0
    for i, r in enumerate(rows):
        h, l, c, v = r[2], r[3], r[4], r[5]
        if h == l:
            continue
        mfm = ((c - l) - (h - c)) / (h - l)
        ad_val += mfm * v
    return ad_val


# ── structure / regime ─────────────────────────────────────────────────────────

def swing_high(rows: List[Row], left: int = 2, right: int = 2) -> Optional[int]:
    """Index of most recent swing high (peak with `left` higher before and `right` higher after)."""
    if len(rows) < left + right + 1:
        return None
    for i in range(len(rows) - right - 1, left - 1, -1):
        h = rows[i][2]
        left_ok = all(rows[j][2] < h for j in range(i - left, i))
        right_ok = all(rows[j][2] < h for j in range(i + 1, i + right + 1))
        if left_ok and right_ok:
            return i
    return None


def swing_low(rows: List[Row], left: int = 2, right: int = 2) -> Optional[int]:
    """Index of most recent swing low."""
    if len(rows) < left + right + 1:
        return None
    for i in range(len(rows) - right - 1, left - 1, -1):
        l = rows[i][3]
        left_ok = all(rows[j][3] > l for j in range(i - left, i))
        right_ok = all(rows[j][3] > l for j in range(i + 1, i + right + 1))
        if left_ok and right_ok:
            return i
    return None


def support_resistance(rows: List[Row], left: int = 5, right: int = 3, max_zones: int = 5) -> Dict[str, Any]:
    """Return recent swing highs (resistance) and swing lows (support)."""
    highs_idx = []
    lows_idx = []
    for i in range(left, len(rows) - right):
        h = rows[i][2]
        if all(rows[j][2] < h for j in range(i - left, i)) and \
           all(rows[j][2] < h for j in range(i + 1, i + right + 1)):
            highs_idx.append(i)
        l = rows[i][3]
        if all(rows[j][3] > l for j in range(i - left, i)) and \
           all(rows[j][3] > l for j in range(i + 1, i + right + 1)):
            lows_idx.append(i)
    sr = {
        "resistance": [rows[i][2] for i in highs_idx[-max_zones:]],
        "support": [rows[i][3] for i in lows_idx[-max_zones:]],
        "resistance_index": highs_idx[-max_zones:],
        "support_index": lows_idx[-max_zones:]
    }
    return sr


def adx(rows: List[Row], period: int = 14) -> Optional[float]:
    """Average Directional Index (simplified). Returns ADX value (trend strength 0-100).

    Uses true range smoothing and directional movement approximation.
    Good enough for relative regime comparison; not a textbook ADX.
    """
    if len(rows) < period + 1:
        return None
    tr = _true_range(rows[-period:])
    if not tr:
        return None
    atr_val = _wilder_smooth(tr, period)
    if atr_val == 0:
        return 0.0
    closes = _closes(rows[-period:])
    plus_dm, minus_dm = [], []
    for i in range(1, len(closes)):
        up_move = closes[i] - closes[i - 1]
        dn_move = closes[i - 1] - closes[i]
        if up_move > dn_move and up_move > 0:
            plus_dm.append(up_move)
        else:
            plus_dm.append(0.0)
        if dn_move > up_move and dn_move > 0:
            minus_dm.append(dn_move)
        else:
            minus_dm.append(0.0)
    if len(plus_dm) < period:
        return None
    plus_avg = _wilder_smooth(plus_dm[-period:], period)
    minus_avg = _wilder_smooth(minus_dm[-period:], period)
    if plus_avg + minus_avg == 0:
        return 0.0
    dx = 100.0 * abs(plus_avg - minus_avg) / (plus_avg + minus_avg)
    return min(100.0, dx)


def regime(rows: List[Row]) -> str:
    """Market regime: 'uptrend', 'downtrend', 'range', or 'unknown'.
    Uses EMA slope (20 vs 50 if available) and price position."""
    if len(rows) < 50:
        return "unknown"
    ema20 = ema(rows, 20)
    ema50 = ema(rows, 50)
    close = rows[-1][4]
    if ema20 is None or ema50 is None:
        return "unknown"
    if ema20 > ema50 and close > ema20:
        return "uptrend"
    if ema20 < ema50 and close < ema20:
        return "downtrend"
    return "range"


# ── feature extraction (for scanning) ──────────────────────────────────────────

def feature_vector(rows: List[Row]) -> Dict[str, Any]:
    """Compute all features for one asset/timeframe. Returns dict of indicator values."""
    f: Dict[str, Any] = {
        "close": rows[-1][4] if rows else None,
        "volume": rows[-1][5] if rows else None,
        "ts": rows[-1][0] if rows else None,
        "sma_20": sma(rows, 20),
        "sma_50": sma(rows, 50),
        "sma_200": sma(rows, 200),
        "ema_12": ema(rows, 12),
        "ema_26": ema(rows, 26),
        "ema_20": ema(rows, 20),
        "ema_50": ema(rows, 50),
        "ema_200": ema(rows, 200),
        "macd": macd(rows),
        "rsi_14": rsi(rows, 14),
        "rsi_7": rsi(rows, 7),
        "rsi_21": rsi(rows, 21),
        "stoch": stoch(rows),
        "williams_r": williams_r(rows, 14),
        "cci_20": cci(rows, 20),
        "roc_14": roc(rows, 14),
        "atr_14": atr(rows, 14),
        "bollinger": bollinger_bands(rows),
        "keltner": keltner_channels(rows),
        "donchian": donchian(rows),
        "obv": obv(rows),
        "ad": ad(rows),
        "psar": psar(rows),
        "regime": regime(rows),
        "swing_high": swing_high(rows),
        "swing_low": swing_low(rows),
        "support_resistance": support_resistance(rows),
        "xtick_count": len(rows),
    }
    return f


def multi_timeframe_alignment(
    tf_features: Dict[str, Dict[str, Any]],
    tf_order: List[str] = None
) -> Dict[str, Any]:
    """Assess directional alignment across multiple timeframes.

    tf_features: { "1h": feature_dict, "4h": feature_dict, "1d": feature_dict }
    tf_order: list of TF keys in highest-to-lowest priority (default: ["1h","4h","1d"])

    Returns:
        {
            "alignment_score": 0..3 (number of TFs bullish minus bearish, normalized),
            "bullish_count": int,
            "bearish_count": int,
            "neutral_count": int,
            "tf_reads": {tf: "bullish"|"bearish"|"neutral"|"unknown" for each tf},
            "strongest_signal": "bullish" | "bearish" | "neutral" | "mixed",
            "summary": str
        }
    """
    if tf_order is None:
        tf_order = ["1h", "4h", "1d"]
    bullish, bearish, neutral = 0, 0, 0
    tf_reads = {}
    for tf in tf_order:
        fd = tf_features.get(tf, {})
        regime_ = fd.get("regime", "unknown")
        rsi = fd.get("rsi_14")
        macd = fd.get("macd")
        macd_sig = macd.get("signal") if isinstance(macd, dict) else None
        macd_line = macd.get("macd") if isinstance(macd, dict) else None
        # determine direction
        direction = "unknown"
        if regime_ == "uptrend" and (rsi is None or rsi > 50):
            direction = "bullish"
        elif regime_ == "downtrend" and (rsi is None or rsi < 50):
            direction = "bearish"
        elif rsi is not None:
            if rsi > 60:
                direction = "bullish"
            elif rsi < 40:
                direction = "bearish"
        elif macd_line is not None and macd_sig is not None:
            if macd_line > macd_sig:
                direction = "bullish"
            elif macd_line < macd_sig:
                direction = "bearish"
        elif regime_ == "uptrend":
            direction = "bullish"
        elif regime_ == "downtrend":
            direction = "bearish"
        elif regime_ == "range":
            direction = "neutral"
        tf_reads[tf] = direction
        if direction == "bullish":
            bullish += 1
        elif direction == "bearish":
            bearish += 1
        else:
            neutral += 1
    total = bullish + bearish + neutral
    if total == 0:
        alignment_score = 0.0
    else:
        alignment_score = (bullish - bearish) / max(total, 1)
    if bullish > bearish and bearish == 0:
        strongest = "bullish"
    elif bearish > bullish and bullish == 0:
        strongest = "bearish"
    elif bullish == bearish:
        strongest = "neutral"
    else:
        strongest = "mixed"
    summary = f"{bullish} bullish, {bearish} bearish, {neutral} neutral across {len(tf_features)} TFs"
    return {
        "alignment_score": round(alignment_score, 2),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
        "tf_reads": tf_reads,
        "strongest_signal": strongest,
        "summary": summary
    }


# ── backtest helper: simulate a simple signal on historical rows ────────────────

def backtest_sma_cross(
    rows: List[Row],
    fast: int = 12,
    slow: int = 26,
    stop_pct: float = 0.05,
    tp_pct: float = 0.15
) -> Dict[str, Any]:
    """Simple backtest: SMA(fast) crossover SMA(slow) entry/exit with stop and target.
    Returns stats. NOT production-grade — a starting point for validation."""
    if len(rows) < slow + 2:
        return {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "wr": 0.0, "error": "insufficient data"}
    closes = _closes(rows)
    trades, wins, losses, pnl = 0, 0, 0, 0.0
    in_trade = False
    entry_idx = None
    entry_price = None
    stop_price = None
    tp_price = None
    peak = None
    for i in range(slow, len(closes)):
        # compute indicators at i
        fast_sma = _sma(closes[:i], fast)
        slow_sma = _sma(closes[:i], slow)
        if fast_sma is None or slow_sma is None:
            continue
        if not in_trade:
            if fast_sma > slow_sma:
                in_trade = True
                entry_idx = i
                entry_price = closes[i]
                stop_price = entry_price * (1 - stop_pct)
                tp_price = entry_price * (1 + tp_pct)
                peak = entry_price
        else:
            c = closes[i]
            if c <= stop_price:
                # stop hit
                pnl += stop_price - entry_price
                in_trade = False
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades += 1
                stop_price = tp_price = peak = None
            elif c >= tp_price:
                # target hit
                pnl += tp_price - entry_price
                in_trade = False
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades += 1
                stop_price = tp_price = peak = None
            else:
                # trail stop / track peak
                if c > peak:
                    peak = c
                    stop_price = peak * (1 - stop_pct)
    wr = wins / trades if trades else 0.0
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "pnl": round(pnl, 4),
        "wr": round(wr, 3),
        "avg_win": round(pnl / max(wins, 1), 4),
        "avg_loss": round((-pnl) / max(losses, 1), 4) if losses else None
    }


def backtest_atr_expand(
    rows: List[Row],
    atr_period: int = 14,
    atr_mult_entry: float = 1.5,
    atr_mult_stop: float = 2.0,
    atr_mult_tp: float = 3.0,
    min_score: float = 0.5
) -> Dict[str, Any]:
    """ATR expansion breakout: enter when price breaks a multiple of ATR above recent high,
    stop at ATR multiple below entry, target at ATR multiple above entry.
    Simplified — a starting point for the ATR_EXPANSION system."""
    if len(rows) < atr_period + 3:
        return {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "wr": 0.0, "error": "insufficient data"}
    atr_vals = []
    for i in range(atr_period, len(rows)):
        atr_v = atr(rows[:i], atr_period)
        if atr_v is None:
            continue
        atr_vals.append((i, atr_v))
    if not atr_vals:
        return {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "wr": 0.0, "error": "no ATR data"}
    close = [r[4] for r in rows]
    high = [r[2] for r in rows]
    trades, wins, losses, pnl = 0, 0, 0, 0.0
    in_trade = False
    entry_price = None
    stop_price = None
    tp_price = None
    for idx, atr_v in atr_vals:
        if not in_trade:
            recent_high = max(high[idx - atr_period:idx])
            breakout_level = recent_high + atr_mult_entry * atr_v
            if close[idx] > breakout_level:
                in_trade = True
                entry_price = close[idx]
                stop_price = entry_price - atr_mult_stop * atr_v
                tp_price = entry_price + atr_mult_tp * atr_v
        else:
            c = close[idx]
            if c <= stop_price:
                pnl += stop_price - entry_price
                in_trade = False
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades += 1
                entry_price = stop_price = tp_price = None
            elif c >= tp_price:
                pnl += tp_price - entry_price
                in_trade = False
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades += 1
                entry_price = stop_price = tp_price = None
    wr = wins / trades if trades else 0.0
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "pnl": round(pnl, 4),
        "wr": round(wr, 3),
        "avg_win": round(pnl / max(wins, 1), 4),
        "avg_loss": round((-pnl) / max(losses, 1), 4) if losses else None
    }


def backtest_rsi_reversion(
    rows: List[Row],
    period: int = 14,
    oversold: float = 30.0,
    overbought: float = 70.0,
    stop_pct: float = 0.05,
    tp_pct: float = 0.10
) -> Dict[str, Any]:
    """RSI mean reversion: long when RSI < oversold and rising, exit on target or stop.
    Simplified — a starting point."""
    if len(rows) < period + 2:
        return {"trades": 0, "wins": 0, "losses": 0, "pnl": 0.0, "wr": 0.0, "error": "insufficient data"}
    closes = _closes(rows)
    trades, wins, losses, pnl = 0, 0, 0, 0.0
    in_trade = False
    entry_price = None
    stop_price = None
    tp_price = None
    prev_rsi = None
    for i in range(period + 1, len(closes)):
        rsi_v = rsi(rows[:i], period)
        if rsi_v is None:
            continue
        if not in_trade:
            if prev_rsi is not None and prev_rsi < oversold and rsi_v >= prev_rsi:
                in_trade = True
                entry_price = closes[i]
                stop_price = entry_price * (1 - stop_pct)
                tp_price = entry_price * (1 + tp_pct)
        else:
            c = closes[i]
            if c <= stop_price:
                pnl += stop_price - entry_price
                in_trade = False
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades += 1
                entry_price = stop_price = tp_price = None
            elif c >= tp_price:
                pnl += tp_price - entry_price
                in_trade = False
                if pnl > 0:
                    wins += 1
                else:
                    losses += 1
                trades += 1
                entry_price = stop_price = tp_price = None
        prev_rsi = rsi_v
    wr = wins / trades if trades else 0.0
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "pnl": round(pnl, 4),
        "wr": round(wr, 3),
        "avg_win": round(pnl / max(wins, 1), 4),
        "avg_loss": round((-pnl) / max(losses, 1), 4) if losses else None
    }


# ── batch scanning helper ──────────────────────────────────────────────────────

def scan_many(
    assets: Dict[str, List[Row]],
    min_rows: int = 50
) -> Dict[str, Dict[str, Any]]:
    """Compute feature_vector for each asset that has enough rows.
    Returns {symbol: feature_dict}."""
    result = {}
    for sym, rows in assets.items():
        if len(rows) < min_rows:
            continue
        result[sym] = feature_vector(rows)
    return result


def scan_signals(
    features: Dict[str, Dict[str, Any]],
    require_mtf: bool = False,
    mtf_features: Dict[str, Dict[str, Any]] = None,
    min_score: float = 0.5
) -> List[Dict[str, Any]]:
    """From feature vectors, detect candidate signals. Returns list of signal dicts."""
    signals = []
    for sym, f in features.items():
        if f.get("regime") == "unknown":
            continue
        close = f.get("close")
        if close is None:
            continue
        score = 0.5
        reasons = []
        direction = None
        signal_type = None
        entry = None
        stop = None
        tp = None
        mtf_align = None
        if mtf_features:
            mtf = multi_timeframe_alignment(mtf_features)
            mtf_align = mtf.get("tf_reads", {})
            if mtf.get("strongest_signal") == "bullish":
                score += 0.15
                reasons.append("MTF_bullish")
            elif mtf.get("strongest_signal") == "bearish":
                score -= 0.10
                reasons.append("MTF_bearish")
        rsi = f.get("rsi_14")
        macd = f.get("macd")
        macd_line = macd.get("macd") if isinstance(macd, dict) else None
        macd_sig = macd.get("signal") if isinstance(macd, dict) else None
        bb = f.get("bollinger")
        atr_v = f.get("atr_14")
        regime_ = f.get("regime", "unknown")
        # Trend-following long: regime uptrend, MACD bullish, RSI 50-70
        if regime_ == "uptrend" and macd_line is not None and macd_sig is not None and macd_line > macd_sig:
            if rsi is not None and 50 < rsi < 75:
                signal_type = "momentum_long"
                direction = "long"
                score = max(score, 0.65)
                reasons.append(f"uptrend_macd_bullish_rsi_{rsi:.0f}")
        # Pullback long: regime uptrend, RSI pulled below 40, MACD still positive or near cross
        if regime_ == "uptrend" and rsi is not None and rsi < 40:
            if macd_line is not None and macd_sig is not None and macd_line > macd_sig:
                signal_type = "pullback_long"
                direction = "long"
                score = max(score, 0.70)
                reasons.append(f"uptrend_pullback_rsi_{rsi:.0f}")
        # Mean-reversion long: RSI oversold, regime not strongly downtrend
        if rsi is not None and rsi < 30 and regime_ != "downtrend":
            signal_type = "reversion_long"
            direction = "long"
            score = max(score, 0.60)
            reasons.append(f"rsi_oversold_{rsi:.0f}")
        # Breakdown short: regime downtrend, MACD bearish, RSI 50-25
        if regime_ == "downtrend" and macd_line is not None and macd_sig is not None and macd_line < macd_sig:
            if rsi is not None and 25 < rsi < 50:
                signal_type = "momentum_short"
                direction = "short"
                score = max(score, 0.65)
                reasons.append(f"downtrend_macd_bearish_rsi_{rsi:.0f}")
        # Rejection from resistance: price near BB upper, RSI > 70
        if bb and rsi is not None and rsi > 70:
            upper = bb.get("upper")
            if upper and close and close > upper * 0.98:
                signal_type = "rejection_short"
                direction = "short"
                score = max(score, 0.55)
                reasons.append(f"bb_upper_rejection_rsi_{rsi:.0f}")
        # Breakout long: price breaks BB upper or Donchian upper with volume
        if bb and f.get("volume"):
            upper = bb.get("upper")
            if upper and close and close > upper and f["volume"] > f.get("volume", 0) * 1.5:
                signal_type = "breakout_long"
                direction = "long"
                score = max(score, 0.70)
                reasons.append("bb_breakout_volume")
        if signal_type and direction and score >= min_score:
            if atr_v and atr_v > 0:
                stop = round(close * (1 - 0.02) if direction == "long" else close * (1 + 0.02), 4)
                tp = round(close * 1.03 if direction == "long" else close * 0.97, 4)
                entry = round(close, 4)
            signals.append({
                "symbol": sym,
                "signal_type": signal_type,
                "direction": direction,
                "entry": entry,
                "stop": stop,
                "tp": tp,
                "score": round(score, 2),
                "reasons": reasons,
                "rsi": rsi,
                "macd": macd,
                "bollinger": bb,
                "atr": atr_v,
                "regime": regime_,
                "mtf_alignment": mtf_align,
                "ts": f.get("ts")
            })
    return sorted(signals, key=lambda s: s["score"], reverse=True)


# ── demo / quick test ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import random
    random.seed(42)
    # generate 300 rows of synthetic data with a trend + noise
    rows: List[Row] = []
    price = 100.0
    for i in range(300):
        ts = i * 3600
        o = price
        h = price + random.uniform(0, 3)
        l = price - random.uniform(0, 3)
        c = price + random.uniform(-2, 2)
        v = random.uniform(100, 1000)
        rows.append((ts, o, max(h, c), min(l, c), c, v))
        price = c + random.uniform(-1, 1)
    fv = feature_vector(rows)
    print("=== feature_vector (last 300 synthetic candles) ===")
    for k in ["close", "sma_20", "sma_50", "sma_200", "ema_12", "ema_26",
              "macd", "rsi_14", "rsi_7", "rsi_21", "stoch", "williams_r",
              "cci_20", "roc_14", "atr_14", "bollinger", "donchian",
              "obv", "psar", "regime"]:
        print(f"  {k}: {fv.get(k)}")
    print()
    print("=== multi-timeframe_alignment (single TF mock) ===")
    mtf = multi_timeframe_alignment({"1h": fv})
    for k, v in mtf.items():
        print(f"  {k}: {v}")
    print()
    print("=== signals ===")
    sigs = scan_signals({"SYNTH": fv}, require_mtf=False)
    for s in sigs[:5]:
        print(f"  {s['symbol']} {s['signal_type']} {s['direction']} "
              f"entry={s['entry']} stop={s['stop']} tp={s['tp']} score={s['score']} "
              f"reasons={s['reasons']}")
    print()
    print("=== backtest SMA cross (last 250 of 300) ===")
    bt = backtest_sma_cross(rows[-250:])
    for k, v in bt.items():
        print(f"  {k}: {v}")
    print()
    print("=== backtest ATR expand (last 250 of 300) ===")
    bt2 = backtest_atr_expand(rows[-250:])
    for k, v in bt2.items():
        print(f"  {k}: {v}")
    print()
    print("=== backtest RSI reversion (last 250 of 300) ===")
    bt3 = backtest_rsi_reversion(rows[-250:])
    for k, v in bt3.items():
        print(f"  {k}: {v}")
