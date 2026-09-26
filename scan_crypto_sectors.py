#!/usr/bin/env python3
"""Cross-asset & crypto sector scan: BB mean-reversion + regime + RSI/MACD signals.

Reads zeus_brain.db for BTCUSDT/ETHUSDT/SPY/EURUSD/CL=F/GC=F candles,
applies scan_signals + backtest_bb_mean_revert, and prints a structured
watchlist with correlated / uncorrelated groupings.

Output goes to stdout + cross_asset_scan_results.txt
"""
import sys, os, sqlite3, json, datetime

sys.path.insert(0, os.path.dirname(__file__))
import zeus_ta, importlib
importlib.reload(zeus_ta)
from zeus_ta import (
    feature_vector, scan_signals, backtest_bb_mean_revert,
    bollinger_bands, sma, atr, rsi, macd, obv, psar
)

DB = os.path.join(os.path.dirname(__file__), 'zeus_brain.db')

# ── helpers ──────────────────────────────────────────────────────────────────
def fmt_ts(ts):
    return datetime.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

def load_candles(conn, symbol, tf, limit=500):
    rows = conn.execute(
        "SELECT ts,open,high,low,close,volume FROM candles "
        "WHERE symbol=? AND tf=? ORDER BY ts DESC LIMIT ?",
        (symbol, tf, limit)
    ).fetchall()
    rows.reverse()  # DESC gives newest-first; reverse to chronological order
    return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in rows]

def ta_summary(candles, label):
    """Return a dict of key TA readings for the LATEST candle."""
    if len(candles) < 34:
        return {"n": len(candles), "status": "too_short"}
    fv = feature_vector(candles)
    bb = fv.get("bollinger")
    close = candles[-1][4]
    last = {
        "label": label,
        "price": round(close, 2),
        "n_candles": len(candles),
        "last_ts": fmt_ts(candles[-1][0]),
        "regime": fv.get("regime", "unknown"),
        "sma_30": round(fv.get("sma_30"), 2) if fv.get("sma_30") else None,
        "sma_200": round(fv.get("sma_200"), 2) if fv.get("sma_200") else None,
        "bb_lower": round(bb["lower"], 2) if bb else None,
        "bb_mid": round(bb["mid"], 2) if bb else None,
        "bb_upper": round(bb["upper"], 2) if bb else None,
        "bb_pct_b": round(bb.get("%B", 0.5), 3) if bb else None,
        "rsi_14": round(fv.get("rsi_14"), 2) if fv.get("rsi_14") else None,
        "atr_14": round(fv.get("atr_14"), 2) if fv.get("atr_14") else None,
        "atr_pct": round(fv.get("atr_14", 0) / close * 100, 2) if close else None,
        "macd_hist": round(fv.get("macd_histogram", 0), 4),
        "psar": round(fv.get("psar", 0), 2),
        "obv": round(fv.get("obv", 0), 0),
    }
    return last

def bb_scan(candles, label):
    """Run scan_signals on the full series and collect BB-related signals."""
    if len(candles) < 34:
        return []
    fv = feature_vector(candles)
    sigs = scan_signals({label: fv}, min_score=0.5)
    bb_sigs = [s for s in sigs if "bb_mean_revert" in s.get("signal_type", "")]
    return bb_sigs

def bb_backtest(candles, label):
    """Run backtest_bb_mean_revert over the series and return stats."""
    if len(candles) < 50:
        return {"trades": 0, "status": "too_short"}
    bt = backtest_bb_mean_revert(
        candles, bb_period=20, bb_std=2.0, ma_period=30,
        atr_period=14, atr_stop_mult=1.5, atr_tp_mult=3.0,
        bb_touch_band=0.02
    )
    bt["label"] = label
    bt["break_even_wr"] = 0.333  # fixed for 1:2 RR
    return bt

