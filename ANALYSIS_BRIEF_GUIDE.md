# UBER AUTOTRADER — Team Analysis Brief

**Purpose:** Every 30 min (ET clock-synced) the system generates a structured briefing
at `analysis_brief.json`. This doc tells the team WHAT TO LOOK AT and HOW TO DECIDE
whether to take a trade. The system handles the mechanical parts — clock, scan, scoring,
risk gating, journaling. The team reads the brief and decides on the actionable signals.

---

## HOW THE CYCLE WORKS

```
Every 30 min (ET clock-synced):
  1. Clock check → market state (FULL / NO_EQUITIES / CRYPTO_ONLY)
  2. Open buckets determined → bots dispatched
  3. Signal engine scans watchlist for each open bucket
  4. Every signal scored 0..1 (multi-TF, volume, regime, recency WR, time-of-day)
  5. P0: Signal auto-suspension — if a signal type's last 20 trades have win rate < 40%,
     that type is automatically suspended (score forced to 0) until recovery
  6. Risk governor gates: daily loss, concurrency, correlation, R:R, slippage
  7. Ranked signals → fire top N up to concurrency cap, sized by signal score
  8. Every trade → journal → rolling stats → win-rate weights update
  9. P1: Dry-run mode — set config.dry_run=true to generate signals + brief WITHOUT firing
 10. P1: Signal TTL — signals older than 4h are discarded (stale setups don't fire)
 11. P1: Score-based sizing — higher score = more capital (1% at 0.55 → 1.5% at 0.80)
 12. P1: Trail-stop — moves stop to breakeven at 1R profit
 13. Every trade → journal → rolling stats → win-rate weights update
 14. Brief generated → team reads → decides
 15. Weekend idle: re-optimize, research, review (hooks available)
 16. Heartbeat written every cycle → ops can scrape to verify process is alive
```

The team's job: read `analysis_brief.json`, look at the actionable signals, verify the
setup, decide whether to take it. The system already screened for quality and risk.

**Auto-suspension (P0):** If any signal type is in `risk.suspended_signal_types`, its
signals get score 0 and won't fire. Check `signal_type_stats` to see which types are
declining. The system recovers a suspended type when its rolling stats show WR > 55%.

**Dry-run (P1):** Set `"dry_run": true` in config. The system scans, scores, gates, and
generates the full brief — but never fires. Every fire line shows `[DRY_RUN] would fire`.
Use this to validate the pipeline before going live.

**Signal TTL (P1):** Stale signals get dropped before the risk gate. A breakout detected at
10:00 that hasn't triggered by 14:00 is dead — don't fire on it. Configurable via
`signal_ttl_hours` (default 4h).

**Score-based sizing (P1):** A 0.80 signal gets more capital than a 0.58 signal. Base 1% at
score 0.55, scaling linearly to max_exposure (1.5%) at score 0.80+. This means the system
naturally allocates more to high-conviction signals without manual intervention.

**Trail-stop (P1):** When a long position reaches 1R profit, the stop moves to breakeven.
The system logs the trail event. To push to the broker, implement the TODO in
`risk.trail_stop()`. Short positions mirror the logic.
  8. Brief generated → team reads → decides
  9. Weekend idle: re-optimize, research, review (hooks available)
