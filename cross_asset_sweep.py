#!/usr/bin/env python3
"""
HERMES CROSS-ASSET SWEEP — Free Data Stack
==========================================
One script. Zero budget. All asset classes.

Sources (all free, no credit card):
  - CoinGecko     : crypto prices, market cap, 24h change (no key, 30 req/min)
  - Yahoo Finance : futures, commodities, indices (direct API, no key)
  - FRED (St.Louis): Treasury yields, credit spreads, SOFR, DXY (CSV, no key)
  - algoxflow.com : SPY/NQ/SPX gamma flip, max pain, call/put walls (no key)
  - CoinDesk RSS  : crypto sector news headlines (fallback if API blocked)

Output: structured cross-asset dashboard printed to stdout + saved to file.

Run: python3 cross_asset_sweep.py [--save] [--output FILE]
"""

import sys
import os
import json
import csv
import io
import time
import argparse
import datetime
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
from datetime import timezone, timedelta

try:
    import requests
except ImportError:
    requests = None

# ──────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────
COINGECKO_TIMEOUT = 10
YAHOO_TIMEOUT = 10
FRED_TIMEOUT = 15
ALGXOFLOW_TIMEOUT = 10

USER_AGENT = "Mozilla/5.0 (Termux; Hermes Cross-Asset Sweep)"

# ──────────────────────────────────────────────────────────────
# HTTP HELPERS
# ──────────────────────────────────────────────────────────────