# ── sector group lookup (per-symbol, not just DB class) ──────────────────────
SECTOR_PATTERNS = {
    "L1_L2":     ["BTC","ETH","SOL","AVAX","NEAR","DOT","ATOM","LINK","INJ","TRX","APT","ARB","OP","MATIC","GRT","RUNE","HBAR","ICP","ALGO","KAVA"],
    "DeFi":      ["UNI","AAVE","COMP","MKR","CRV","SUSHI","GMX","BAL","PENDLE","STG","LDO","YFI","SNX","REN","BAT","1INCH","ENA","DEI","OHM","KLAY"],
    "Meme":      ["DOGE","SHIB","PEPE","WIF","BONK","FLOKI","MYRO","BRETT","POPCAT","MOG","WEN","TREMP","ADMIN"],
    "AI":        ["RENDER","FET","TENSOR","HAI","RNDR","AI","ORCL","GOOGL","ROSE","AGIX","OCEAN"],
    "Gaming_GameFi": ["AXS","GALA","GOAL","IMX","MANA","ILV","BEAM","RIVER","PIXELF","VRDRWD","ULT","CHR","ENJ"],
    "RWA":       ["MKR","ONDO","STRK","TLOS","BANXA","REAL","PQ","PROP","READY","PORT"],
    "Privacy":   ["ZEC","XMR","DASH","OM","CAC","PRIVACY","FIR","ZNT"],
    "Exchange_CEX": ["BNB","OKB","KCS","FTM","LEO","FTT","KIN","GT"],
    "Social_Farcaster": ["DEGEN","FC","YOLO","NEIRO","ZRO","MUMBAI","VINE","TNS"],
    "Infra_Storage_Compute": ["FIL","AR","RPL","STORJ","TFLO","SC","DENT","IOTX","AGI","NMR","CVC","QNT","MVI","BAND","UMA"],
}
GROUP_NAMES = {
    "L1_L2":     "L1/L2",
    "DeFi":      "DeFi",
    "Meme":      "Meme",
    "AI":        "AI",
    "Gaming_GameFi": "Gaming/GameFi",
    "RWA":       "RWA",
    "Privacy":   "Privacy",
    "Exchange_CEX": "Exchange/CEX",
    "Social_Farcaster": "Social/Farcaster",
    "Infra_Storage_Compute": "Infra/Storage/Compute",
}

def sector_group(symbol, class_):
    """Map symbol+class to a display sector group."""
    base = symbol.replace("USDT","").replace("USD","").replace("=X","")
    # class-based fallback (for non-crypto symbols like SPY, CL=F)
    CLASS_MAP = {
        "equity": "US Equities",
        "forex": "Forex",
        "future": "Commodities",
        "crypto": "Crypto",
    }
    g = CLASS_MAP.get(class_)
    if g:
        return g
    # try pattern-based
    for sector, symbols in SECTOR_PATTERNS.items():
        if base in symbols:
            return GROUP_NAMES.get(sector, sector)
    return class_

conn = sqlite3.connect(DB)

# Pull every symbol+tf from candle_sources + candles
symbols_rows = conn.execute("""
    SELECT DISTINCT cs.symbol, cs.class, c2.tf, COUNT(c2.ts)
    FROM candle_sources cs
    LEFT JOIN candles c2 ON cs.symbol=c2.symbol AND c2.ts IS NOT NULL
    GROUP BY cs.symbol, cs.class, c2.tf
    ORDER BY cs.class, cs.symbol, c2.tf
""").fetchall()

SCAN_SPEC = []
for sym, class_, tf, n in symbols_rows:
    if n < 50:
        continue  # skip symbols with too few candles
    group = sector_group(sym, class_)
    label = f"{sym} {tf}"
    SCAN_SPEC.append((sym, tf, label, group))

print("╔══════════════════════════════════════════════════════════════════╗")
print("║  CROSS-ASSET & CRYPTO SECTOR SCAN                             ║")
print(f"║  Run: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}  |  zeus_brain.db candle store  ║")
print(f"║  Symbols to scan: {len(SCAN_SPEC)}  ║")
print("╚══════════════════════════════════════════════════════════════════╝\n")

results = {}  # label -> summary

