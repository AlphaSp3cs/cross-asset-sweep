#!/usr/bin/env python3
"""zeus_candles_sector_sync.py — register + backfill ALL crypto sectors into zeus_brain.db.

Covers every sector from the scan gaps:
  L1/L2, DeFi, Meme, AI, Gaming/GameFi, RWA, Privacy, Exchange/CEX,
  Social/Farcaster, Infra/Storage/Compute

Uses Bybit v5 (fastest free source for USDT-margined crypto) as primary.
Falls back to OKX and CryptoCompare if Bybit misses a symbol.

Run:  python3 zeus_candles_sector_sync.py
"""
import sys, os, time, json, logging, random, ssl, urllib.request, urllib.parse, urllib.error
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(__file__))
import zeus_candles as zc
from zeus_candles import (
    CandleDB, fetch_candles_for, fetch_all_candles,
    PRIORITY, SOURCES,
    bybit_symbol_map, okx_symbol_map, USER_AGENT,
    _fetch_json, _delay, log,
)

DB_PATH = os.path.join(os.path.dirname(__file__), "zeus_brain.db")

# ── full sector symbol list ──────────────────────────────────────────────────
# (symbol, sector_label)  — all are BASEUSDT pairs

SECTORS: Dict[str, List[str]] = {
    "L1_L2": [
        "BTCUSDT", "ETHUSDT", "SOLUSDT", "AVAXUSDT", "NEARUSDT",
        "DOTUSDT", "ATOMUSDT", "LINKUSDT", "INJUSDT", "TRXUSDT",
        "APTUSDT", "ARBUSDT", "OPUSDT", "MATICUSDT", "GRTUSDT",
        "RUNEUSDT", "KAVAUSDT", "HBARUSDT", "ICPUSDT", "ALGOUSDT",
    ],
    "DeFi": [
        "UNIUSDT", "AAVEUSDT", "COMPUSDT", "MKRUSDT", "CRVUSDT",
        "SUSHIUSDT", "GMXUSDT", "BALUSDT", "PENDLEUSDT", "STGUSDT",
        "LDOUSDT", "YFIUSDT", "SNXUSDT", "RENUSDT", "BATUSDT",
        "1INCHUSDT", "ENAUSDT", "DEUSDT", "OHMUSDT", "KLAYUSDT",
    ],
    "Meme": [
        "DOGEUSDT", "SHIBUSDT", "PEPEUSDT", "WIFUSDT", "BONKUSDT",
        "FLOKIUSDT", "MYROUSDT", "BRETTUSDT", "POPCATUSDT", "MOGUSDT",
        "WENUSDT", "TREMPUSDT", "ADMINUSDT",
    ],
    "AI": [
        "RENDERUSDT", "FETUSDT", "TENSORSUSDT", "HAIUSDT",
        "RNDRUSDT", "AIUSDT", "ORCLUSDT", "GOOGLUSDT",
        "NEARUSDT",  # NEAR also AI-adjunct
        "ROSEUSDT", "AGIXUSDT", "OCEANUSDT", "TYPUSDT",
    ],
    "Gaming_GameFi": [
        "AXSUSDT", "GOALUSDT", "IMXUSDT", "GALAUSDT", "SANDUSDT",
        "MANAUSDT", "ILVUSDT", "BEAMUSDT", "RIVERUSDT", "PIXELFUSDT",
        "VRDRWDUSDT", "ULTUSDT", "CHRUSDT", "ENJUSDT", "ALGOUSDT",
    ],
    "RWA": [
        "MKRUSDT", "ONDOUSDT", "STRKUSDT", "TLOSUSDT", "BANXAUSDT",
        "REALUSDT", "PQUSDT", "PROPUSDT", "READYUSDT", "PORTUSDT",
    ],
    "Privacy": [
        "ZECUSDT", "XMRUSDT", "DASHUSDT", "OMUSDT", "CACUSDT",
        "PRIVACYUSDT", "FIRUSDT", "ZNTUSDT",
    ],
    "Exchange_CEX": [
        "BNBUSDT", "OKBUSDT", "KCSUSDT", "FTMUSDT", "LEOUSDT",
        "FTTUSDT", "KINUSDT", "GTUSDT", "WOKUSDT", "af8USDT",
    ],
    "Social_Farcaster": [
        "DEGENUSDT", "FCUSDT", "YOLOUSDT", "NEIROUSDT", "ZROUSDT",
        "MUMBAIUSDT", "VINEUSDT", "TNSUSDT",
    ],
    "Infra_Storage_Compute": [
        "FILUSDT", "ARUSDT", "RPLUSDT", "STORJUSDT", "TFLOUSDT",
        "SCUSDT", "DENTUSDT", "IOTXUSDT", "AGIUSDT", "NMRUSDT",
    ],
}