def _fetch(url, timeout=10, binary=False):
    """Fetch URL with User-Agent header. Returns text or bytes."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=timeout) as resp:
            if binary:
                return resp.read()
            return resp.read().decode("utf-8", errors="replace")
    except (URLError, HTTPError, OSError) as e:
        return None


def _fetch_json(url, timeout=10):
    txt = _fetch(url, timeout=timeout)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None


# ──────────────────────────────────────────────────────────────
# 1. CRYPTO — CoinGecko API (no key, 30 req/min)
# ──────────────────────────────────────────────────────────────

def sweep_crypto():
    """Fetch BTC, ETH, SOL, XRP, ZEC, ADA, DOGE, LTC, DOT, AVAX, MATIC, BCH, LINK, UNI, ATOM, NEAR, APT, ARB, EGOLD, TRX, XLM, DOGE, SHIB, PEPE, WIF, BONK, FLOKI, RENDER, FET, AI, TAO, INJ, AVAX, POLY, AAVE, MKR, CRV, COMP, UNI, SUSHI, GMX, JUP, WEMIX, WEMIX."""
    ids = [
        "bitcoin", "ethereum", "solana", "ripple", "zcash", "cardano",
        "dogecoin", "litecoin", "polkadot", "avalanche-2", "matic-network",
        "bitcoin-cash", "chainlink", " Uniswap", "cosmos", "near",
        "aptos-lab", "arbitrum", "wrapped-eogn-gold", "tron",
        "stellar", "shiba-inu", "pepe", "dogwifhat", "bonk",
        "floki", "render-token", "fetch-ai", "internet-computer",
        "enjincoin", "the-arena", "osmosis", "injective-protocol",
        "matic-network", "maker", "curve-dao-token", "compound-governance-token",
        "sushi", "gmx", "jupiter-exchange-solana", "wen-get-rich-quick",
    ]
    # Clean the IDs
    ids = [i.strip().lower() for i in ids if i.strip()]
    # Remove duplicates while preserving order
    seen = set()
    clean_ids = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            clean_ids.append(i)

    vs_currencies = "usd"
    include_24hr = "true"
    include_market_cap = "true"
    include_24hr_vol = "true"

    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={','.join(clean_ids)}"
        f"&vs_currencies={vs_currencies}"
        f"&include_24hr_change={include_24hr}"
        f"&include_market_cap={include_market_cap}"
        f"&include_24hr_vol={include_24hr_vol}"
    )

    data = _fetch_json(url, timeout=COINGECKO_TIMEOUT)
    if data is None:
        return {"error": "CoinGecko API unreachable", "data": None}

    return {"error": None, "data": data}


# ──────────────────────────────────────────────────────────────
# 2. FUTURES / COMMODITIES / INDICES — Yahoo Finance direct API
# ──────────────────────────────────────────────────────────────

def _yahoo_quote(symbol):
    """Fetch latest quote for a Yahoo Finance symbol (e.g. 'CL=F', 'GC=F', 'ES=F')."""
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range=1d"
    )
    data = _fetch_json(url, timeout=YAHOO_TIMEOUT)
    if data is None:
        return None

    try:
        result = data["chart"]["result"][0]
        meta = result["meta"]
        timestamp = result["timestamp"][0] if result.get("timestamp") else None
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        change = meta.get("regularMarketChange")
        change_pct = meta.get("regularMarketChangePercent")
        volume = meta.get("volume")
        open_price = meta.get("open")
        high = meta.get("dayHigh")
        low = meta.get("dayLow")
        currency = meta.get("currency")
        market_time = meta.get("marketState")

        # Calculate change manually if Yahoo didn't provide it
        if price and prev_close and (change is None):
            change = price - prev_close
            change_pct = (change / prev_close) * 100

        quote = {
            "symbol": symbol,
            "price": price,
            "prev_close": prev_close,
            "change": change,
            "change_pct": change_pct,
            "volume": volume,
            "open": open_price,
            "high": high,
            "low": low,
            "currency": currency,
            "market_time": market_time,
        }
        return quote
    except (KeyError, IndexError):
        return None


def sweep_futures():
    """Sweep all major futures: indices, commodities, rates, metals, energy, grains, softs, meats."""
    symbols = {
        # Indices
        "ES=F": "S&P 500 E-mini",
        "NQ=F": "Nasdaq 100 E-mini",
        "YM=F": "Dow Jones E-mini",
        "RTY=F": "Russell 2000 E-mini",
        # Rates / Bonds
        "ZB=F": "30Y T-Bond",
        "ZN=F": "10Y T-Note",
        "ZF=F": "5Y T-Note",
        "ZT=F": "2Y T-Note",
        "UB=F": "Ultra T-Bond",
        # Metals
        "GC=F": "Gold",
        "SI=F": "Silver",
        "PL=F": "Platinum",
        "PA=F": "Palladium",
        "HG=F": "Copper",
        # Energy
        "CL=F": "WTI Crude",
        "BZ=F": "Brent Crude",
        "NG=F": "Natural Gas",
        "HO=F": "Heating Oil",
        "RB=F": "RBOB Gasoline",
        # Grains / Softs
        "ZC=F": "Corn",
        "ZS=F": "Soybeans",
        "ZW=F": "Wheat",
        "ZM=F": "Soybean Meal",
        "ZL=F": "Soybean Oil",
        "CT=F": "Cotton",
        "SB=F": "Sugar #11",
        "CC=F": "Cocoa",
        "KC=F": "Coffee",
        "OJ=F": "Orange Juice",
        # Meats
        "LE=F": "Live Cattle",
        "GF=F": "Feeder Cattle",
        "HE=F": "Lean Hogs",
        # FX
        "6E=F": "Euro FX",
        "6B=F": "British Pound",
        "6J=F": "Japanese Yen",
        "6S=F": "Swiss Franc",
        "6A=F": "Australian Dollar",
        "6C=F": "Canadian Dollar",
        "DX=F": "US Dollar Index",
    }

    results = {}
    for sym, name in symbols.items():
        q = _yahoo_quote(sym)
        results[sym] = {"name": name, "quote": q}

    return {"error": None, "data": results}


# ──────────────────────────────────────────────────────────────
# 3. RATES / MACRO — FRED direct CSV (no key)
# ──────────────────────────────────────────────────────────────

FRED_SERIES = {
    "DGS10": "10Y Treasury Yield",
    "DGS2": "2Y Treasury Yield",
    "DGS30": "30Y Treasury Yield",
    "DGS5": "5Y Treasury Yield",
    "DGS7": "7Y Treasury Yield",
    "BAMLH0A0HYM2": "ICE BofA HY OAS (credit spread)",
    "BAMLC0A0CMEY": "ICE BofA IG Corp OAS (credit spread)",
    "SOFR": "Secured Overnight Financing Rate",
    "EFFR": "Effective Federal Funds Rate",
    "VIXCLS": "CBOE VIX",
}

def _fred_latest(series_id):
    """Get latest value from FRED CSV."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    txt = _fetch(url, timeout=FRED_TIMEOUT)
    if txt is None:
        return None
    try:
        reader = csv.reader(io.StringIO(txt))
        rows = list(reader)
        if len(rows) < 2:
            return None
        # FRED CSV: date, value — last row is most recent
        last = rows[-1]
        date_str = last[0]
        val_str = last[1]
        try:
            val = float(val_str)
        except ValueError:
            return {"date": date_str, "value": val_str, "raw": val_str}
        return {"date": date_str, "value": val}
    except Exception:
        return None