for sym, tf, label, group in SCAN_SPEC:
    candles = load_candles(conn, sym, tf, limit=500)
    if not candles:
        print(f"[SKIP] {label:25s} [{group}] — no candles")
        continue

    summary = ta_summary(candles, label)
    bb_signals = bb_scan(candles, label)
    bt = bb_backtest(candles, label)

    summary["group"] = group
    summary["bb_signals"] = bb_signals
    summary["bb_backtest"] = bt
    results[label] = summary

    # ── print per-asset block ──
    print(f"─── {label} [{group}]  ({len(candles)} candles, last {summary['last_ts']}) ───")
    print(f"  Price:      {summary['price']}")
    print(f"  Regime:     {summary['regime']}")
    print(f"  SMA30:      {summary['sma_30']}   SMA200: {summary['sma_200']}")
    if summary["bb_lower"] is not None and summary["bb_lower"] != 0:
        bb_l = summary['bb_lower']
        print(f"  BB:         lower={bb_l}  mid={summary['bb_mid']}  "
              f"upper={summary['bb_upper']}  %B={summary['bb_pct_b']}  "
              f"(vs lower {(summary['price']/bb_l-1)*100:+.2f}%)")
    elif summary["bb_lower"] is not None:
        print(f"  BB:         lower={summary['bb_lower']}  mid={summary['bb_mid']}  "
              f"upper={summary['bb_upper']}  %B={summary['bb_pct_b']}  "
              f"(vs lower n/a — near-zero price)")
    print(f"  RSI(14):    {summary['rsi_14']}   ATR(14): {summary['atr_14']} "
          f"({summary['atr_pct']}%)")
    print(f"  MACD hist:  {summary['macd_hist']}   PSAR: {summary['psar']}   "
          f"OBV: {summary['obv']}")

    if bb_signals:
        print(f"  ⚡ BB SIGNALS ({len(bb_signals)}):")
        for s in bb_signals:
            print(f"     {s['signal_type']:24s} {s['direction']:5s}  "
                  f"entry={s['entry']}  stop={s['stop']}  tp={s['tp']}  "
                  f"score={s['score']}  reasons={s['reasons']}")
    else:
        print(f"  ⚡ BB signals: none on latest window")

    if bt.get("trades", 0) > 0:
        print(f"  📊 BB BACKTEST (over full series): trades={bt['trades']}  "
              f"wins={bt['wins']}  losses={bt['losses']}  WR={bt['wr']*100:.1f}%  "
              f"RR={bt['rr_ratio']}  expectancy={bt['expectancy_r']} ATR/trade  "
              f"break-even WR={bt.get('break_even_wr',0.333)*100:.1f}%")
        if bt['wr'] >= 0.333:
            print(f"     → ABOVE break-even  ✓")
        else:
            print(f"     → BELOW break-even  (this window is below average)")
    else:
        print(f"  📊 BB BACKTEST: insufficient data for backtest")
    print()

conn.close()

# ── correlated / uncorrelated grouping ──────────────────────────────────────
print("╔══════════════════════════════════════════════════════════════════╗")
print("║  WATCHLIST — CORRELATED vs UNCORRELATED SETUPS                ║")
print("╚══════════════════════════════════════════════════════════════════╝\n")

# Build setup verdicts
setups = []
for label, s in results.items():
    verdict = "none"
    direction = None
    reasons = []

    rsi = s.get("rsi_14")
    regime = s.get("regime", "")
    bb_l = s.get("bb_lower")
    bb_u = s.get("bb_upper")
    bb_m = s.get("bb_mid")
    price = s.get("price")
    bb_pct = s.get("bb_pct_b")
    macd_h = s.get("macd_hist", 0)
    atr_pct = s.get("atr_pct")
    bt = s.get("bb_backtest", {})

    # BB mean-revert LONG
    if bb_l and price and price >= bb_l and price <= bb_l * 1.02 and s.get("sma_30") and price > s["sma_30"]:
        verdict = "bb_mean_revert_long"
        direction = "LONG"
        reasons.append(f"price {price} within 2% of BB lower {bb_l} + above SMA30 {s['sma_30']}")
        if rsi and rsi < 40:
            reasons.append(f"RSI {rsi} oversold confirmation")

    # BB mean-revert SHORT
    if bb_u and price and price <= bb_u and price >= bb_u * 0.98 and s.get("sma_30") and price < s["sma_30"]:
        if verdict == "none":
            verdict = "bb_mean_revert_short"
            direction = "SHORT"
        reasons.append(f"price {price} within 2% of BB upper {bb_u} + below SMA30 {s['sma_30']}")

    # RSI oversold/overbought (secondary)
    if rsi:
        if rsi < 30 and regime in ("uptrend", "range"):
            if verdict == "none":
                verdict = "rsi_oversold_long"
                direction = "LONG"
            reasons.append(f"RSI {rsi} oversold in {regime}")
        elif rsi > 70 and regime in ("downtrend", "range"):
            if verdict == "none":
                verdict = "rsi_overbought_short"
                direction = "SHORT"
            reasons.append(f"RSI {rsi} overbought in {regime}")

    # MACD crossover
    if macd_h is not None:
        if macd_h > 0.001 and regime == "uptrend":
            if verdict == "none":
                verdict = "macd_bullish"
                direction = "LONG"
            reasons.append(f"MACD hist {macd_h} positive in uptrend")
        elif macd_h < -0.001 and regime == "downtrend":
            if verdict == "none":
                verdict = "macd_bearish"
                direction = "SHORT"
            reasons.append(f"MACD hist {macd_h} negative in downtrend")

    # Backtest edge
    if bt.get("trades", 0) >= 5 and bt.get("wr", 0) >= 0.333:
        reasons.append(f"backtest: {bt['trades']} trades, WR {bt['wr']*100:.1f}% > 33.3% break-even ✓")
    elif bt.get("trades", 0) >= 5:
        reasons.append(f"backtest: {bt['trades']} trades, WR {bt['wr']*100:.1f}% < 33.3% break-even (this window below avg)")

    if verdict != "none":
        setups.append({
            "label": label,
            "group": s.get("group", ""),
            "verdict": verdict,
            "direction": direction,
            "price": price,
            "sma30": s.get("sma_30"),
            "rsi": rsi,
            "bb_pct_b": bb_pct,
            "regime": regime,
            "reasons": reasons,
        })