```

The team's job: read `analysis_brief.json`, look at the actionable signals, verify the
setup, decide whether to take it. The system already screened for quality and risk.

---

## WHAT THE TEAM READS — analysis_brief.json STRUCTURE

### Section 1: Market State
```json
{
  "market_state": "FULL",          // FULL | NO_EQUITIES | CRYPTO_ONLY
  "clock_et": "2026-09-26T14:30:00-04:00",
  "open_buckets": ["equities","crypto","forex","oil","metals","indices","futures"],
  "active_bots": ["alpaca_equities","mt5_forex","mt5_crypto","mt5_indices","mt5_commodities"],
  "is_weekend": false,
  "is_idle_weekend": false
}
```
**Team action:** Know what markets are live. If it's CRYPTO_ONLY, no equity signals will fire.
If FULL, everything is open.

---

### Section 2: Regime Context
```json
{
  "regime": {
    "trend": "neutral",       // up | down | neutral | ranging
    "volatility": "normal",   // low | normal | high
    "key_levels": {},
    "macro_context": {}
  }
}
```
**Team action:** Check this before trusting any signal. A mean-reversion signal in a trending
market is low-probability. A breakout in a ranging market is low-probability. The system
downgrades those automatically via `fits_regime()`, but the team should verify the regime
reading is correct.

**To implement:** Fill in `detect_regime()` with your actual logic — moving average slope,
ADX, ATR vs. history, correlation breakdown detection, macro inputs from the sweep.

---

### Section 3: Signal Leaderboard (RANKED — read top to bottom)
```json
{
  "signal_leaderboard": [
    {
      "asset": "BTCUSDT",
      "type": "breakout",
      "direction": "long",
      "entry": 84500.0,
      "stop": 83200.0,
      "tp": 87500.0,
      "rr": 2.35,              // risk/reward ratio
      "score": 0.72,           // 0..1 quality score
      "bucket": "crypto",
      "reason": "4H breakout above 83.5K with volume + daily confirmation",
      "recent_wr": 0.58,       // last 50 trades of this signal type: 58% win rate
      "recent_pf": 1.6,        // profit factor
      "avg_r": 0.45,           // average R multiple per trade
      "n_trades": 47,          // sample size
      "can_fire": true,        // risk governor approved
      "fire_reason": "OK"
    },
    ...
  ]
}
```
**Team action:** Read top to bottom. The system has already:
- Scored each signal on quality
- Checked risk governor (daily loss, concurrency, correlation, R:R)
- Ranked them

Your job: **verify the setup makes sense**, check the score, check the recent stats,
then decide. If `can_fire: false`, the reason is in `fire_reason` — read it.

**Score interpretation:**
- 0.70+ = strong — multi-TF confirmed, volume, regime fit, good recent WR
- 0.55-0.69 = moderate — passes minimum but verify before trusting
- Below 0.55 = filtered out by minimum threshold

**Recent WR / PF / avg R:** These come from the journal's last 50 trades of this signal
type. If `n_trades < 10`, the stats are noisy — treat with caution. If recent WR has
dropped below 0.45, flag it for review.

---

### Section 4: Open Positions
```json
{
  "open_positions": [
    {
      "asset": "ETHUSDT",
      "signal_type": "momentum",
      "direction": "long",
      "entry": 2650.0,
      "stop": 2580.0,
      "tp": 2850.0,
      "size": 0.5,
      "open_time": "2026-09-26T10:30:00-04:00",
      "group": "crypto"
    }
  ]
}
```
**Team action:** Know what's already on. Before approving a new signal that overlaps with an
open position in the same correlation group, decide if you want both or just one.

---

### Section 5: Risk Status
```json
{
  "risk": {
    "daily_pnl": -120.50,           // today's P&L
    "daily_loss_limit": 200.00,     // 2% of account
    "daily_utilization_pct": 60.3,  // how much of the limit used
    "concurrency": 2,               // open positions
    "max_concurrency": 6,           // cap
    "api_health": {"alpaca": true, "mt5": true}
  }
}
```
**Team action:**
- If `daily_utilization_pct > 80%` → be conservative on new signals today. Risk budget is
  nearly exhausted.
- If `api_health` shows any broker as false → that bot's signals are blocked until it recovers.
- If `daily_pnl` is at or past the loss limit → system is paused. Investigate before resuming.
- **P0:** If `suspended_signal_types` is non-empty, those types are NOT firing. Check why —
  declining win rate. The system will re-enable them when rolling WR exceeds 55%.
- **P1:** If `dry_run: true`, NO trades are being fired. The system is in validation mode.
- **P1:** `signal_ttl_hours` shows how old a signal can be before it's discarded.
- **P0:** `auto_suspend_lookback` / `auto_suspend_wr_threshold` / `auto_resume_wr_threshold`
  show the auto-suspension config that's active this cycle.

---

### Section 6: Signal Type Stats (ALL — for diagnostics)
```json
{
  "signal_type_stats": {
    "breakout": {
      "wr": 0.58,
      "pf": 1.6,
      "avg_r": 0.45,
      "expectancy": 0.28,     // avg R per trade — positive = edge
      "n": 47,
      "profits": [...],
      "losses": [...]
    },
    "pullback": {
      "wr": 0.42,
      "pf": 0.9,              // below 1.0 — losing money on this type
      ...
    }
  }
}
```
**Team action:** This is the diagnostic view. If any signal type shows:
- `wr < 0.45` AND `n >= 10` → it's declining. Flag for review.
- `pf < 1.0` → losing money. Investigate why.
- `expectancy < 0` → negative edge. Stop using or re-optimize.

The system uses these stats to weight signals (declining signal types get lower scores
automatically via `recency_winrate_weight`).

---

### Section 7: Actionable Signals (already gated — team's decision list)
```json
{
  "actionable_signals": [
    {
      "asset": "BTCUSDT",
      "type": "breakout",
      "direction": "long",
      "entry": 84500.0,
      "stop": 83200.0,
      "tp": 87500.0,
      "rr": 2.35,
      "score": 0.72,
      "reason": "4H breakout above 83.5K with volume + daily confirmation",
      "recent_wr": 0.58,
      "recent_pf": 1.6,
      "n_trades": 47
    }
  ]
}
```
**This is the team's decision list.** Every signal here has:
- Passed the risk governor (no daily loss limit hit, concurrency not full, no correlation
  overlap, R:R ≥ 1.0, exposure within budget)
- Scored above the minimum threshold

**Team decision process per signal:**
1. Read the `reason` — does the setup make sense?
2. Check `recent_wr` and `recent_pf` — is this signal type working right now?
3. Check `rr` — is the risk/reward acceptable?
4. Check `open_positions` — does it overlap with anything already on?
5. Decide: TAKE / SKIP / REDUCE_SIZE / MOVE_STOP

---

### Section 8: Idle-Weekend Research (Saturdays only)
```json
{
  "idle_research": {
    "declining_signal_types": ["pullback"],
    "recommendations": [
      "Re-run backtests on declining signal types with recent data",
      "Research new signal patterns on crypto (only market open)",
      "Review top 10 trades from last week — what made them work?",
      "Check correlation groups — any assets that decoupled?"
    ]
  }
}
```
**Team action:** On Saturdays, the system is in idle research mode. Read the
recommendations and assign work. Use the downtime to improve the system rather than
letting it sit idle.

---

## TEAM DECISION FRAMEWORK

### When to TAKE a signal:
- Score 0.65+ AND recent WR > 0.50 AND PF > 1.0 AND R:R > 1.5
- Setup makes sense on the chart
- No correlation overlap that would concentrate risk
- Daily risk budget has room

### When to SKIP a signal:
- Score below 0.60 even if it passed the gate
- Recent WR < 0.45 (declining signal type — let it cool off)
- R:R < 1.5 (tight edge, not worth the risk)
- Setup doesn't make sense on the chart (false breakout, etc.)
- Overlaps with an existing position in the same correlation group

### When to REDUCE SIZE:
- Score 0.55-0.64 (borderline)
- Daily risk budget > 60% utilized
- High volatility regime (wider stops = more risk)

### When to MOVE STOP:
- Trade moves in your favor — trail stop to breakeven at 1R
- Regime changes mid-trade (e.g. trend reverses) — tighten or exit

---

## THE FIVE IMPLEMENTATION HOOKS

The system is broker-agnostic. You fill in these five stubs:

### 1. `detect_regime(now, buckets) → dict`
Returns the current market regime so the signal scorer can penalize regime-inappropriate
signals.

What to put here:
- Trend: MA slope (20/50/200), ADX, higher highs/lows
- Volatility: ATR vs. 20-period average, VIX equivalent
- Key levels: recent highs/lows, volume profile POC, round numbers
- Macro context: from your sweep — DXY, 10Y yield, BTC dominance, VIX

```python
def detect_regime(now, buckets):
    return {
        "trend": "up" if price > SMA50 > SMA200 else ("down" if price < SMA50 else "neutral"),
        "volatility": "high" if atr > atr_avg * 1.3 else "normal",
        "key_levels": {"resistance": [...], "support": [...]},
        "macro_context": {"dxy": 100.5, "yield_10y": 4.96, "btc_dominance": 0.58}
    }