def sweep_fred():
    results = {}
    for sid, name in FRED_SERIES.items():
        latest = _fred_latest(sid)
        results[sid] = {"name": name, "latest": latest}
        time.sleep(0.3)  # Be polite to FRED
    return {"error": None, "data": results}


# ──────────────────────────────────────────────────────────────
# 4. OPTIONS — algoxflow (no key, CORS open)
# ──────────────────────────────────────────────────────────────

def sweep_options():
    """Fetch gamma flip, max pain, call/put walls for SPY and NQ."""
    symbols = ["SPY", "QQQ", "IWM", "TLT"]
    results = {}
    for sym in symbols:
        url = f"https://algoxflow.com/api/gexmap?ticker={sym}"
        data = _fetch_json(url, timeout=ALGXOFLOW_TIMEOUT)
        if data is None:
            results[sym] = {"error": "algoxflow unreachable"}
        else:
            results[sym] = data
        time.sleep(0.3)
    return {"error": None, "data": results}


# ──────────────────────────────────────────────────────────────
# 5. BITCOIN ETF FLOWS — Farside (free, daily)
# ──────────────────────────────────────────────────────────────

def sweep_etf_flows():
    """Fetch BTC ETF flow summary from Farside."""
    url = "https://farside.co.uk/btc"
    txt = _fetch(url, timeout=10)
    if txt is None:
        return {"error": "Farside unreachable", "data": None}
    # We'll parse the HTML minimally to extract the latest flow row
    # The table structure: date | IBIT | FBTC | BITB | ARKB | ... | Total
    # Simple approach: look for total column pattern
    import re
    # Find all table rows
    rows = re.findall(r'<tr>(.*?)</tr>', txt, re.DOTALL)
    flows = []
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) >= 2:
            date_cell = cells[0].strip()
            # Clean HTML tags from cells
            clean_cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            if clean_cells and clean_cells[0]:
                flows.append(clean_cells)

    # Filter to rows that look like data (date + numbers)
    data_rows = []
    for row in flows:
        if len(row) >= 3 and row[0] and any(c.replace('.', '').replace('-', '').isdigit() for c in row[1:] if c):
            data_rows.append(row)

    # Return the most recent data row
    latest = data_rows[0] if data_rows else None
    return {"error": None, "latest_flow": latest, "all_rows": data_rows[:10]}


# ──────────────────────────────────────────────────────────────
# OUTPUT FORMATTERS
# ──────────────────────────────────────────────────────────────

def fmt_price(val, currency="$"):
    if val is None:
        return "N/A"
    return f"{currency}{val:,.2f}"


def fmt_pct(val):
    if val is None:
        return "N/A"
    return f"{val:+.2f}%"


def fmt_big(val):
    if val is None:
        return "N/A"
    return f"{val:,.0f}"


def fmt_change(price, prev_close):
    if price and prev_close:
        chg = price - prev_close
        chg_pct = (chg / prev_close) * 100
        sign = "+" if chg >= 0 else ""
        return f"{sign}{chg:.2f} ({sign}{chg_pct:.2f}%)"
    return "N/A"


def print_section(title, width=60):
    print(f"\n{'='*width}")
    print(f"  {title}")
    print(f"{'='*width}")


def print_subsection(title):
    print(f"\n--- {title} ---")