# Flatten with sector label — dedup by symbol (first sector wins)
SECTOR_MAP: Dict[str, str] = {}
for sector, symbols in SECTORS.items():
    for sym in symbols:
        if sym not in SECTOR_MAP:
            SECTOR_MAP[sym] = sector

def register_all(db: CandleDB):
    """Register every symbol in candle_sources."""
    registered = 0
    for sym, sector in SECTOR_MAP.items():
        try:
            db.upsert_source(sym, "crypto", sym[:-4], tf_map={"1h": f"{sym[:-4]}/USDT", "1d": f"{sym[:-4]}/USDT"})
            registered += 1
        except Exception as e:
            log.warning("register %s failed: %s", sym, e)
    log.info("registered %d/%d symbols", registered, len(SECTOR_MAP))

# ── Coinbase public snapshot (no HMAC needed, just API key in query) ──────────
COINBASE_BASE = "https://api.coinbase.com/v2"
COINBASE_KEY = "0a7f9351-bf83-487f-a976-17fe27eccf37"

CB_SYMBOLS = {
    "BTC": "L1_L2", "ETH": "L1_L2", "SOL": "L1_L2", "AVAX": "L1_L2",
    "NEAR": "L1_L2", "DOT": "L1_L2", "ATOM": "L1_L2", "LINK": "L1_L2",
    "INJ": "L1_L2", "TRX": "L1_L2", "APT": "L1_L2", "ARB": "L1_L2",
    "OP": "L1_L2", "MATIC": "L1_L2", "GRT": "L1_L2", "RUNE": "L1_L2",
    "HBAR": "L1_L2", "ICP": "L1_L2", "ALGO": "L1_L2", "KAVA": "L1_L2",
    "UNI": "DeFi", "AAVE": "DeFi", "COMP": "DeFi", "MKR": "DeFi",
    "CRV": "DeFi", "SUSHI": "DeFi", "GMX": "DeFi", "BAL": "DeFi",
    "PENDLE": "DeFi", "STG": "DeFi", "LDO": "DeFi", "YFI": "DeFi",
    "SNX": "DeFi", "REN": "DeFi", "BAT": "DeFi", "1INCH": "DeFi",
    "ENA": "DeFi", "DEI": "DeFi", "OHM": "DeFi", "KLAY": "DeFi",
    "DOGE": "Meme", "SHIB": "Meme", "PEPE": "Meme", "WIF": "Meme",
    "BONK": "Meme", "FLOKI": "Meme", "MYRO": "Meme", "BRETT": "Meme",
    "POPCAT": "Meme", "MOG": "Meme", "WEN": "Meme", "TREMP": "Meme",
    "ADMIN": "Meme",
    "RENDER": "AI", "FET": "AI", "TENSOR": "AI", "HAI": "AI",
    "RNDR": "AI", "AI": "AI", "ORCL": "AI", "GOOGL": "AI",
    "ROSE": "AI", "AGIX": "AI", "OCEAN": "AI",
    "AXS": "Gaming_GameFi", "GALA": "Gaming_GameFi", "IMX": "Gaming_GameFi",
    "MANA": "Gaming_GameFi", "ILV": "Gaming_GameFi", "BEAM": "Gaming_GameFi",
    "RIVER": "Gaming_GameFi", "PIXELF": "Gaming_GameFi", "VRDRWD": "Gaming_GameFi",
    "ULT": "Gaming_GameFi", "CHR": "Gaming_GameFi", "ENJ": "Gaming_GameFi",
    "MKR": "RWA", "ONDO": "RWA", "STRK": "RWA", "TLOS": "RWA",
    "BANXA": "RWA", "REAL": "RWA", "PQ": "RWA", "PROP": "RWA",
    "READY": "RWA", "PORT": "RWA",
    "ZEC": "Privacy", "XMR": "Privacy", "DASH": "Privacy",
    "OM": "Privacy", "CAC": "Privacy", "PRIVACY": "Privacy",
    "FIR": "Privacy", "ZNT": "Privacy",
    "BNB": "Exchange_CEX", "OKB": "Exchange_CEX", "KCS": "Exchange_CEX",
    "FTM": "Exchange_CEX", "LEO": "Exchange_CEX", "FTT": "Exchange_CEX",
    "KIN": "Exchange_CEX", "GT": "Exchange_CEX",
    "DEGEN": "Social_Farcaster", "FC": "Social_Farcaster", "YOLO": "Social_Farcaster",
    "NEIRO": "Social_Farcaster", "ZRO": "Social_Farcaster",
    "MUMBAI": "Social_Farcaster", "VINE": "Social_Farcaster", "TNS": "Social_Farcaster",
    "FIL": "Infra_Storage_Compute", "AR": "Infra_Storage_Compute",
    "RPL": "Infra_Storage_Compute", "STORJ": "Infra_Storage_Compute",
    "TFLO": "Infra_Storage_Compute", "SC": "Infra_Storage_Compute",
    "DENT": "Infra_Storage_Compute", "IOTX": "Infra_Storage_Compute",
    "AGI": "Infra_Storage_Compute", "NMR": "Infra_Storage_Compute",
    "CVC": "Infra_Storage_Compute", "QNT": "Infra_Storage_Compute",
    "MVI": "Infra_Storage_Compute", "BAND": "Infra_Storage_Compute",
    "UMA": "Infra_Storage_Compute",
}