```

### 2. `get_watchlist(bucket, cfg) → list[str]`
Returns the assets to scan for each bucket.

What to put here:
- equities: the ETFs/stocks you trade (SPY, QQQ, IWM, sector ETFs, etc.)
- crypto: the crypto assets you trade (BTC, ETH, SOL, XRP, etc.)
- forex: the pairs you trade
- oil/metals: CL, GC, SI, PL, etc.
- indices/futures: ES, NQ, RTY, etc.

```python
def get_watchlist(bucket, cfg):
    watchlists = {
        "equities": ["SPY","QQQ","IWM","XLF","XLK","XLE"],
        "crypto": ["BTCUSDT","ETHUSDT","SOLUSDT","XRPUSDT","ZECUSDT"],
        "forex": ["EURUSD","GBPUSD","USDJPY","USDCHF"],
        "oil": ["CL=F","BZ=F"],
        "metals": ["GC=F","SI=F","PL=F"],
        "indices": ["ES=F","NQ=F","RTY=F"],
    }
    return watchlists.get(bucket, [])
```

### 3. `SignalEngine.detect_signals(bucket, assets, now) → list[Signal]`
The actual signal detection logic. This is where your trading edge lives.

What to put here:
- Fetch OHLC data for each asset (your data source)
- Run your signal logic (breakouts, pullbacks, momentum, mean reversion, etc.)
- Return Signal objects with entry, stop, TP, confirmed timeframes, volume confirmation

```python
def detect_signals(self, bucket, assets, now):
    signals = []
    for asset in assets:
        df = fetch_ohlc(asset, ["1H","4H","1D"])
        if is_breakout(df, tf="4H"):
            signals.append(Signal(
                asset=asset, bucket=bucket,
                signal_type="breakout", direction="long",
                entry=df["close"].iloc[-1],
                stop=df["close"].iloc[-1] * 0.98,
                tp=df["close"].iloc[-1] * 1.03,
                confirmed_timeframes=["4H","1D"],
                volume_confirmed=True,
                reason="4H breakout above resistance with volume"
            ))
    return signals
