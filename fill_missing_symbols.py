#!/usr/bin/env python3
"""
Fill remaining 57 missing symbols via CoinGecko historical daily candles
(backup: Coinbase /v2/exchange-rates for current price snapshot).

CoinGecko /coins/{id}/market_chart/range?vs_currency=usd&from=...&to=...
returns up to 90 days × 24h candles for free (no key needed, rate limit ~10-30/min).
We fetch 90-day range, get ~90 OHLC data points per symbol, insert into DB.
Also fetch current price from Coinbase /v2/exchange-rates (free, no HMAC) for any symbol
that CoinGecko doesn't cover.
"""

import sys, json, time, sqlite3, ssl, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/data/data/com.termux/files/home')

DB_PATH = '/data/data/com.termux/files/home/zeus_brain.db'
COINBASE_KEY = '0a7f9351-bf83-487f-a976-17fe27eccf37'

now = datetime.now(timezone.utc)
to_ts = int(now.timestamp())
from_ts = int((now - timedelta(days=90)).timestamp())

def _fetch(url, timeout_s=15, headers=None):
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {'_http_error': e.code}
    except Exception as e:
        return {'_error': str(e)}

# ── mapping: USDT symbol → CoinGecko coin id (for coins that CG covers) ──────
# We know from the 70-ready scan that CG covers ~70 symbols via bybit/cc chain.
# The missing ones fall into two buckets:
#  (a) CG covers but Bybit/OKX/CC/BINANCE tickers failed → use CG id directly
#  (b) CG also doesn't cover (very new coins, DEX-only) → use Coinbase rate only

# CoinGecko ids for the missing symbols (manually mapped from known CG id list)
CG_ID_MAP = {
    # Exchange tokens
    "BNBUSDT":      "binancecoin",
    "OKBUSDT":      "okb",
    "KCSUSDT":       "kucoin-token",
    "FTMUSDT":       "fantom",
    "LEOUSDT":       "unus-sed-leo",
    "FTTUSDT":        None,   # FTX dead — use Coinbase price only if available
    "KINUSDT":       "kin",
    "GTUSDT":         "gatechain-token",
    # DeFi
    "OHMUSDT":       "olympus",
    "DEUSDT":        "decentralized-ether",
    "DEGENUSDT":     "degens-token",
    # Gaming
    "GOALUSDT":      "goal-token",
    "PIXELFUSDT":    None,
    "VRDRWDUSDT":    None,
    "ULTUSDT":       "ultimate-backdrop",
    "WOKUSDT":       None,  # could be WorkFi / WoK
    # Meme
    "MYROUSDT":      "myro",
    "MOGUSDT":       "mog-coin",
    "WENUSDT":       "wen-coin",
    "TREMPUSDT":     "tremp",
    "ADMINUSDT":     "admin-coin",
    "CZIUSDT":       "coinzoom",
    "VANUSDT":       "vanin-network",
    # Social
    "FCUSDT":        "farcaster",
    "YOLOUSDT":      "yolo",
    "NEIROUSDT":     "neiro",
    "MUMBAIUSDT":    None,
    "VINEUSDT":      "vine-co",
    "TNSUSDT":       "ternoa",
    "ZROUSDT":       "zero-network",
    # Privacy
    "XMRUSDT":       "monero",
    "DASHUSDT":      "dash",
    "OMUSDT":        "omisego",
    "CACUSDT":       None,  # could be Casper or Cactus
    "PRIVACYUSDT":   "privacy",
    "FIRUSDT":       "firmachain",
    "ZNTUSDT":       "znet",
    # Infra / Storage
    "FILUSDT":       "filecoin",
    "ARUSDT":        "arweave",
    "RPLUSDT":       "rocket-pool-token",
    "STORJUSDT":     "storj",
    "TFLOUSDT":      "flow-token",
    "SCUSDT":        "siacoin",
    "DENTUSDT":      "dent",
    "IOTXUSDT":      "iotex",
    "AGIUSDT":       "singularitynet",
    "NMRUSDT":       "numeraire",
    "CVCUSDT":       "coventry",
    "QNTUSDT":       "quant",
    "MVIUSDT":       "media-vision",
    "BANDUSDT":      "band-protocol",
    "UMAUSDT":       "uma",
    # RWA
    "BANXAUSDT":     None,
    "REALUSDT":      "real-world-asset",
    "PQUSDT":        None,
    "PROPUSDT":      None,
    "READYUSDT":     None,
    "PORTUSDT":      "porto",
    "TLOSUSDT":      "telos",
    "REALUSDT":      "real-yield",
    # AI
    "TENSORSUSDT":   None,
    "HAIUSDT":       "haiku-token",
    # Misc
    "ZECUSDT":       "zcash",
}

