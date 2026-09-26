# Uber Auto Trader

**Production-ready auto-trader orchestrator for multi-asset, multi-session trading.**

Runs as a 24/7 daemon. Every 30 minutes (ET clock-synced) it:
1. Reads the clock → determines which asset buckets are open
2. Dispatches scans to the right bots for open buckets
3. Scores every signal (quality, confidence, regime-fit, recent win rate)
4. Gates trades through a risk governor (daily loss, concurrency, correlation, R:R, slippage)
5. Fires ranked signals up to a concurrency cap, sized by signal score
6. Records every trade to a JSONL journal → rolling stats → auto-suspends declining signal types
7. Generates a structured analysis brief the team reads to decide trades
8. Writes a heartbeat every cycle for ops monitoring

## Architecture

```
uber_autotrader.py  —  master orchestrator (single file, ~760 lines)
├── Market Hours Router   —  determines FULL / NO_EQUITIES / CRYPTO_ONLY state
├── Signal Engine         —  detects + scores signals; auto-suspends declining types (P0)
├── Risk Governor         —  gates trades; trail-stop at 1R (P1)
├── Trade Journal         —  JSONL recording + rolling stats per signal type
├── Analysis Brief        —  structured JSON the team reads to decide
├── Position Sizer        —  score-based sizing (P1)
├── Signal TTL            —  discards stale signals (P1)
├── Dry-Run Mode          —  scan+score+brief WITHOUT firing (P1)
├── Heartbeat/PIDfile     —  ops monitoring, duplicate prevention (P2)
└── Main Loop             —  ET clock-synced 30-min cycle
```

## Broker Integration

Broker-agnostic at the core. Five implementation hooks to fill in:

1. **`detect_regime(now, buckets) → dict`** — trend, volatility, key levels, macro context
2. **`get_watchlist(bucket, cfg) → list[str]`** — assets to scan per bucket
3. **`SignalEngine.detect_signals(bucket, assets, now) → list[Signal]`** — your trading edge
4. **`position_size(sig, account_size, risk, score) → float`** — size each position
5. **`execute_trade(sig, size, fill_price, cfg)`** — place the order via your broker

Supported brokers (stub — implement the actual API calls):
- **Alpaca** — equities and ETFs (bucket: equities, etfs)
- **MT5 / Capital.com** — forex, crypto, indices, futures, oil, metals

## Market Hours

| Window | Equities/ETFs | Crypto | Indices/Forex/Oil/Metals |
|--------|---------------|--------|--------------------------|
| Mon-Fri 09:00-16:05 ET | ✅ | ✅ | ✅ |
| Fri 16:05 - Sun 17:00 ET | ❌ | ✅ | ❌ |
| Sun 17:00 - Mon 09:00 ET | ❌ | ✅ | ✅ |

## Key Features

### P0 — Signal Auto-Suspension
If a signal type's last 20 trades have win rate below 40%, that type is automatically
suspended (score forced to 0). Recovers automatically when rolling win rate exceeds 55%.

### P1 — Dry-Run Mode
Set `"dry_run": true` in config. The system scans, scores, gates, and generates the full
brief — but never fires. Every would-be fire shows `[DRY_RUN] would fire`. Use this to
validate the pipeline before going live.

### P1 — Signal TTL
Signals older than 4 hours are discarded before the risk gate. Prevents firing stale setups.

### P1 — Score-Based Sizing
A 0.80 signal gets more capital than a 0.58 signal. Base 1% at score 0.55, scaling linearly
to max_exposure (1.5%) at score 0.80+. Higher conviction = more capital, automatically.

### P1 — Trail-Stop
When a long position reaches 1R profit, the stop moves to breakeven. Logs the event; push to
broker via TODO in `risk.trail_stop()`.

### P2 — Heartbeat + PIDfile
Every cycle writes `.heartbeats/uber_autotrader.heartbeat` with timestamp, PID, and market
state. Ops can scrape this to verify the process is alive. PID file prevents two instances.

## Configuration

All tunable parameters in `config_uber.json`:
- Risk: daily loss limit, concurrency cap, per-signal exposure, min R:R, correlation groups
- Scoring: multi-TF bonus, volume bonus, regime fit, recency WR weight, time-of-day, min score
- Auto-suspension: lookback (20 trades), suspend threshold (WR < 40%), resume threshold (WR > 55%)
- Signal TTL: 4 hours default
- Dry-run: false by default
- Account size: 10000.0 default
- Heartbeat: `.heartbeats/` directory

## Analysis Brief

The system generates `analysis_brief.json` every cycle. The team reads this to decide trades.
See `ANALYSIS_BRIEF_GUIDE.md` for the full structure and team decision framework.

## Files

- `uber_autotrader.py` — master orchestrator
- `config_uber.json` — configuration
- `ANALYSIS_BRIEF_GUIDE.md` — team documentation
- `trade_journal.jsonl` — auto-generated trade log (append-only)
- `analysis_brief.json` — auto-generated team brief (overwrite each cycle)
- `.heartbeats/uber_autotrader.heartbeat` — auto-generated heartbeat
- `.heartbeats/uber_autotrader.pid` — auto-generated PID file

## Run

```bash
python uber_autotrader.py
```

For production on Windows:
- Windows Task Scheduler (trigger at boot, repeat every 30 min)
- Or as a service with nssm / WinSW
- Or as a persistent terminal session

## License

Internal use. Customize for your brokerage setup and trading edge.