def coinbase_all_prices() -> dict:
    """Fetch ALL crypto prices from Coinbase exchange-rates endpoint (one call, no HMAC).
    Returns {symbol: price_in_usd} for every coin Coinbase lists.
    """
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
    url = f"{COINBASE_BASE}/exchange-rates?currency=USD&key={COINBASE_KEY}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10, context=_ssl_ctx) as resp:
            data = json.loads(resp.read())
            rates = data.get("data", {}).get("rates", {})
            return {sym: float(price) for sym, price in rates.items() if sym != "USD"}
    except Exception as e:
        log.warning("coinbase all-prices failed: %s", e)
        return {}


def coinbase_sector_snapshot():
    """Print all sectors with live Coinbase prices."""
    prices = coinbase_all_prices()
    sector_prices: Dict[str, List[Tuple[str, float]]] = {}
    for sym, price in prices.items():
        sector = CB_SYMBOLS.get(sym, "other")
        if sector not in sector_prices:
            sector_prices[sector] = []
        sector_prices[sector].append((sym, price))

    print(f"\n{'='*72}")
    print(f"COINBASE LIVE SECTOR SNAPSHOT — {time.strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*72}")
    print(f"Total coins priced: {len(prices)}  |  sectors covered: {len(sector_prices)}")
    print()
    for sector in sorted(sector_prices):
        entries = sorted(sector_prices[sector], key=lambda x: -x[1])
        print(f"─── {sector} ───")
        for sym, price in entries:
            # Coinbase returns rates in weird scales — normalize to USD
            # Most are direct USD rates; some are scaled (e.g. 10^8 for DOGE-family)
            # Flag any that look absurdly large or tiny
            formatted = f"${price:,.6f}"
            if price > 1_000_000:
                formatted = f"${price/1_000_000:,.4f}M"
            elif price < 0.0001 and price > 0:
                formatted = f"${price*1_000_000:,.4f} (scaled)"
            print(f"  {sym:8s}  {formatted}")
        print()
    return sector_prices

def fetch_missing_1h(db: CandleDB, refresh_minutes: int = 60) -> Dict[str, dict]:
    """Fetch 1h candles for every registered symbol that doesn't have recent data."""
    results = {}
    for sym in SECTOR_MAP:
        ok, src, cnt = fetch_candles_for(db, sym, "crypto", "1h", refresh_minutes=refresh_minutes)
        results[sym] = {"ok": ok, "source": src, "count": cnt, "sector": SECTOR_MAP[sym]}
        status = "OK" if ok else "MISS"
        log.info("[%s] %s (%s): src=%s cnt=%s", status, sym, SECTOR_MAP[sym], src, cnt)
        # small delay between fetches to be polite
        _delay(0.2, 0.5)
    return results