if not setups:
    print("  No setups found on latest windows.")
else:
    # Group into correlated / uncorrelated buckets
    correlated_groups = {"US Equities", "Forex", "Commodities", "Energy", "Precious Metals"}
    uncorrelated_groups = {"Crypto", "L1/L2", "DeFi", "Meme", "AI", "Gaming/GameFi",
                           "RWA", "Privacy", "Exchange/CEX", "Social/Farcaster",
                           "Infra/Storage/Compute"}
    correlated = [x for x in setups if x["group"] in correlated_groups]
    uncorrelated = [x for x in setups if x["group"] in uncorrelated_groups]

    print("  ── CORRELATED CLUSTER (US equities / energy / forex — driven by same macro) ──")
    if correlated:
        for x in correlated:
            print(f"    [{x['direction']:5s}] {x['label']:18s} {x['verdict']:24s}  "
                  f"price={x['price']}  RSI={x['rsi']}  %B={x['bb_pct_b']}  regime={x['regime']}")
            for r in x["reasons"]:
                print(f"         → {r}")
    else:
        print("    (no setups in this cluster right now)")

    print()
    print("  ── UNCORRELATED CLUSTER (crypto / metals — independent drivers) ──")
    if uncorrelated:
        for x in uncorrelated:
            print(f"    [{x['direction']:5s}] {x['label']:18s} {x['verdict']:24s}  "
                  f"price={x['price']}  RSI={x['rsi']}  %B={x['bb_pct_b']}  regime={x['regime']}")
            for r in x["reasons"]:
                print(f"         → {r}")
    else:
        print("    (no setups in this cluster right now)")

print("\n  ── ALL SETUPS (flat list) ──")
for x in setups:
    bb_l_str = f"{x.get('sma30')}" if x.get('sma30') else "n/a"
    print(f"  [{x['direction']:5s}] {x['label']:18s} {x['verdict']:24s}  "
          f"RSI={x.get('rsi')}  %B={x.get('bb_pct_b')}  regime={x['regime']}")

print(f"\n  Total setups: {len(setups)}")

# ── save to file ─────────────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(__file__), 'cross_asset_scan_results.txt')
with open(OUT, 'w') as f:
    f.write(f"Cross-Asset & Crypto Sector Scan — {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
    f.write("=" * 70 + "\n\n")
    for label, s in results.items():
        f.write(f"─── {label} [{s.get('group','')}] ───\n")
        for k, v in s.items():
            if k in ("bb_signals", "bb_backtest"):
                continue
            f.write(f"  {k}: {v}\n")
        f.write("\n")

    f.write("WATCHLIST\n")
    f.write("-" * 40 + "\n")
    for x in setups:
        f.write(f"  [{x['direction']}] {x['label']} {x['verdict']}  "
                f"price={x['price']} RSI={x.get('rsi')} %B={x.get('bb_pct_b')} regime={x['regime']}\n")
        for r in x["reasons"]:
            f.write(f"    - {r}\n")

print(f"\n✓ Results saved to: {OUT}")