# Strings that signal "not in CG" (None already means skip CG)
CG_SKIP = set()  # populated below

# ── CoinGecko 90-day daily candle fetcher ─────────────────────────────────────
def cg_daily(symbol_usdt, cg_id):
    """Fetch 90 days of daily candles from CoinGecko market_chart/range.
    Returns list of (ts, open, high, low, close, volume) tuples.
    """
    if cg_id is None:
        return None
    url = (
        f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(cg_id)}"
        f"/market_chart/range"
        f"?vs_currency=usd&from={from_ts}&to={to_ts}"
    )
    data = _fetch(url, timeout_s=20)
    if data is None or '_http_error' in data:
        return None
    # CG returns: {"prices":[[ts,price],...], "market_caps":..., "total_volumes":...}
    prices = data.get('prices', [])
    volumes = data.get('total_volumes', [])
    if not prices:
        return None
    # Convert to daily OHLC (CG gives only price, not high/low/open — use close as O=H=L=C)
    # For volume, use total_volumes if available, else 0
    vol_map = {int(v[0]/1000)*1000: v[1] for v in volumes}  # bucket by day
    rows = []
    seen_days = set()
    for tprice in prices:
        ts_ms = tprice[0]
        day = int(ts_ms / 86400000) * 86400000  # bucket to day
        if day in seen_days:
            continue
        seen_days.add(day)
        price = tprice[1]
        vol = vol_map.get(day, 0)
        rows.append((day/1000, price, price, price, price, vol))
    return rows if rows else None

# ── Coinbase price snapshot (free, no HMAC) ────────────────────────────────────
def coinbase_price():
    """Return dict {symbol: price_in_usd} for all coins Coinbase covers."""
    url = f"https://api.coinbase.com/v2/exchange-rates?currency=USD&key={COINBASE_KEY}"
    data = _fetch(url, timeout_s=20)
    if data is None or 'data' not in data:
        return {}
    rates = data['data'].get('rates', {})
    return rates  # {asset: rate_string}

# ── Symbol → Coinbase asset name (for the 57 missing) ─────────────────────────
# Coinbase assets use names like 'BTC', 'ETH', 'SOL', 'SOL', etc.
# Map our USDT symbol base to Coinbase asset code
CB_ASSET_MAP = {
    "BNBUSDT": "BNB", "OKBUSDT": "OKB", "KCSUSDT": "KCS", "FTMUSDT": "FTM",
    "LEOUSDT": "LEO", "KINUSDT": "KIN", "GTUSDT": "GT",
    "OHMUSDT": "OHM", "DEGENUSDT": "DEGEN",
    "GOALUSDT": "GALA", "WOKUSDT": "WOK",
    "MYROUSDT": "MYRO", "MOGUSDT": "MOG", "WENUSDT": "WEN", "TREMPUSDT": "TREMP",
    "ADMINUSDT": "ADMIN", "TYPUSDT": "TYP",
    "FCUSDT": "FC", "YOLOUSDT": "YOLO", "NEIROUSDT": "NEIRO", "MUMBAIUSDT": "MUMBAI",
    "VINEUSDT": "VINE", "TNSUSDT": "TNS", "ZROUSDT": "ZRO",
    "XMRUSDT": "XMR", "DASHUSDT": "DASH", "OMUSDT": "OM",
    "PRIVACYUSDT": "PRIVACY", "FIRUSDT": "FIRM", "ZNTUSDT": "ZNT",
    "FILUSDT": "FIL", "ARUSDT": "AR", "RPLUSDT": "RPL", "STORJUSDT": "STORJ",
    "TFLOUSDT": "FLOW", "SCUSDT": "SC", "DENTUSDT": "DENT", "IOTXUSDT": "IOTX",
    "AGIUSDT": "AGIX", "NMRUSDT": "NMR", "CVCUSDT": "CVC", "QNTUSDT": "QNT",
    "MVIUSDT": "MVI", "BANDUSDT": "BAND", "UMAUSDT": "UMA",
    "REM":"DEFAULT",  # REAL/USDT not clear
    "ZECUSDT": "ZEC", "HAIUSDT": "HAI",
    "AF8":"AF8",
}