```

### 4. `position_size(sig, account_size, risk) → float`
Sizes each position based on signal risk + account risk budget.

What to put here:
- Fixed fractional: risk X% of account per trade
- Volatility-adjusted: wider stops = smaller size
- Kelly fraction (optional, advanced)

```python
def position_size(sig, account_size, risk):
    risk_pts = abs(sig.entry - sig.stop)
    if risk_pts == 0:
        return 0
    risk_amount = account_size * 0.01  # 1% risk per trade
    return risk_amount / risk_pts
```

### 5. `execute_trade(sig, size, fill_price, cfg)`
Place the order via your broker (Alpaca for equities/ETFs, MT5 for everything else).

What to put here:
- Map asset → broker (from `cfg["bots"]`)
- Send the order
- Handle rejections, partial fills, rejections
- Record the actual fill price (not the signal price)

```python
def execute_trade(sig, size, fill_price, cfg):
    bot_config = cfg["bots"][f"mt5_{sig.bucket}"]
    if bot_config["broker"] == "mt5":
        mt5_order(sig, size, fill_price)  # your MT5 function
    elif bot_config["broker"] == "alpaca":
        alpaca_order(sig, size, fill_price)  # your Alpaca function
```

---

## WHAT THE TEAM DOES NOT DO

- Don't re-scan — the system already did
- Don't re-score — the system already scored
- Don't second-guess the risk governor — it's the circuit breaker
- Don't override without a reason — if you skip a signal, note why in the brief

The team's job is **verification and decision**, not re-doing the work. The system does the
mechanical heavy lifting. The team applies judgment to the output.

---

## CONFIGURATION FILE — config_uber.json

```json
{
  "clock_tz": "America/New_York",
  "scan_interval_minutes": 30,
  "market_windows": {
    "FULL": {"weekday": [0,1,2,3,4], "start": "09:00", "end": "16:05"},
    "NO_EQUITIES": {"weekday": [0,1,2,3,6], "start": null, "end": null},
    "CRYPTO_ONLY": {"weekday": [4,5,6], "start": null, "end": null}
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
    "correlation_group_threshold": 0.7,
    "slippage_alert_pct": 0.05,
    "api_health_timeout_seconds": 10
  },
  "signal_scoring": {
    "multi_tf_bonus": 0.15,
    "volume_confirmation_bonus": 0.10,
    "regime_fit_bonus": 0.10,
    "recency_winrate_weight": 0.4,
    "time_of_day_weight": 0.05,
    "min_score_to_fire": 0.55
  },
  "journal": {
    "path": "trade_journal.jsonl",
    "rolling_stats_window_trades": 50
  },
  "analysis_brief_path": "analysis_brief.json"
}
```

Tune these to taste. The most important knobs:
- `max_daily_loss_pct` — your daily circuit breaker
- `max_concurrent_positions` — how many trades you run at once
- `max_exposure_per_signal_pct` — max risk per signal as % of account
- `min_score_to_fire` — raise to be more selective, lower to be more aggressive
- `recency_winrate_weight` — how much recent performance matters vs. long-run stats

---

## CORRELATION GROUPS — map these

The risk governor needs to know which assets are correlated so it doesn't fire
overlapping bets. Fill in `risk.correlation_groups`:

```python
risk.correlation_groups = {
    # Crypto bucket
    "BTCUSDT": "crypto_leader",
    "ETHUSDT": "crypto_secondary",
    "SOLUSDT": "crypto_high_beta",
    # Equities bucket
    "SPY": "us_equity_broad",
    "QQQ": "us_tech",
    "IWM": "us_small_cap",
    # Forex bucket
    "EURUSD": "eur_long",
    "GBPUSD": "gbp_long",
    "USDJPY": "jpy_short",
}
```

Rules:
- Assets in the same group are treated as one exposure for concurrency purposes
- If BTC long is open, a SOL long in the same group gets flagged as correlation overlap
- Adjust group labels to match your actual correlation structure

---

## RUN INSTRUCTIONS

```bash
# On each Windows machine running Hermes:
python uber_autotrader.py

