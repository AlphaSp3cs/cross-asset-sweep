#!/usr/bin/env python3
"""
uber_autotrader.py — master orchestrator.

Wraps: market-hours router + signal engine + risk governor + trade journal
+ analysis brief generator. Every 30 min (ET clock-synced) it:
  1. Reads clock → determines open asset buckets
  2. Dispatches scan to signal engine for each open bucket
  3. Scores every signal (quality, confidence, regime-fit)
  4. Risk governor gates: daily loss, concurrency, correlation, per-signal budget
  5. Fires ranked signals up to cap
  6. Records every order to journal → rolling stats → signal weights adapt
  7. Generates analysis brief the team uses to decide trades
  8. Weekend idle: re-optimize, research, review (hooks only — implement as needed)

Broker-agnostic at the core. Alpaca/MT5 hooks are stub functions you fill in.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def load_config(path: str = "config_uber.json") -> dict:
    p = Path(path)
    if not p.exists():
        return DEFAULT_CONFIG
    with open(p) as f:
        return json.load(f)

DEFAULT_CONFIG = {
    "clock_tz": "America/New_York",
    "scan_interval_minutes": 30,
    "dry_run": false,
    "account_size": 10000.0,
    "market_windows": {
        "FULL": {"weekday": [0,1,2,3,4], "start": "09:00", "end": "16:05"},
        "NO_EQUITIES": {"weekday": [0,1,2,3,6], "start": null, "end": null,
                        "extra": "mon_after_close_to_fri_open, sun_night_to_mon_open"},
        "CRYPTO_ONLY": {"weekday": [4,5,6], "start": null, "end": null,
                        "extra": "fri_405pm_to_sun_1700pm"}
    },
    "asset_buckets": {
        "FULL": ["equities","etfs","indices","crypto","forex","oil","metals","futures"],
        "NO_EQUITIES": ["indices","crypto","forex","oil","metals","futures"],
        "CRYPTO_ONLY": ["crypto"]
    },
    "bots": {
        "alpaca_equities": {"buckets": ["equities","etfs"], "broker": "alpaca"},
        "mt5_forex": {"buckets": ["forex"], "broker": "mt5"},
        "mt5_crypto": {"buckets": ["crypto"], "broker": "mt5"},
        "mt5_indices": {"buckets": ["indices","futures"], "broker": "mt5"},
        "mt5_commodities": {"buckets": ["oil","metals"], "broker": "mt5"}
    },
    "risk": {
        "max_daily_loss_pct": 2.0,
        "max_concurrent_positions": 6,
        "max_exposure_per_signal_pct": 1.5,
        "min_risk_reward": 1.0,
        "correlation_group_threshold": 0.7,
        "slippage_alert_pct": 0.05,
        "api_health_timeout_seconds": 10,
        "trail_stop_1r_breakeven": true,
        "trail_stop_atr_multiplier": 0.5
    },
    "signal_scoring": {
        "multi_tf_bonus": 0.15,
        "volume_confirmation_bonus": 0.10,
        "regime_fit_bonus": 0.10,
        "recency_winrate_weight": 0.4,
        "time_of_day_weight": 0.05,
        "min_score_to_fire": 0.55,
        "signal_ttl_hours": 4.0,
        "auto_suspend_lookback": 20,
        "auto_suspend_wr_threshold": 0.40,
        "auto_resume_wr_threshold": 0.55
    },
    "journal": {
        "path": "trade_journal.jsonl",
        "rolling_stats_window_trades": 50
    },
    "heartbeat_dir": ".heartbeats",
    "analysis_brief_path": "analysis_brief.json",
    "telegram_alert": false
}

# ---------------------------------------------------------------------------
# Market Hours Router
# ---------------------------------------------------------------------------

def et_now() -> datetime:
    return datetime.now(ET)

def parse_time(t: str) -> int:  # "HH:MM" → minutes since midnight
    h, m = t.split(":")
    return int(h)*60 + int(m)

def market_state(now: datetime | None = None) -> str:
    """Returns FULL | NO_EQUITIES | CRYPTO_ONLY | UNKNOWN."""
    now = now or et_now()
    wd = now.weekday()          # Mon=0 … Sun=6
    hm = now.hour*60 + now.minute

    EQUITY_OPEN  = parse_time("09:00")   # 540
    EQUITY_CLOSE = parse_time("16:05")   # 965
    SUN_NIGHT    = parse_time("17:00")   # 1020

    # FULL: Mon-Fri 09:00-16:05
    if wd <= 4 and EQUITY_OPEN <= hm <= EQUITY_CLOSE:
        return "FULL"

    # CRYPTO_ONLY: Fri 16:05 → Sun 17:00
    if (wd == 4 and hm > EQUITY_CLOSE) or wd == 5 or (wd == 6 and hm < SUN_NIGHT):
        return "CRYPTO_ONLY"

    # NO_EQUITIES: Sun 17:00 → Mon 09:00  +  Mon-Thu nights
    if (wd == 6 and hm >= SUN_NIGHT) or (wd == 0 and hm < EQUITY_OPEN):
        return "NO_EQUITIES"
    if wd <= 4:
        return "NO_EQUITIES"

    return "UNKNOWN"

def open_buckets(state: str, cfg: dict) -> list[str]:
    return cfg["asset_buckets"].get(state, ["crypto"])

def bots_for_buckets(buckets: list[str], cfg: dict) -> list[str]:
    """Which bot IDs should run given open buckets."""
    active = []
    for bid, binfo in cfg["bots"].items():
        if any(b in buckets for b in binfo["buckets"]):
            active.append(bid)
    return active

# ---------------------------------------------------------------------------
# Signal Engine (stub — fill in your actual signal logic)
# ---------------------------------------------------------------------------

class SignalEngine:
    """
    Detects signals per asset. Returns list of Signal objects with a
    quality_score 0..1. You replace detect_signals() with your real logic.
    """

    def __init__(self, cfg: dict, journal: TradeJournal = None):
        self.cfg = cfg
        self.scoring = cfg["signal_scoring"]
        self.journal = journal  # set after construction in main()
        self.rolling_wr = {}   # {signal_type: (wins, total, window_start)}
        self.suspended_cache: set[str] = set()

    def detect_signals(self, bucket: str, assets: list[str], now: datetime) -> list["Signal"]:
        """
        Stub. Replace with real signal logic for each bucket.
        Return list of Signal objects.
        """
        signals = []
        for asset in assets:
            # ── EXAMPLE: pull price data (you implement the fetch) ──
            # df = fetch_ohlc(asset, timeframes=["1H","4H","1D"])
            # if is_breakout(df):  ...
            # if is_pullback(df):  ...
            pass
        return signals

    def score_signal(self, sig: "Signal", now: datetime, regime: dict) -> float:
        """0..1 quality score. Higher = more confident.

        Auto-suspension: if the signal type is in the journal's suspended set,
        return 0 immediately — don't even score it.
        """
        # ── P0: Signal-type auto-suspension ──
        if self.journal is not None:
            suspended = self.journal.suspended_types()
            self.suspended_cache = suspended
            if sig.signal_type in suspended:
                return 0.0

        # ── Multi-timeframe directional alignment (P3) ──
        # If daily and 4H disagree on direction, penalize (counter-trend = lower prob).
        # If all timeframes agree, bonus.
        # This requires the signal to carry per-TF direction info — extend Signal as needed.
        # For now, the confirmed_timeframes count already gives partial credit.
        # Directional alignment is a future extension — see ANALYSIS_BRIEF_GUIDE.md.

        s = 0.5  # baseline

        # Multi-timeframe confirmation
        n_tf = len(sig.confirmed_timeframes)
        s += self.scoring["multi_tf_bonus"] * (n_tf - 1)

        # Volume confirmation
        if sig.volume_confirmed:
            s += self.scoring["volume_confirmation_bonus"]

        # Regime fit
        if sig.fits_regime(regime):
            s += self.scoring["regime_fit_bonus"]

        # Recent win-rate weighting
        wr = self.rolling_wr.get(sig.signal_type, (0,0,0))
        if wr[1] > 0:
            recent_wr = wr[0] / wr[1]
            s += self.scoring["recency_winrate_weight"] * (recent_wr - 0.5) * 2  # center at 0.5

        # Time-of-day bonus (e.g. opening range more reliable)
        s += self.scoring["time_of_day_weight"] * self.time_of_day_score(now, sig)

        return max(0.0, min(1.0, s))

    def time_of_day_score(self, now: datetime, sig: "Signal") -> float:
        """Higher reliability at market open / close for equities; neutral for crypto."""
        hm = now.hour*60 + now.minute
        if sig.bucket in ("equities","etfs"):
            if 540 <= hm <= 600:   # 09:00-10:00 open
                return 0.15
            if 900 <= hm <= 965:   # 15:00-16:05 close
                return 0.10
        return 0.0

    def update_winrate(self, signal_type: str, won: bool):
        if signal_type not in self.rolling_wr:
            self.rolling_wr[signal_type] = [0,0,0]
        w, t, _ = self.rolling_wr[signal_type]
        self.rolling_wr[signal_type] = [w+int(won), t+1, time.time()]

# ---------------------------------------------------------------------------
# Signal dataclass
# ---------------------------------------------------------------------------

class Signal:
    __slots__ = ("asset","bucket","signal_type","direction","entry","stop","tp",
                 "confirmed_timeframes","volume_confirmed","reason","score","created_at")

    def __init__(self, asset: str, bucket: str, signal_type: str, direction: str,
                 entry: float, stop: float, tp: float,
                 confirmed_timeframes: list[str] = None,
                 volume_confirmed: bool = False,
                 reason: str = "",
                 score: float = 0.0,
             created_at: datetime = None):
        self.asset = asset
        self.bucket = bucket
        self.signal_type = signal_type      # "breakout","pullback","momentum","mean_reversion",…
        self.direction = direction          # "long","short"
        self.entry = entry
        self.stop  = stop
        self.tp    = tp
        self.confirmed_timeframes = confirmed_timeframes or []
        self.volume_confirmed = volume_confirmed
        self.reason = reason
        self.score = score
        self.created_at = created_at or datetime.now(ET)  # signal birth — used for TTL

    def fits_regime(self, regime: dict) -> bool:
        """Does this signal type fit the current market regime? Override with real logic."""
        # Example: mean_reversion fits ranging regime; breakout fits trending
        trend = regime.get("trend","neutral")
        if self.signal_type == "mean_reversion" and trend in ("down","up"):
            return False
        if self.signal_type == "breakout" and trend == "ranging":
            return False
        return True

    def risk_reward(self) -> float:
        if self.direction == "long":
            return (self.tp - self.entry) / (self.entry - self.stop) if self.stop < self.entry else 0
        else:
            return (self.entry - self.tp) / (self.stop - self.entry) if self.stop > self.entry else 0

    def risk_pct(self, account_size: float) -> float:
        return abs(self.entry - self.stop) / account_size * 100

# ---------------------------------------------------------------------------
# Risk Governor
# ---------------------------------------------------------------------------

class RiskGovernor:
    """
    Gates every trade before it fires. Tracks daily P&L, concurrency,
    correlation overlap, per-signal risk budget, slippage alerts.
    """

    def __init__(self, cfg: dict, account_size: float):
        self.cfg = cfg
        self.account = account_size
        self.risk = cfg["risk"]
        self.daily_pnl = 0.0
        self.daily_loss_limit = self.risk["max_daily_loss_pct"] / 100 * account_size
        self.open_positions = []     # list of position dicts
        self.correlation_groups = {} # asset → group label (fill in your correlation map)
        self.slippage_alerts = {}    # asset → last good fill price

    def can_fire(self, sig: Signal, regime: dict) -> tuple[bool, str]:
        """Returns (allowed, reason)."""
        # 1. daily loss limit
        if self.daily_pnl <= -self.daily_loss_limit:
            return False, "DAILY_LOSS_LIMIT_HIT"

        # 2. concurrency cap
        if len(self.open_positions) >= self.risk["max_concurrent_positions"]:
            return False, "CONCURRENCY_CAP"

        # 3. per-signal risk budget
        exposure = sig.risk_pct(self.account)
        if exposure > self.risk["max_exposure_per_signal_pct"]:
            return False, f"EXPOSURE_TOO_HIGH ({exposure:.2f}% > {self.risk['max_exposure_per_signal_pct']}%)"

        # 4. correlation overlap — don't fire if highly correlated asset already open
        group = self.correlation_groups.get(sig.asset)
        if group:
            for pos in self.open_positions:
                if self.correlation_groups.get(pos["asset"]) == group:
                    return False, f"CORRELATION_OVERLAP ({group})"

        # 5. R:R threshold (from config)
        rr = sig.risk_reward()
        min_rr = self.risk.get("min_risk_reward", 1.0)
        if rr < min_rr:
            return False, f"R_RATIO_TOO_LOW ({rr:.2f} < {min_rr})"

        return True, "OK"

    def record_open(self, sig: Signal, size: float, fill_price: float):
        pos = {
            "asset": sig.asset,
            "signal_type": sig.signal_type,
            "direction": sig.direction,
            "entry": fill_price,
            "stop": sig.stop,
            "tp": sig.tp,
            "size": size,
            "open_time": datetime.now(ET).isoformat(),
            "group": self.correlation_groups.get(sig.asset)
        }
        self.open_positions.append(pos)
        self.slippage_alerts[sig.asset] = fill_price

    def record_close(self, asset: str, exit_price: float, won: bool, pnl: float):
        self.daily_pnl += pnl
        for i, pos in enumerate(self.open_positions):
            if pos["asset"] == asset:
                del self.open_positions[i]
                break
        # slippage check
        last = self.slippage_alerts.get(asset)
        if last and abs(exit_price - last) / last > self.risk["slippage_alert_pct"]:
            logging.warning(f"SLIPPAGE_ALERT {asset}: fill {exit_price} vs {last}")

    def api_health_ok(self, broker: str) -> bool:
        """Check broker API is responding. Stub — implement with your broker."""
        # e.g. alpaca.get_account() or mt5 terminal status
        return True

    def trail_stop(self, asset: str, current_price: float, atr: float = None):
        """Trail the stop-loss for an open position once price moves in favor.
        Activates at 1R profit, then trails at highest_high - 0.5R (or atr-based).

        Stub — implement with your broker's modify-order API.
        """
        for pos in self.open_positions:
            if pos["asset"] == asset:
                if pos["direction"] == "long":
                    profit_pts = current_price - pos["entry"]
                    risk_pts = pos["entry"] - pos["stop"]
                    if risk_pts > 0 and profit_pts >= risk_pts:  # 1R reached
                        # Move stop to breakeven
                        new_stop = pos["entry"]
                        # TODO: if current_price > entry + 2R, trail at current_price - 0.5 * risk_pts
                        logging.info(f"TRAIL_STOP {asset}: moving stop to breakeven {new_stop}")
                        # pos["stop"] = new_stop  # update in-memory; push to broker
                else:  # short
                    profit_pts = pos["entry"] - current_price
                    risk_pts = pos["stop"] - pos["entry"]
                    if risk_pts > 0 and profit_pts >= risk_pts:
                        new_stop = pos["entry"]
                        logging.info(f"TRAIL_STOP {asset}: moving stop to breakeven {new_stop}")

    def reset_daily(self):
        self.daily_pnl = 0.0
        self.open_positions.clear()

# ---------------------------------------------------------------------------
# Trade Journal
# ---------------------------------------------------------------------------

class TradeJournal:
    """
    Records every trade to a JSONL file. Computes rolling stats per signal type.
    Feeds win-rate back into signal engine.
    """

    def __init__(self, cfg: dict):
        self.path = Path(cfg["journal"]["path"])
        self.window = cfg["journal"]["rolling_stats_window_trades"]
        self.rows = []  # in-memory cache

    def load(self):
        if self.path.exists():
            with open(self.path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.rows.append(json.loads(line))

    def record(self, sig: Signal, pos: dict, exit_price: float, won: bool,
               pnl: float, fill_time: datetime, exit_reason: str = "target"):
        row = {
            "asset": sig.asset,
            "signal_type": sig.signal_type,
            "direction": sig.direction,
            "entry": pos["entry"],
            "stop": sig.stop,
            "tp": sig.tp,
            "exit_price": exit_price,
            "size": pos["size"],
            "pnl": pnl,
            "won": won,
            "open_time": pos["open_time"],
            "exit_time": fill_time.isoformat(),
            "exit_reason": exit_reason,
            "r_multiple": pnl / (pos["entry"] - sig.stop) if sig.direction=="long" and sig.stop < sig.entry else 0,
            "bucket": sig.bucket,
            "regime": "",   # fill in at exit time
            "slippage_pts": abs(exit_price - sig.entry)
        }
        self.rows.append(row)
        with open(self.path, "a") as f:
            f.write(json.dumps(row) + "\n")

    def rolling_stats(self, signal_type: str) -> dict:
        """Last N trades of this signal type → win rate, PF, avg R, expectancy."""
        recent = [r for r in self.rows[-self.window:] if r["signal_type"] == signal_type]
        if not recent:
            return {"wr": None, "pf": None, "avg_r": None, "expectancy": None, "n": 0}
        wins = [r for r in recent if r["won"]]
        losses = [r for r in recent if not r["won"]]
        total_r = sum(r["r_multiple"] for r in recent)
        win_r = sum(r["r_multiple"] for r in wins)
        loss_r = sum(abs(r["r_multiple"]) for r in losses)
        return {
            "wr": len(wins)/len(recent),
            "pf": (win_r/abs(loss_r)) if loss_r > 0 else None,
            "avg_r": total_r/len(recent),
            "expectancy": (win_r - abs(loss_r))/len(recent),
            "n": len(recent),
            "profits": [r["pnl"] for r in recent],
            "losses": [r["pnl"] for r in recent]
        }

    def all_signal_stats(self) -> dict:
        types = set(r["signal_type"] for r in self.rows)
        return {t: self.rolling_stats(t) for t in types}

    def suspended_types(self, lookback: int = None, wr_threshold: float = None) -> set[str]:
        """Return signal types whose LAST `lookback` trades have win rate below `wr_threshold`.
        These get auto-suspended — score forced to 0 until the type recovers.

        Recovery: when the type's rolling stats (full window) show wr > 0.55 again,
        it's automatically re-enabled on the next cycle.
        """
        from collections import defaultdict
        if lookback is None:
            lookback = self.cfg.get("signal_scoring", {}).get("auto_suspend_lookback", 20)
        if wr_threshold is None:
            wr_threshold = self.cfg.get("signal_scoring", {}).get("auto_suspend_wr_threshold", 0.40)
        # Walk rows in reverse (newest first), collecting up to `lookback` outcomes per type
        recent: dict[str, list[bool]] = defaultdict(list)
        for r in reversed(self.rows):
            st = r["signal_type"]
            if len(recent[st]) < lookback:
                recent[st].append(r["won"])
        suspended = set()
        for t, outcomes in recent.items():
            if len(outcomes) >= lookback:
                wr = sum(outcomes) / len(outcomes)
                if wr < wr_threshold:
                    suspended.add(t)
        return suspended

# ---------------------------------------------------------------------------
# Analysis Brief Generator — what the team uses
# ---------------------------------------------------------------------------

class AnalysisBrief:
    """
    Generates the structured briefing the team reads to decide trades.
    Dense, scannable, no fluff.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.brief_path = Path(cfg["analysis_brief_path"])

    def generate(self, state: str, regime: dict, signals: list[Signal],
                 risk: RiskGovernor, journal: TradeJournal,
                 engine: SignalEngine, idle_mode: bool = False) -> dict:
        b = {}

        # ── Market State ──
        b["market_state"] = state
        b["clock_et"] = et_now().isoformat()
        b["open_buckets"] = open_buckets(state, self.cfg)
        b["active_bots"] = bots_for_buckets(b["open_buckets"], self.cfg)
        b["is_weekend"] = state == "CRYPTO_ONLY"
        b["is_idle_weekend"] = idle_mode

        # ── Regime ──
        b["regime"] = regime

        # ── Signal Leaderboard (scored & ranked) ──
        scored = []
        for sig in signals:
            s = engine.score_signal(sig, et_now(), regime)
            sig.score = s
            stats = journal.rolling_stats(sig.signal_type)
            scored.append({
                "asset": sig.asset,
                "type": sig.signal_type,
                "direction": sig.direction,
                "entry": sig.entry,
                "stop": sig.stop,
                "tp": sig.tp,
                "rr": sig.risk_reward(),
                "score": round(s,3),
                "bucket": sig.bucket,
                "reason": sig.reason,
                "recent_wr": stats["wr"],
                "recent_pf": stats["pf"],
                "avg_r": stats["avg_r"],
                "n_trades": stats["n"],
                "can_fire": risk.can_fire(sig, regime)[0],
                "fire_reason": risk.can_fire(sig, regime)[1]
            })
        scored.sort(key=lambda x: x["score"], reverse=True)
        b["signal_leaderboard"] = scored

        # ── Open Positions ──
        b["open_positions"] = risk.open_positions

        # ── Risk Status ──
        b["risk"] = {
            "daily_pnl": round(risk.daily_pnl, 2),
            "daily_loss_limit": round(risk.daily_loss_limit, 2),
            "daily_utilization_pct": round(abs(risk.daily_pnl)/risk.daily_loss_limit*100 if risk.daily_loss_limit else 0, 1),
            "concurrency": len(risk.open_positions),
            "max_concurrency": risk.risk["max_concurrent_positions"],
            "api_health": {b: risk.api_health_ok(b) for b in ["alpaca","mt5"]},
            "dry_run": cfg.get("dry_run", False),
            "suspended_signal_types": list(engine.suspended_cache) if engine.suspended_cache else [],
            "signal_ttl_hours": cfg["signal_scoring"]["signal_ttl_hours"],
            "auto_suspend_lookback": cfg["signal_scoring"]["auto_suspend_lookback"],
            "auto_suspend_wr_threshold": cfg["signal_scoring"]["auto_suspend_wr_threshold"],
            "auto_resume_wr_threshold": cfg["signal_scoring"]["auto_resume_wr_threshold"]
        }

        # ── Signal Type Stats (all) ──
        b["signal_type_stats"] = journal.all_signal_stats()

        # ── Top N actionable ──
        actionable = [s for s in scored if s["can_fire"]]
        b["actionable_signals"] = actionable[:risk.risk["max_concurrent_positions"]]

        # ── Idle-Time Research (weekend) ──
        if idle_mode:
            b["idle_research"] = self.idle_research_hook(journal, engine)

        return b

    def idle_research_hook(self, journal: TradeJournal, engine: SignalEngine) -> dict:
        """Weekend idle: what to research/re-optimize. Stub — fill in."""
        stats = journal.all_signal_stats()
        declining = []
        for t, s in stats.items():
            if s["wr"] is not None and s["n"] >= 10 and s["wr"] < 0.45:
                declining.append(t)
        return {
            "declining_signal_types": declining,
            "recommendations": [
                "Re-run backtests on declining signal types with recent data",
                "Research new signal patterns on crypto (only market open)",
                "Review top 10 trades from last week — what made them work?",
                "Check correlation groups — any assets that decoupled?"
            ]
        }

    def save(self, brief: dict):
        self.brief_path.write_text(json.dumps(brief, indent=2, default=str))
        logging.info(f"Analysis brief saved → {self.brief_path}")