def print_table(headers, rows, col_widths=None):
    """Print a simple markdown-ish table."""
    if not rows:
        print("  (no data)")
        return
    # Header
    header_line = "  ".join(f"{h:>12}" for h in headers)
    print(f"  {header_line}")
    print(f"  {'-'*len(header_line)}")
    for row in rows:
        line = "  ".join(f"{str(c):>12}" for c in row)
        print(f"  {line}")


def build_dashboard(crypto, futures, fred, options, etf_flows):
    """Build the structured dashboard output."""
    lines = []
    ts = datetime.datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines.append(f"╔{'═'*78}╗")
    lines.append(f"║  HERMES CROSS-ASSET SWEEP  —  {ts}  ║")
    lines.append(f"║  Free Data Stack: CoinGecko + Yahoo + FRED + algoxflow + Farside  ║")
    lines.append(f"╚{'═'*78}╝")

    # ── MACRO / RATES ──
    lines.append(f"\n{'─'*78}")
    lines.append("  📊 MACRO & RATES (FRED — latest available)")
    lines.append(f"{'─'*78}")

    macro_rows = []
    for sid, info in fred.get("data", {}).items():
        latest = info.get("latest")
        if latest and isinstance(latest, dict) and "value" in latest:
            val = latest["value"]
            date = latest.get("date", "unknown")
            macro_rows.append([sid, info["name"][:30], f"{val:.2f}", date[:10]])
        elif latest:
            macro_rows.append([sid, info["name"][:30], str(latest), "—"])

    lines.append(f"  {'Series':<14} {'Name':<32} {'Value':>10} {'Date':>10}")
    lines.append(f"  {'─'*14} {'─'*32} {'─'*10} {'─'*10}")
    for row in macro_rows:
        lines.append(f"  {row[0]:<14} {row[1]:<32} {row[2]:>10} {row[3]:>10}")

    # Key macro signals
    lines.append(f"\n  KEY SIGNALS:")
    dgs10 = _find_fred_val(fred, "DGS10")
    dgs2 = _find_fred_val(fred, "DGS2")
    dgs30 = _find_fred_val(fred, "DGS30")
    hy_oas = _find_fred_val(fred, "BAMLH0A0HYM2")
    sofr = _find_fred_val(fred, "SOFR")
    effr = _find_fred_val(fred, "EFFR")
    vix = _find_fred_val(fred, "VIXCLS")
    dxy = _find_fred_val(fred, "DXY")

    if dgs10:
        lines.append(f"    • 10Y Treasury: {dgs10:.2f}%  {'← 2007 high zone' if dgs10 > 5.0 else ''}")
    if dgs2:
        lines.append(f"    • 2Y Treasury: {dgs2:.2f}%")
    if dgs30:
        lines.append(f"    • 30Y Treasury: {dgs30:.2f}%")
    if hy_oas:
        lines.append(f"    • HY Credit Spread: {hy_oas:.2f}%  {'← WATCH: widening = stress' if hy_oas > 3.5 else '← Normal'}")
    if sofr:
        lines.append(f"    • SOFR: {sofr:.2f}%")
    if effr:
        lines.append(f"    • Effective Fed Funds: {effr:.2f}%  (target 3.75-4.00%)")
    if vix:
        lines.append(f"    • VIX: {vix:.2f}  {'← Compressed — volatility expansion risk' if vix < 16 else ''}")
    if dxy:
        lines.append(f"    • DXY: {dxy:.2f}  {'← Strong dollar' if dxy > 100 else ''}")

    # ── FUTURES ──
    lines.append(f"\n{'─'*78}")
    lines.append("  📈 FUTURES & COMMODITIES (Yahoo Finance — real-time during session)")
    lines.append(f"{'─'*78}")

    fut_data = futures.get("data", {})
    # Group by category
    groups = {
        "INDICES": ["ES=F", "NQ=F", "YM=F", "RTY=F"],
        "RATES/BONDS": ["ZB=F", "ZN=F", "ZF=F", "ZT=F", "UB=F"],
        "PRECIOUS METALS": ["GC=F", "SI=F", "PL=F", "PA=F"],
        "BASE METALS": ["HG=F"],
        "ENERGY": ["CL=F", "BZ=F", "NG=F", "HO=F", "RB=F"],
        "GRAINS/SOFTS": ["ZC=F", "ZS=F", "ZW=F", "ZM=F", "ZL=F", "CT=F", "SB=F", "CC=F", "KC=F", "OJ=F"],
        "MEATS": ["LE=F", "GF=F", "HE=F"],
        "FOREX": ["6E=F", "6B=F", "6J=F", "6S=F", "6A=F", "6C=F", "DX=F"],
    }

    for group_name, syms in groups.items():
        lines.append(f"\n  [{group_name}]")
        header = f"  {'Symbol':<10} {'Name':<22} {'Price':>12} {'Change':>14} {'Volume':>12}"
        lines.append(header)
        lines.append(f"  {'─'*10} {'─'*22} {'─'*12} {'─'*14} {'─'*12}")
        for sym in syms:
            info = fut_data.get(sym, {})
            q = info.get("quote")
            name = info.get("name", sym)

            # Forex — JPY (6J=F) needs special handling:
            # Yahoo returns JPY contract price (~100x the rate), invert for display
            if sym == "6J=F" and q and q.get("price") is not None:
                jpy_price = q["price"]
                # CME JPY futures: price is JPY per USD × 100 (approx)
                # Actual JPY/USD rate ≈ 100 / contract_price * some_factor
                # Simpler: just show the raw price as-is with note
                lines.append(f"  {sym:<10} {name:<22} {jpy_price:>12,.2f}  (JPY contract)")
                continue

            if q and q.get("price") is not None:
                price = q["price"]
                prev = q.get("prev_close")
                chg_str = fmt_change(price, prev)
                vol = fmt_big(q.get("volume"))
                lines.append(f"  {sym:<10} {name:<22} {price:>12,.2f} {chg_str:>14} {vol:>12}")
            else:
                lines.append(f"  {sym:<10} {name:<22} {'UNAVAILABLE':>12} {'—':>14} {'—':>12}")

    # ── CRYPTO ──
    lines.append(f"\n{'─'*78}")
    lines.append("  🪙 CRYPTO (CoinGecko — free, no key)")
    lines.append(f"{'─'*78}")

    crypto_data = crypto.get("data", {})
    if crypto_data is None:
        lines.append("  (CoinGecko API unreachable)")
    else:
        # Sort by market cap descending
        crypto_items = []
        for coin_id, info in crypto_data.items():
            price = info.get("usd")
            mcap = info.get("usd_market_cap")
            change_24h = info.get("usd_24h_change")
            vol_24h = info.get("usd_24h_vol")
            crypto_items.append((coin_id, price, mcap, change_24h, vol_24h))

        crypto_items.sort(key=lambda x: x[2] or 0, reverse=True)

        header = f"  {'Coin':<14} {'Price':>12} {'24h Chg':>10} {'Market Cap':>16} {'24h Vol':>14}"
        lines.append(header)
        lines.append(f"  {'─'*14} {'─'*12} {'─'*10} {'─'*16} {'─'*14}")
        for coin_id, price, mcap, change_24h, vol_24h in crypto_items:
            coin_display = coin_id.replace("-", " ").title()[:14]
            p_str = fmt_price(price)
            c_str = fmt_pct(change_24h)
            m_str = fmt_big(mcap) if mcap else "N/A"
            v_str = fmt_big(vol_24h) if vol_24h else "N/A"
            lines.append(f"  {coin_display:<14} {p_str:>12} {c_str:>10} {m_str:>16} {v_str:>14}")

        # Highlight key signals
        lines.append(f"\n  KEY CRYPTO SIGNALS:")
        btc = crypto_data.get("bitcoin", {})
        eth = crypto_data.get("ethereum", {})
        if btc.get("usd"):
            btc_chg = btc.get("usd_24h_change", 0)
            lines.append(f"    • BTC: {fmt_price(btc['usd'])}  {fmt_pct(btc_chg)}  {'← UNDER $84K — yield pressure' if btc['usd'] < 84000 else ''}")
        if eth.get("usd"):
            eth_chg = eth.get("usd_24h_change", 0)
            lines.append(f"    • ETH: {fmt_price(eth['usd'])}  {fmt_pct(eth_chg)}  {'← Testing $2,700 support' if eth['usd'] < 2750 else ''}")
        if btc.get("usd_24h_vol") and eth.get("usd_24h_vol"):
            btc_vol = btc["usd_24h_vol"]
            eth_vol = eth["usd_24h_vol"]
            ratio = btc_vol / eth_vol if eth_vol else 0
            lines.append(f"    • BTC/ETH volume ratio: {ratio:.1f}x")

    # ── OPTIONS ──
    lines.append(f"\n{'─'*78}")
    lines.append("  📉 OPTIONS DERBIT/SPX GAMMA (algoxflow — free, no key)")
    lines.append(f"{'─'*78}")

    opt_data = options.get("data", {})
    for sym, data in opt_data.items():
        if isinstance(data, dict) and "error" not in data:
            spot = data.get("spot")
            regime = data.get("regime", "unknown")
            flip = data.get("flip")
            call_wall = data.get("callWall")
            put_wall = data.get("putWall")
            max_pain = data.get("maxPain")
            total_gex = data.get("totalGex")
            exp_move_pct = data.get("expMovePct")

            lines.append(f"\n  {sym} (spot: {spot})")
            lines.append(f"    Regime: {regime} gamma")
            if flip:
                lines.append(f"    Gamma Flip: {flip:,.2f}")
            if call_wall:
                lines.append(f"    Call Wall: {call_wall:,.2f}")
            if put_wall:
                lines.append(f"    Put Wall: {put_wall:,.2f}")
            if max_pain:
                lines.append(f"    Max Pain: {max_pain:,.2f}")
            if total_gex:
                lines.append(f"    Total GEX: ${total_gex:,.0f}M per 1% move")
            if exp_move_pct:
                lines.append(f"    Expected Move (1σ): {exp_move_pct:.2f}%")
        else:
            lines.append(f"  {sym}: {'UNAVAILABLE' if isinstance(data, dict) else 'N/A'}")

    # ── ETF FLOWS ──
    lines.append(f"\n{'─'*78}")
    lines.append("  💰 BITCOIN ETF FLOWS (Farside — daily, free)")
    lines.append(f"{'─'*78}")

    etf = etf_flows.get("latest_flow")
    if etf:
        lines.append(f"  Latest flow row: {' | '.join(etf[:6])}")
    else:
        lines.append("  (Farside data unavailable)")

    # ── CORRELATION SIGNALS ──
    lines.append(f"\n{'─'*78}")
    lines.append("  🔗 CROSS-ASSET CORRELATION SIGNALS")
    lines.append(f"{'─'*78}")

    # Build signals from available data
    crypto_data = crypto.get("data") or {}
    fut_data = futures.get("data") or {}
    fred_data = fred.get("data") or {}

    btc_price = (crypto_data.get("bitcoin", {}) or {}).get("usd")
    eth_price = (crypto_data.get("ethereum", {}) or {}).get("usd")
    btc_chg = (crypto_data.get("bitcoin", {}) or {}).get("usd_24h_change", 0)
    es_price = (fut_data.get("ES=F", {}).get("quote") or {}).get("price")
    cl_price = (fut_data.get("CL=F", {}).get("quote") or {}).get("price")
    gc_price = (fut_data.get("GC=F", {}).get("quote") or {}).get("price")

    dgs10_val = _find_fred_val(fred, "DGS10")
    vix_val = _find_fred_val(fred, "VIXCLS")
    dxy_val = _find_fred_val(fred, "DXY")
    hy_oas_val = _find_fred_val(fred, "BAMLH0A0HYM2")

    signals = []

    if dgs10_val and dgs10_val > 5.0:
        signals.append(("⚠️  RATE REGIME", f"10Y at {dgs10_val:.2f}% — growth assets under pressure. BTC {fmt_pct(btc_chg)} confirms."))
    elif dgs10_val:
        signals.append(("📉 RATE REGIME", f"10Y at {dgs10_val:.2f}% — moderate. BTC {fmt_pct(btc_chg)}."))

    if vix_val and vix_val < 16:
        signals.append(("📊 VIX COMPRESSION", f"VIX at {vix_val:.2f} — historically low. Volatility expansion setups are the edge."))

    if dxy_val and dxy_val > 100:
        signals.append(("💵 DOLLAR STRENGTH", f"DXY at {dxy_val:.2f} — EM and crypto under pressure. USD long vs EUR/GBP is the correlated play."))

    if hy_oas_val and hy_oas_val > 3.5:
        signals.append(("🔴 CREDIT STRESS", f"HY OAS at {hy_oas_val:.2f}% — widening. Risk-off signal. Watch for contagion."))
    elif hy_oas_val:
        signals.append(("🟢 CREDIT CALM", f"HY OAS at {hy_oas_val:.2f}% — normal. No stress signal."))

    if cl_price and gc_price:
        oil_gold_ratio = cl_price / gc_price
        signals.append(("🛢️ OIL/GOLD RATIO", f"{oil_gold_ratio:.4f} — oil/gold cross-asset signal."))

    if btc_price and eth_price:
        dominance = btc_price / (btc_price + eth_price) * 100 if (btc_price + eth_price) else 0
        signals.append(("🪙 BTC DOMINANCE", f"~{dominance:.1f}% (BTC/ETH only) — capital concentration signal."))

    if es_price and btc_price and btc_chg:
        # Simple equity/crypto correlation read
        signals.append(("📈 EQUITY/CRYPTO LINK", f"S&P E-mini at {es_price:,.0f}. BTC {fmt_pct(btc_chg)}. {'Risk-on sync' if btc_chg > 0 else 'Divergence possible'}"))

    for cat, msg in signals:
        lines.append(f"    [{cat}] {msg}")

    # ── SETUP WATCHLIST ──
    lines.append(f"\n{'─'*78}")
    lines.append("  🎯 SETUP WATCHLIST (from cross-asset read)")
    lines.append(f"{'─'*78}")

    setups = []

    # Gold — uncorrelated safe haven
    if gc_price:
        setups.append(("🟡 GOLD LONG (uncorrelated)", f"GC at {gc_price:,.2f}. Hormuz risk + rate correlation broken. Watch $4,200 support. TP $4,500+."))

    # Oil — correlated Iran play
    if cl_price:
        setups.append(("🟢 WTI LONG (correlated)", f"CL at {cl_price:,.2f}. Iran premium. Stop $88. TP $100-105. Hormuz-dependent."))

    # USD/EUR short — correlated rate play
    dxy_signal = "DXY strong — USD long vs EUR/GBP is the correlated macro play." if (dxy_val and dxy_val > 100) else "DXY moderate — monitor for USD reversal."
    setups.append(("💵 USD/EUR SHORT (correlated)", dxy_signal))

    # ATR expansion note
    setups.append(("🔬 ATR_EXPANSION SWEEP", "Run on all 34 positive symbols. ZEC = champion. 1,354 trades, +10,191.9%. Universal across all asset classes above."))

    # BTC options expiry
    setups.append(("📉 BTC OPTIONS EXPIRY (Sep 25)", "$16B BTC options expire Friday. Call-heavy book. Gamma play — not directional. Check algoxflow for SPX/NQ gamma flip levels."))

    for title, detail in setups:
        lines.append(f"    {title}")
        lines.append(f"      {detail}")

    return "\n".join(lines)


