#!/usr/bin/env python3
"""
Fill missing symbols — Yahoo Finance (primary) + CoinGecko (fallback) + Coinbase (last resort).

Yahoo Finance "/v8/finance/chart/{BASE}-USD" returns 180+ days of daily OHLCV
for most established crypto — free, no key, no practical rate limits.
CoinGecko 90d market_chart/range as fallback for coins Yahoo doesn't cover.
Coinbase /v2/exchange-rates synthetic 1-candle only as last resort (sanity-checked).
"""

import sys, json, time, sqlite3, ssl, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/data/data/com.termux/files/home')

DB_PATH = '/data/data/com.termux/files/home/zeus_brain.db'

now = datetime.now(timezone.utc)
to_ts = int(now.timestamp())
ctx = ssl.create_default_context()


# ── Yahoo Finance 180d daily candles ──────────────────────────────────────────
def yahoo_daily(sym_usdt, max_days=180):
    """Return list of (ts, open, high, low, close, volume) or None."""
    base = sym_usdt.replace("USDT", "").replace("USD", "").upper()
    from_ts = int((now - timedelta(days=max_days)).timestamp())
    for ticker in [f"{base}-USD", f"{base}USD=X"]:
        url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(ticker)}"
               f"?period1={from_ts}&period2={to_ts}&interval=1d&events=history")
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; zeus-bot/1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                data = json.loads(r.read().decode())
            result = data.get("chart", {}).get("result", [])
            if not result:
                continue
            res = result[0]
            ts_raw = res.get("timestamp", [])
            q = res.get("indicators", {}).get("quote", [{}])[0]
            o = q.get("open", [])
            h = q.get("high", [])
            l = q.get("low", [])
            c = q.get("close", [])
            v = q.get("volume", [])
            if not c or all(x is None for x in c):
                continue
            rows = []
            for i in range(len(ts_raw)):
                if c[i] is None:
                    continue
                rows.append((ts_raw[i], o[i] or c[i], h[i] or c[i], l[i] or c[i], c[i], v[i] or 0))
            if len(rows) >= 10:
                return rows
        except Exception:
            continue
    return None