# ---------------------------------------------------------------------------
# Main Loop
# ---------------------------------------------------------------------------

def run_once(cfg: dict, engine: SignalEngine, risk: RiskGovernor,
             journal: TradeJournal, brief_gen: AnalysisBrief,
             account_size: float, idle_mode: bool = False):
    now = et_now()
    state = market_state(now)
    buckets = open_buckets(state, cfg)
    bots = bots_for_buckets(buckets, cfg)

    # ── Determine regime (stub — fill in your regime detection) ──
    regime = detect_regime(now, buckets)  # implement

    # ── Scan for signals per bucket ──
    all_signals = []
    for bucket in buckets:
        # assets = get_watchlist(bucket, cfg)  # implement
        assets = []  # stub — fill in
        sigs = engine.detect_signals(bucket, assets, now)
        all_signals.extend(sigs)

    # ── Score & rank ──
    for sig in all_signals:
        sig.score = engine.score_signal(sig, now, regime)

    all_signals.sort(key=lambda s: s.score, reverse=True)

    # ── Fire gated by risk ──
    fired = []
    ttl = timedelta(hours=cfg["signal_scoring"]["signal_ttl_hours"])
    min_score = cfg["signal_scoring"]["min_score_to_fire"]
    dry_run = cfg.get("dry_run", False)

    for sig in all_signals:
        # ── P1: Signal TTL — discard stale signals ──
        if datetime.now(ET) - sig.created_at > ttl:
            logging.debug(f"TTL_DROP {sig.asset} {sig.signal_type} age {datetime.now(ET) - sig.created_at}")
            continue

        ok, reason = risk.can_fire(sig, regime)
        if not ok or sig.score < min_score:
            continue

        size = position_size(sig, account_size, risk, sig.score)
        fill_price = sig.entry  # stub — use real fill
        risk.record_open(sig, size, fill_price)

        if not dry_run:
            execute_trade(sig, size, fill_price, cfg)  # implement — Alpaca/MT5
            fired.append(sig)
            logging.info(f"FIRE {sig.asset} {sig.signal_type} {sig.direction} "
                         f"@{sig.entry} R:R {sig.risk_reward():.2f} score {sig.score:.2f} sz {size:.4f}")
        else:
            logging.info(f"[DRY_RUN] would fire {sig.asset} {sig.signal_type} {sig.direction} "
                         f"@{sig.entry} R:R {sig.risk_reward():.2f} score {sig.score:.2f} sz {size:.4f} "
                         f"fire_reason OK")

    # ── Generate brief ──
    brief = brief_gen.generate(state, regime, all_signals, risk, journal, engine, idle_mode)
    brief_gen.save(brief)

    return brief