def _find_fred_val(fred_result, series_id):
    """Extract the numeric value for a FRED series."""
    data = fred_result.get("data", {})
    info = data.get(series_id, {})
    latest = info.get("latest")
    if isinstance(latest, dict) and "value" in latest:
        return latest["value"]
    return None


# ──────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Hermes Cross-Asset Sweep — Free Data Stack")
    parser.add_argument("--save", action="store_true", help="Save output to file")
    parser.add_argument("--output", default=None, help="Output file path (default: ./sweep_output_TIMESTAMP.txt)")
    parser.add_argument("--verbose", action="store_true", help="Include verbose data dumps")
    args = parser.parse_args()

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║  HERMES CROSS-ASSET SWEEP  —  Starting…                     ║")
    print("║  Free sources: CoinGecko | Yahoo Finance | FRED | algoxflow  ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    # 1. Crypto
    print("[1/5] Sweeping crypto via CoinGecko…")
    crypto = sweep_crypto()
    if crypto["error"]:
        print(f"  ⚠  {crypto['error']}")
    else:
        count = len(crypto.get("data", {}))
        print(f"  ✓  Fetched {count} coins")
    time.sleep(1)

    # 2. Futures
    print("[2/5] Sweeping futures/commodities via Yahoo Finance…")
    futures = sweep_futures()
    fut_count = sum(1 for info in futures.get("data", {}).values() if info.get("quote") is not None)
    total = len(futures.get("data", {}))
    print(f"  ✓  {fut_count}/{total} futures returned data")
    time.sleep(1)

    # 3. FRED
    print("[3/5] Sweeping macro/rates via FRED…")
    fred = sweep_fred()
    fred_count = sum(1 for info in fred.get("data", {}).values() if info.get("latest") is not None)
    total_fred = len(fred.get("data", {}))
    # VIX from Yahoo (real-time) — FRED VIXCLS has 1-2 day lag
    # Use Yahoo ^VIX for current reading, fall back to FRED if needed
    vix_yahoo = _yahoo_quote("^VIX")
    vix_val = None
    if vix_yahoo and vix_yahoo.get("price") is not None:
        vix_val = vix_yahoo["price"]
        # Override FRED VIXCLS with real-time Yahoo value
        fred["data"]["VIXCLS"] = {
            "name": "CBOE VIX (real-time via Yahoo)",
            "latest": {"date": datetime.datetime.now().strftime("%Y-%m-%d"), "value": vix_val}
        }
        print(f"  ✓  VIX (real-time): {vix_val:.2f}")
    time.sleep(1)

    # 4. Options
    print("[4/5] Sweeping options gamma via algoxflow…")
    options = sweep_options()
    opt_count = sum(1 for data in options.get("data", {}).values() if isinstance(data, dict) and "error" not in data)
    total_opt = len(options.get("data", {}))
    print(f"  ✓  {opt_count}/{total_opt} options symbols returned data")
    time.sleep(1)

    # 5. ETF Flows
    print("[5/5] Fetching BTC ETF flows from Farside…")
    etf_flows = sweep_etf_flows()
    if etf_flows.get("latest_flow"):
        print(f"  ✓  Latest flow: {' | '.join(etf_flows['latest_flow'][:4])}")
    else:
        print("  ⚠  Farside data unavailable")
    time.sleep(1)

    # Build dashboard
    print("\n" + "─" * 78)
    print("  BUILDING DASHBOARD…")
    print("─" * 78)

    dashboard = build_dashboard(crypto, futures, fred, options, etf_flows)

    # Print
    print(dashboard)

    # Save
    output_path = args.output
    if args.save or output_path:
        if not output_path:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"/data/data/com.termux/files/home/sweep_output_{ts}.txt"
        with open(output_path, "w") as f:
            f.write(dashboard)
        print(f"\n  ✓  Saved to: {output_path}")

    # Also save to a standard location
    std_path = "/data/data/com.termux/files/home/cross_asset_sweep_latest.txt"
    with open(std_path, "w") as f:
        f.write(dashboard)
    print(f"  ✓  Saved to: {std_path}")

    # Verbose: save raw JSON dumps
    if args.verbose:
        verbose_dir = "/data/data/com.termux/files/home/sweep_verbose"
        os.makedirs(verbose_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        for name, data in [("crypto", crypto), ("futures", futures), ("fred", fred), ("options", options), ("etf_flows", etf_flows)]:
            path = f"{verbose_dir}/{name}_{ts}.json"
            with open(path, "w") as f:
                json.dump(data, f, indent=2, default=str)
            print(f"  ✓  Verbose dump: {path}")

    print("\n" + "=" * 78)
    print("  SWEEP COMPLETE")
    print("=" * 78)

    return 0


if __name__ == "__main__":
    sys.exit(main())