# ── CoinGecko 90d daily (fallback) ─────────────────────────────────────────────
def cg_daily(cg_id, max_days=90):
    if cg_id is None:
        return None
    from_ts = int((now - timedelta(days=max_days)).timestamp())
    url = (f"https://api.coingecko.com/api/v3/coins/{urllib.parse.quote(cg_id)}"
           f"/market_chart/range?vs_currency=usd&from={from_ts}&to={to_ts}")
    req = urllib.request.Request(url, headers={"User-Agent": "zeus-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            data = json.loads(r.read().decode())
    except Exception:
        return None
    if data is None or '_http_error' in data:
        return None
    prices = data.get("prices", [])
    volumes = data.get("total_volumes", [])
    if not prices:
        return None
    vol_by_day = {}
    for v in volumes:
        day = int(v[0] / 86400000) * 86400000
        vol_by_day[day] = v[1]
    seen = set()
    rows = []
    for pt in prices:
        ts_ms = pt[0]
        day = int(ts_ms / 86400000) * 86400000
        if day in seen:
            continue
        seen.add(day)
        price = pt[1]
        vol = vol_by_day.get(day, 0)
        rows.append((int(day / 1000), price, price, price, price, vol))
    return rows if len(rows) >= 10 else None


# ── Coinbase /v2/exchange-rates (last resort) ─────────────────────────────────
def coinbase_rates():
    url = "https://api.coinbase.com/v2/exchange-rates?currency=USD"
    req = urllib.request.Request(url, headers={"User-Agent": "zeus-bot/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            data = json.loads(r.read().decode())
        return data.get("data", {}).get("rates", {})
    except Exception:
        return {}


CB_ASSET_FOR = {
    "OKBUSDT":"OKB","KCSUSDT":"KCS","FTTUSDT":"FTT","GTUSDT":"GT","KINUSDT":"KIN",
    "LEOUSDT":"LEO","XMRUSDT":"XMR","DENTUSDT":"DENT","IOTXUSDT":"IOTX","SCUSDT":"SC",
    "STORJUSDT":"STORJ","RPLUSDT":"RPL","NMRUSDT":"NMR","FILUSDT":"FIL","TFLOUSDT":"FLOW",
    "QNTUSDT":"QNT","BANDUSDT":"BAND","UMAUSDT":"UMA","MVIUSDT":"MVI","CVCUSDT":"CVC",
    "DASHUSDT":"DASH","ZECUSDT":"ZEC","ARUSDT":"AR","AGIUSDT":"AGIX",
    "DEGENUSDT":"DEGEN","FCUSDT":"FC","YOLOUSDT":"YOLO","NEIROUSDT":"NEIRO",
    "MYROUSDT":"MYRO","MOGUSDT":"MOG","WENUSDT":"WEN","TREMPUSDT":"TREMP",
    "ADMINUSDT":"ADMIN","TYPUSDT":"TYP","OHMUSDT":"OHM","DEUSDT":"DEU",
    "OMUSDT":"OMG","ZNTUSDT":"ZNT","FIRUSDT":"FIRM","PRIVACYUSDT":"PRIVACY",
    "BANXAUSDT":"BANXA","REALUSDT":"REAL","PORTUSDT":"PORTO","TLOSUSDT":"TLOS",
    "HAIUSDT":"HAI","GOALUSDT":"GALA","WOKUSDT":"WOK","MUMBAIUSDT":"MUMBAI",
    "VINEUSDT":"VINE","TNSUSDT":"TNS","ZROUSDT":"ZRO",
    "PIXELFUSDT":"PIXELF","VRDRWDUSDT":"VRDRWD","ULTUSDT":"ULT",
    "PQUSDT":"PQ","PROPUSDT":"PROP","READYUSDT":"READY","CACUSDT":"CAC",
    "TENSORSUSDT":"TENSORS","AF8USDT":"AF8","CEEDUSDT":"CEED",
}


def cb_rate(sym, rates):
    asset = CB_ASSET_FOR.get(sym)
    if asset is None:
        asset = sym.replace("USDT", "").replace("USD", "").upper()
    r = rates.get(asset)
    return float(r) if r else None


def is_sane(price):
    return 0.0001 < price < 1_000_000


# ── CoinGecko id map ────────────────────────────────────────────────────────────
CG_ID_MAP = {
    "OKBUSDT":"okb","KCSUSDT":"kucoin-token","GTUSDT":"gatechain-token","KINUSDT":"kin",
    "LEOUSDT":"unus-sed-leo","XMRUSDT":"monero","DENTUSDT":"dent","IOTXUSDT":"iotex",
    "SCUSDT":"siacoin","STORJUSDT":"storj","RPLUSDT":"rocket-pool-token","NMRUSDT":"numeraire",
    "FILUSDT":"filecoin","TFLOUSDT":"flow-token","QNTUSDT":"quant","BANDUSDT":"band-protocol",
    "UMAUSDT":"uma","MVIUSDT":"media-vision","CVCUSDT":"coventry","DASHUSDT":"dash",
    "ZECUSDT":"zcash","ARUSDT":"arweave","AGIUSDT":"singularitynet","DEGENUSDT":"degens-token",
    "FCUSDT":"farcaster","YOLOUSDT":"yolo","NEIROUSDT":"neiro","MYROUSDT":"myro",
    "MOGUSDT":"mog-coin","WENUSDT":"wen-coin","TREMPUSDT":"tremp","ADMINUSDT":"admin-coin",
    "OHMUSDT":"olympus","DEUSDT":"decentralized-ether","OMUSDT":"omisego","ZNTUSDT":"znet",
    "FIRUSDT":"firmachain","PRIVACYUSDT":"privacy","REALUSDT":"real-yield","PORTUSDT":"porto",
    "TLOSUSDT":"telos","HAIUSDT":"haiku","GOALUSDT":"goal-token","VINEUSDT":"vine-co",
    "TNSUSDT":"ternoa","ZROUSDT":"zero","ULTUSDT":"ultimate-backdrop",
}


# ── Main ─────────────────────────────────────────────────────────────────────────
def main():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA journal_mode=WAL")
    cs = db.cursor()

    missing = cs.execute(
        "SELECT symbol FROM candle_sources "
        "LEFT JOIN (SELECT symbol, COUNT(*) as n FROM candles GROUP BY symbol) c USING(symbol) "
        "WHERE c.n < 50 OR c.n IS NULL ORDER BY symbol"
    ).fetchall()
    missing_syms = [r[0] for r in missing]
    print(f"Missing symbols to fill: {len(missing_syms)}")
    if not missing_syms:
        print("  Nothing to fill — DB is complete.")
        db.close()
        return

    # Fetch Coinbase rates upfront (one call)
    print("Fetching Coinbase /v2/exchange-rates ...")
    cb_rates = coinbase_rates()
    print(f"  → {len(cb_rates)} rates")

    results = []
    for sym in missing_syms:
        cg_id = CG_ID_MAP.get(sym)
        candle_rows = None
        source = None

        # Tier 1: Yahoo Finance 180d
        print(f"  [{sym:15s}] Yahoo ...", end=' ', flush=True)
        rows = yahoo_daily(sym, max_days=180)
        if rows and len(rows) >= 10:
            candle_rows = rows
            source = "yahoo"
            print(f"✓ {len(rows)}d [yahoo]")
        else:
            print("✗", end=' ')

        # Tier 2: CoinGecko 90d
        if not candle_rows and cg_id:
            print("CG ...", end=' ', flush=True)
            rows = cg_daily(cg_id, max_days=90)
            if rows and len(rows) >= 10:
                candle_rows = rows
                source = "coingecko"
                print(f"✓ {len(rows)}d [cg]")
            else:
                print("✗", end=' ')
        elif not candle_rows:
            print("CG n/a", end=' ')

        # Tier 3: Coinbase synthetic (only sanity-checked)
        if not candle_rows:
            rate = cb_rate(sym, cb_rates)
            if rate and is_sane(rate):
                ts_y = int((now - timedelta(days=1)).timestamp())
                candle_rows = [(ts_y, rate, rate, rate, rate, rate)]
                source = "coinbase"
                print(f"CB ${rate:.4f} → 1d synth")
            else:
                print("all fail → unavailable")

        # Insert
        if candle_rows and source:
            for (ts, o, h, l, c, v) in candle_rows:
                cs.execute(
                    "INSERT OR REPLACE INTO candles (symbol, tf, ts, open, high, low, close, volume, source, fetched_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (sym, "1d", ts, o, h, l, c, v, source, int(now.timestamp()))
                )
            db.commit()
            results.append((sym, source, len(candle_rows)))
        else:
            results.append((sym, "none", 0))

        time.sleep(0.3)

    # Summary
    print()
    print("─" * 60)
    n_real = sum(1 for _, src, n in results if n >= 10)
    n_synth = sum(1 for _, src, n in results if 0 < n < 10)
    n_none = sum(1 for _, src, n in results if n == 0)
    print(f"  Real data (≥10 candles):  {n_real}/{len(results)}")
    print(f"  Synthetic (1 candle):     {n_synth}/{len(results)}")
    print(f"  Still unavailable:        {n_none}/{len(results)}")
    print()
    for sym, src, n in results:
        if n >= 10:
            tag = f"✓ {n:3d}d [{src}]"
        elif n > 0:
            tag = f"○ {n}d [{src}] (synth)"
        else:
            tag = "✗ unavailable"
        print(f"  {sym:15s}  {tag}")

    total = db.execute("SELECT COUNT(DISTINCT symbol) FROM candles").fetchone()[0]
    print(f"\nTotal symbols with candles in DB: {total}")
    db.close()


if __name__ == "__main__":
    main()