# It runs as a foreground daemon. For production, run as:
# - Windows Task Scheduler: trigger at boot, repeat every 30 min
# - Or as a service with nssm / WinSW
# - Or as a persistent terminal session

# The system syncs to ET :00/:30 marks. It sleeps until the next mark.
# Logs go to stderr (redirect to file for production).

# Dry-run mode (P1): edit config_uber.json, set "dry_run": true
# The system scans, scores, gates, and generates the brief — but never fires.
# Use this to validate the full pipeline before going live.

# Verify the process is alive (P2):
# cat .heartbeats/uber_autotrader.heartbeat
# Should show: alive <timestamp> pid <pid> state <market_state>

# Prevent two instances running simultaneously (P2):
# The first instance writes .heartbeats/uber_autotrader.pid
# A second instance will still start (no locking yet) — TODO: add pidfile lock
```

---

## WHAT YOU GET

1. **`uber_autotrader.py`** — the full orchestrator. Clock-synced router,
   signal engine with auto-suspension (P0), risk governor with trail-stop (P1),
   trade journal with rolling stats, analysis brief generator, dry-run mode (P1),
   signal TTL (P1), score-based sizing (P1), heartbeat/pidfile (P2), main loop.

2. **`ANALYSIS_BRIEF_GUIDE.md`** — this doc. Tells the team what to read and how to decide.
   Includes P0/P1/P2 feature documentation.

3. **`config_uber.json`** — configuration. Tune risk parameters, scoring weights, watchlists,
   dry-run mode, signal TTL, auto-suspension thresholds, heartbeat dir.

The system is a skeleton with the structure complete. The five implementation hooks
(`detect_regime`, `get_watchlist`, `detect_signals`, `position_size`, `execute_trade`) are
where your edge lives. Fill those in and the system runs end-to-end.

---

## FINAL NOTE

The system's job is to make the team's job easier, not to replace judgment. It scans,
scores, gates, journals, and briefs. The team reads the brief, verifies the setups, and
decides. That division of labor is what makes it work — the system handles the repetitive
mechanical parts, the team handles the judgment calls that machines can't make.

The brief is designed to be scannable in under 60 seconds. If it takes longer, something's
wrong with the brief structure — flag it and we fix it.