def detect_regime(now: datetime, buckets: list[str]) -> dict:
    """Stub regime detection. Fill in with your actual logic.
    Returns trend, volatility, key_levels, etc.
    """
    return {
        "trend": "neutral",        # "up","down","neutral","ranging"
        "volatility": "normal",    # "low","normal","high"
        "key_levels": {},
        "macro_context": {}        # DXY, yields, BTC dominance, etc.
    }


def get_watchlist(bucket: str, cfg: dict) -> list[str]:
    """Stub. Return watchlist assets per bucket. Fill in."""
    return []


def position_size(sig: Signal, account_size: float, risk: RiskGovernor, score: float) -> float:
    """Size the position based on signal risk + account risk budget, scaled by score.

    P1: Score-based sizing — a 0.80 signal gets more capital than a 0.58 signal.
    Base: 1% of account per trade. Scaled up to max_exposure_per_signal_pct as score rises.
    """
    cfg_scoring = risk.cfg.get("signal_scoring", {})
    base_risk_pct = 1.0  # 1% of account as base risk
    max_risk_pct  = risk.cfg["risk"]["max_exposure_per_signal_pct"]

    risk_pts = abs(sig.entry - sig.stop)
    if risk_pts == 0:
        return 0

    # Scale the risk percentage by score: score 0.55 → 1%, 0.70 → ~1.28%, 0.80 → ~1.5%
    # Clamp so we never exceed max_exposure_per_signal_pct
    risk_pct = base_risk_pct + (score - 0.55) * (max_risk_pct - base_risk_pct) / (0.85 - 0.55)
    risk_pct = max(base_risk_pct, min(max_risk_pct, risk_pct))

    risk_amount = account_size * (risk_pct / 100)
    return risk_amount / risk_pts