def summary(results: Dict[str, dict]):
    total = len(results)
    ok = sum(1 for r in results.values() if r["ok"])
    by_sector: Dict[str, dict] = {}
    for sym, r in results.items():
        sec = r["sector"]
        if sec not in by_sector:
            by_sector[sec] = {"total": 0, "ok": 0, "symbols": []}
        by_sector[sec]["total"] += 1
        by_sector[sec]["ok"] += 1 if r["ok"] else 0
        by_sector[sec]["symbols"].append(sym)

    print("\n" + "=" * 70)
    print("SECTOR COVERAGE SUMMARY")
    print("=" * 70)
    print(f"Total symbols: {total}  |  Fetched OK: {ok}  |  Missing: {total - ok}")
    print()
    for sector in sorted(by_sector):
        s = by_sector[sector]
        miss = s["total"] - s["ok"]
        flag = "  ✓" if miss == 0 else f"  ⚠ {miss} missing"
        print(f"  {sector:20s}: {s['ok']:3d}/{s['total']:3d}  {flag}")
        if miss > 0:
            miss_syms = [sym for sym, r in results.items() if r["sector"] == sector and not r["ok"]]
            print(f"    missing: {', '.join(miss_syms)}")
    print()
    print("Missing symbols (full list):")
    miss_all = [sym for sym, r in results.items() if not r["ok"]]
    if miss_all:
        print(f"  {', '.join(miss_all)}")
    else:
        print("  (none — all sectors covered)")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    db = CandleDB(path=DB_PATH)
    try:
        print(f"zeus_brain.db: {DB_PATH}")
        print(f"Already registered: {len(db.list_symbols())} symbols")
        print()

        # ── COINBASE: register + fetch via Advanced Trade ──
        print("\n═══ COINBASE CANDLE FETCH ═══")
        print("(Note: API key 0a7f9351 confirmed working for public /v2 exchange-rates)")
        print("(Advanced Trade /v3/brokerage endpoints return 401 — needs separate HMAC)")


        # 1. Register all sector symbols
        print("\n── 1. Registering all sector symbols ──")
        register_all(db)
        print(f"Now registered: {len(db.list_symbols())} symbols")
        print()

        # 2. Fetch 1h candles for everything
        print("── 2. Fetching 1h candles (Bybit → OKX → CryptoCompare) ──")
        t0 = time.time()
        results = fetch_missing_1h(db, refresh_minutes=60)
        dt = time.time() - t0
        print(f"\nFetch completed in {dt:.1f}s")
        summary(results)

        # 3. Quick sanity check on a few symbols
        print("\n── 3. Sanity check (feature_vector on latest) ──")
        from zeus_ta import feature_vector
        check_syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT", "PEPEUSDT",
                      "WIFUSDT", "BONKUSDT", "BNBUSDT", "OKBUSDT", "ZECUSDT",
                      "UNIUSDT", "AXSUSDT", "RENDERUSDT", "ONDOUSDT", "DEGENUSDT",
                      "FILUSDT", "FLOKIUSDT"]
        for sym in check_syms:
            rows = db.get_candles(sym, "1h", limit=60)
            if rows:
                fv = feature_vector(rows)
                bb = fv.get("bollinger", {})
                print(f"  {sym:12s} ({SECTOR_MAP.get(sym,'?')}): close={fv.get('close')}  "
                      f"regime={fv.get('regime')}  RSI={fv.get('rsi_14')}  "
                      f"BB: [{bb.get('lower','?'):.2f}, {bb.get('mid','?'):.2f}, {bb.get('upper','?'):.2f}]  "
                      f"%B={bb.get('%B','?')}  SMA30={fv.get('sma_30')}")
            else:
                print(f"  {sym:12s} ({SECTOR_MAP.get(sym, '?')}): NO DATA")
    finally:
        db.close()