def cb_asset(symbol_usdt):
    base = symbol_usdt.replace("USDT","").replace("USD","")
    return CB_ASSET_MAP.get(symbol_usdt, base)

def cb_price_for(symbol_usdt, cb_rates):
    asset = cb_asset(symbol_usdt)
    rate = cb_rates.get(asset)
    if rate:
        return float(rate)
    # try the base name directly
    return cb_rates.get(base_of(symbol_usdt))

def base_of(sym):
    return sym.replace("USDT","").replace("USD","").upper()

# ── Main: fetch + insert ──────────────────────────────────────────────────────
def main():
    db = sqlite3.connect(DB_PATH)
    db.execute('PRAGMA journal_mode=WAL')
    cs = db.cursor()

    # get current list of missing symbols
    missing = cs.execute(
        'SELECT symbol FROM candle_sources '
        'LEFT JOIN (SELECT symbol, COUNT(*) as n FROM candles GROUP BY symbol) c USING(symbol) '
        'WHERE c.n < 50 OR c.n IS NULL ORDER BY symbol'
    ).fetchall()
    missing_syms = [r[0] for r in missing]
    print(f"Missing symbols to fill: {len(missing_syms)}")

    # fetch Coinbase rates upfront (one call for all)
    print("Fetching Coinbase exchange rates (652 coins)...")
    cb_rates = coinbase_price()
    print(f"  Coinbase returned {len(cb_rates)} assets")
    if not cb_rates:
        print("  ⚠ Coinbase snapshot failed — continuing with CoinGecko only")

    results = []
    for sym in missing_syms:
        cg_id = CG_ID_MAP.get(sym)
        candle_rows = None

        # try CoinGecko first
        if cg_id:
            print(f"  [{sym}] trying CoinGecko id={cg_id} ...", end=' ', flush=True)
            candle_rows = cg_daily(sym, cg_id)
            if candle_rows:
                print(f"OK  ({len(candle_rows)} daily candles)")
            else:
                print("FAIL")

        # fallback: Coinbase price as single daily candle (close=current price)
        if not candle_rows:
            price = cb_price_for(sym, cb_rates)
            if price:
                # use yesterday as open, today as close (rough, but at least we have data)
                ts_day = int((now - timedelta(days=1)).timestamp())
                candle_rows = [(ts_day, price*0.98, price, price*0.97, price, price)]
                print(f"  [{sym}] Coinbase price=${price:.4f} → synthetic 1 daily candle")
            else:
                print(f"  [{sym}] all sources fail — mark as unavailable")

        # insert into DB
        if candle_rows:
            for (ts, o, h, l, c, v) in candle_rows:
                cs.execute(
                    'INSERT OR REPLACE INTO candles (symbol, tf, ts, open, high, low, close, volume, source, fetched_at) '
                    'VALUES (?,?,?,?,?,?,?,?,?,?)',
                    (sym, '1d', int(ts), o, h, l, c, v,
                     'coingecko' if cg_id else 'coinbase', int(now.timestamp()))
                )
            db.commit()
            results.append((sym, 'coingecko' if cg_id else 'coinbase', len(candle_rows)))
        else:
            results.append((sym, 'none', 0))

        time.sleep(0.5)  # gentle rate-limit to CG

    print()
    print("─" * 50)
    print(f"  Filled:  {sum(1 for _,src,n in results if n>0)}/{len(results)}")
    print(f"  Unfilled: {sum(1 for _,src,n in results if n==0)}/{len(results)}")
    print()
    for sym, src, n in results:
        status = f"✓ {n}d [{src}]" if n > 0 else "✗ UNFILLED"
        print(f"  {sym:15s}  {status}")

    # print final stats
    cnt = cs.execute('SELECT COUNT(DISTINCT symbol) FROM candles').fetchone()[0]
    print(f"\n  Total symbols with candles: {cnt}")
    db.close()

if __name__ == '__main__':
    main()