def execute_trade(sig: Signal, size: float, fill_price: float, cfg: dict):
    """Stub. Place the order via Alpaca/MT5. Implement with your broker."""
    pass


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M:%S")
    cfg = load_config()
    account_size = float(cfg.get("account_size", 10000.0))

    journal = TradeJournal(cfg)
    journal.load()
    engine  = SignalEngine(cfg, journal)  # P0: wire journal for auto-suspension check
    risk    = RiskGovernor(cfg, account_size)
    brief   = AnalysisBrief(cfg)

    # Ensure heartbeat directory exists
    hb_dir = Path(cfg.get("heartbeat_dir", ".heartbeats"))
    hb_dir.mkdir(parents=True, exist_ok=True)
    pidfile = hb_dir / "uber_autotrader.pid"
    heartbeat = hb_dir / "uber_autotrader.heartbeat"

    # Write pidfile so a second instance can detect a running copy
    pidfile.write_text(str(os.getpid()))
    logging.info(f"PID {os.getpid()} written to {pidfile}")

    logging.info(f"uber_autotrader started. ET clock-synced {cfg['scan_interval_minutes']}-min cycles. "
                 f"dry_run={cfg.get('dry_run', False)} account_size={account_size}")
    while True:
        now = et_now()
        state = market_state(now)
        idle_mode = (state == "CRYPTO_ONLY" and now.weekday() == 5)  # Saturday = idle research

        try:
            run_once(cfg, engine, risk, journal, brief, account_size, idle_mode)
            # ── Heartbeat: scrapes tell ops the process is alive ──
            heartbeat.write_text(f"alive {now.isoformat()} pid {os.getpid()} state {state}\n")
        except Exception as e:
            logging.error(f"Cycle failed: {e}")

        # Reset daily at ET midnight
        if now.hour == 0 and now.minute == 0:
            risk.reset_daily()

        # Sleep to next scan mark
        interval = cfg.get("scan_interval_minutes", 30)
        next_mark = (now.replace(second=0, microsecond=0)
                     + timedelta(minutes=interval - (now.minute % interval)))
        wait = (next_mark - now).total_seconds()
        time.sleep(max(0, wait))


if __name__ == "__main__":
    main()
