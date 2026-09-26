"""
zeus_candles.py — SQLite candle store + free candle fetchers with source fallback.

Zero external dependencies. Uses stdlib urllib + sqlite3 + json + time.

Architecture:
  - SQLite DB (zeus_brain.db) with tables: candles, candle_sources
  - Fetchers per source: kraken, bybit, okx, cryptocompare, yahoo, binance (fallback)
  - Source priority chain per asset class:
      crypto: kraken -> bybit -> okx -> cryptocompare -> binance
      equities/etfs/futures/forex: yahoo (only free public option)
  - Upsert logic: insert new candles, skip existing, keep last N per symbol+tf
  - Batch fetch: fetch all symbols for a given TF in one pass
  - Cache: do not refetch if fresh candles already exist within refresh_minutes

Author: Hermes agent (built for zeus-brain)
"""

from __future__ import annotations

import sqlite3
import time
import json
import urllib.request
import urllib.error
import urllib.parse
import ssl
import math
import random
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any, Tuple

from zeus_ta import Row  # reuse Row type: (ts, o, h, l, c, v)


# ── logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("zeus_candles")


# ── DB ─────────────────────────────────────────────────────────────────────────

DB_PATH = "zeus_brain.db"

CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS candles (
    symbol TEXT NOT NULL,
    tf TEXT NOT NULL,
    ts INTEGER NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    source TEXT NOT NULL,
    fetched_at INTEGER NOT NULL,
    PRIMARY KEY (symbol, tf, ts)
);

CREATE TABLE IF NOT EXISTS candle_sources (
    symbol TEXT PRIMARY KEY,
    class TEXT NOT NULL,
    base_symbol TEXT,
    tf_1m TEXT,
    tf_5m TEXT,
    tf_15m TEXT,
    tf_1h TEXT,
    tf_4h TEXT,
    tf_1d TEXT,
    last_fetched_1m INTEGER,
    last_fetched_5m INTEGER,
    last_fetched_15m INTEGER,
    last_fetched_1h INTEGER,
    last_fetched_4h INTEGER,
    last_fetched_1d INTEGER
);
"""


class CandleDB:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(CREATE_TABLES)
        self.conn.commit()

    def close(self):
        self.conn.close()

    # ── upsert ────────────────────────────────────────────────────────────────

    def upsert_candles(
        self,
        symbol: str,
        tf: str,
        rows: List[Row],
        source: str,
    ):
        """Insert or replace candles for one symbol+TF. rows = list of (ts,o,h,l,c,v)."""
        if not rows:
            return
        now = int(time.time())
        data = [(symbol, tf, r[0], r[1], r[2], r[3], r[4], r[5], source, now)
                for r in rows]
        self.conn.executemany(
            "INSERT OR REPLACE INTO candles (symbol,tf,ts,open,high,low,close,volume,source,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            data,
        )
        self.conn.commit()

    def upsert_candles_batch(
        self,
        batch: List[Tuple[str, str, List[Row], str]],
    ):
        """batch = list of (symbol, tf, rows, source)."""
        now = int(time.time())
        data = []
        for sym, tf, rows, source in batch:
            for r in rows:
                data.append((sym, tf, r[0], r[1], r[2], r[3], r[4], r[5], source, now))
        if not data:
            return
        self.conn.executemany(
            "INSERT OR REPLACE INTO candles (symbol,tf,ts,open,high,low,close,volume,source,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            data,
        )
        self.conn.commit()

    def upsert_source(self, symbol: str, class_: str, base_symbol: str = "",
                      tf_map: Dict[str, str] = None):
        """Register a symbol with its class and base symbol (for mapping to exchange symbols)."""
        tf_map = tf_map or {}
        self.conn.execute(
            "INSERT OR REPLACE INTO candle_sources (symbol, class, base_symbol, "
            "tf_1m, tf_5m, tf_15m, tf_1h, tf_4h, tf_1d) VALUES (?,?,?,"
            "COALESCE((SELECT tf_1m FROM candle_sources WHERE symbol=?),?),"
            "COALESCE((SELECT tf_5m FROM candle_sources WHERE symbol=?),?),"
            "COALESCE((SELECT tf_15m FROM candle_sources WHERE symbol=?),?),"
            "COALESCE((SELECT tf_1h FROM candle_sources WHERE symbol=?),?),"
            "COALESCE((SELECT tf_4h FROM candle_sources WHERE symbol=?),?),"
            "COALESCE((SELECT tf_1d FROM candle_sources WHERE symbol=?),?))",
            (symbol, class_, base_symbol,
             symbol, tf_map.get("1m", ""), symbol, tf_map.get("5m", ""),
             symbol, tf_map.get("15m", ""), symbol, tf_map.get("1h", ""),
             symbol, tf_map.get("4h", ""), symbol, tf_map.get("1d", "")),
        )
        self.conn.commit()

    def get_candles(
        self,
        symbol: str,
        tf: str,
        limit: int = 500,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
    ) -> List[Row]:
        """Get candles for symbol+TF, newest first, ordered by ts desc."""
        qs = "SELECT ts, open, high, low, close, volume FROM candles WHERE symbol=? AND tf=? AND ts IS NOT NULL"
        params = [symbol, tf]
        if min_ts is not None:
            qs += " AND ts >= ?"
            params.append(min_ts)
        if max_ts is not None:
            qs += " AND ts <= ?"
            params.append(max_ts)
        qs += " ORDER BY ts DESC LIMIT ?"
        params.append(limit)
        rows = self.conn.execute(qs, params).fetchall()
        # flip to oldest-first for TA
        rows = list(reversed(rows))
        return [(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])) for r in rows]

    def get_latest_ts(self, symbol: str, tf: str) -> Optional[int]:
        row = self.conn.execute(
            "SELECT MAX(ts) FROM candles WHERE symbol=? AND tf=?",
            (symbol, tf)
        ).fetchone()
        return int(row[0]) if row and row[0] else None

    def prune(self, symbol: str, tf: str, keep: int = 500):
        """Keep only the newest `keep` candles per symbol+TF."""
        self.conn.execute(
            "DELETE FROM candles WHERE symbol=? AND tf=? AND ts NOT IN "
            "(SELECT ts FROM candles WHERE symbol=? AND tf=? ORDER BY ts DESC LIMIT ?)",
            (symbol, tf, symbol, tf, keep),
        )
        self.conn.commit()

    def prune_all(self, keep_per_tf: Dict[str, int] = None):
        """Prune all symbols: keep last N per symbol+TF."""
        keep_per_tf = keep_per_tf or {"1m": 500, "5m": 500, "15m": 500, "1h": 500, "4h": 500, "1d": 500}
        rows = self.conn.execute(
            "SELECT DISTINCT symbol, tf FROM candles"
        ).fetchall()
        for sym, tf in rows:
            keep = keep_per_tf.get(tf, 500)
            self.prune(sym, tf, keep)

    def symbol_exists(self, symbol: str, tf: str) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol=? AND tf=?",
            (symbol, tf)
        ).fetchone()
        return bool(row and row[0] > 0)

    def list_symbols(self) -> List[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT symbol FROM candle_sources ORDER BY symbol"
        ).fetchall()
        return [r[0] for r in rows]

    def list_by_class(self, class_: str) -> List[str]:
        rows = self.conn.execute(
            "SELECT DISTINCT symbol FROM candle_sources WHERE class=? ORDER BY symbol",
            (class_,)
        ).fetchall()
        return [r[0] for r in rows]

    def count_candles(self, symbol: str, tf: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol=? AND tf=?",
            (symbol, tf)
        ).fetchone()
        return int(row[0]) if row and row[0] else 0

    def bulk_insert_no_dup(self, symbol: str, tf: str, rows: List[Row], source: str):
        """Insert only rows whose (ts) doesn't already exist. Faster for large batches."""
        if not rows:
            return
        now = int(time.time())
        existing_ts = set()
        for i in range(0, len(rows), 500):
            chunk = rows[i:i+500]
            ts_list = [r[0] for r in chunk]
            placeholders = ','.join('?' * len(ts_list))
            ex = self.conn.execute(
                f"SELECT ts FROM candles WHERE symbol=? AND tf=? AND ts IN ({placeholders})",
                [symbol, tf] + ts_list
            ).fetchall()
            existing_ts.update(int(r[0]) for r in ex)
        to_insert = [r for r in rows if r[0] not in existing_ts]
        if not to_insert:
            return
        data = [(symbol, tf, r[0], r[1], r[2], r[3], r[4], r[5], source, now) for r in to_insert]
        self.conn.executemany(
            "INSERT OR REPLACE INTO candles (symbol,tf,ts,open,high,low,close,volume,source,fetched_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            data,
        )
        self.conn.commit()


# ── HTTP helpers ───────────────────────────────────────────────────────────────

USER_AGENT = "ZeusBrain/1.0 (free research; +https://github.com/AlphaSp3cs)"

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE


def _fetch_json(url: str, timeout: int = 15, headers: Dict[str, str] = None) -> Optional[Any]:
    """Fetch JSON from url. Returns parsed JSON or None on failure."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
            data = resp.read()
            if not data:
                return None
            return json.loads(data.decode("utf-8", errors="replace"))
    except Exception as e:
        log.warning("fetch failed: %s → %s", url[:80], e)
        return None


def _fetch_text(url: str, timeout: int = 15, headers: Dict[str, str] = None) -> Optional[str]:
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_ctx) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning("fetch text failed: %s → %s", url[:80], e)
        return None


def _delay(min_s: float = 0.3, max_s: float = 1.0):
    """Random small delay between requests to be polite."""
    time.sleep(random.uniform(min_s, max_s))


# ── YYYY-MM-DD helpers ─────────────────────────────────────────────────────────

def _to_epoch_yahoo(date_str: str) -> int:
    """'2026-09-26' → epoch midnight UTC."""
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return int(dt.replace(tzinfo=timezone.utc).timestamp())


def _epoch_to_yahoo(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


# ── source: Kraken ─────────────────────────────────────────────────────────────

KRAKEN_ROOT = "https://api.kraken.com/0/public"


def kraken_symbol_map(symbol: str) -> Optional[str]:
    """Convert 'BTCUSDT' → 'XBT/USD' or 'ETHUSDT' → 'ETH/USD' for Kraken classic OHLC."""
    if symbol.endswith("USDT"):
        base = symbol[:-4]
        if base == "BTC":
            return "XBT/USD"
        return f"{base}/USDT"
    if symbol.endswith("USD"):
        base = symbol[:-3]
        if base == "BTC":
            return "XBT/USD"
        return f"{base}/USD"
    if symbol.endswith("BTC"):
        base = symbol[:-3]
        return f"{base}/XBT"
    # try classic
    return symbol


def kraken_fetch(symbol: str, tf: str, since: Optional[int] = None,
                 limit: int = 500) -> Optional[List[Row]]:
    """Kraken public OHLC (classic endpoint). Returns oldest-first rows.

    tf: '1m','5m','15m','1h','4h','1d' → Kraken interval code
    since: epoch seconds (fetch since this ts)
    """
    interval_map = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": 1440}
    interval = interval_map.get(tf)
    if interval is None:
        return None
    pair = kraken_symbol_map(symbol)
    if not pair:
        return None
    url = f"{KRAKEN_ROOT}/OHLC?pair={urllib.parse.quote(pair)}&interval={interval}"
    if since:
        url += f"&since={since}"
    data = _fetch_json(url, timeout=20,
                       headers={"User-Agent": USER_AGENT})
    if not data or "result" not in data:
        return None
    result = data["result"]
    # result is { "XXBTZUSD": [...], "last": ts }
    for key, ohlc in result.items():
        if isinstance(ohlc, list):
            rows = []
            for candle in ohlc:
                if len(candle) < 7:
                    continue
                ts = int(candle[0])
                if since and ts < since:
                    continue
                rows.append((
                    ts,
                    float(candle[1]),  # open
                    float(candle[3]),  # high
                    float(candle[4]),  # low
                    float(candle[2]),  # close
                    float(candle[6]),  # volume
                ))
            return rows
    # fallback: any list in result
    for key, val in result.items():
        if isinstance(val, list) and len(val) > 0 and len(val[0]) >= 7:
            rows = []
            for candle in val:
                ts = int(candle[0])
                if since and ts < since:
                    continue
                rows.append((ts, float(candle[1]), float(candle[3]),
                             float(candle[4]), float(candle[2]), float(candle[6])))
            return rows
    return None


# ── source: Bybit ───────────────────────────────────────────────────────────────

BYBIT_ROOT = "https://api.bybit.com/v5/market/kline"


def bybit_symbol_map(symbol: str) -> str:
    """'BTCUSDT' → 'BTCUSDT'."""
    return symbol


def bybit_fetch(symbol: str, tf: str, since: Optional[int] = None,
                limit: int = 500) -> Optional[List[Row]]:
    """Bybit v5 kline endpoint. Spot or perp via category.

    tf: '1m','5m','15m','1h','4h','1d'
    Returns oldest-first rows.
    """
    interval_map = {"1m": "1", "5m": "5", "15m": "15", "1h": "60",
                    "4h": "240", "1d": "D"}
    interval = interval_map.get(tf)
    if interval is None:
        return None
    cat = "linear" if symbol.endswith("USDT") or symbol.endswith("USDC") else "spot"
    inst = bybit_symbol_map(symbol)
    params = f"?category={cat}&symbol={inst}&interval={interval}&limit={limit}"
    if since:
        params += f"&startTime={since}"
    url = BYBIT_ROOT + params
    data = _fetch_json(url, timeout=20,
                       headers={"User-Agent": USER_AGENT})
    if not data or "result" not in data:
        return None
    klines = data["result"].get("list")
    if not klines:
        return None
    rows = []
    for k in klines:
        if len(k) < 6:
            continue
        ts = int(k[0]) // 1000  # bybit uses ms
        rows.append((
            ts,
            float(k[1]),
            float(k[3]),
            float(k[4]),
            float(k[2]),
            float(k[5]),
        ))
    return list(reversed(rows))  # oldest first


# ── source: OKX ────────────────────────────────────────────────────────────────

OKX_ROOT = "https://www.okx.com/api/v5/market/history-candles"


def okx_symbol_map(symbol: str) -> str:
    """'BTCUSDT' → 'BTC-USDT'."""
    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USDT"
    if symbol.endswith("USDC"):
        return symbol[:-4] + "-USDC"
    if symbol.endswith("USD"):
        return symbol[:-3] + "-USD"
    return symbol


def okx_fetch(symbol: str, tf: str, since: Optional[int] = None,
              limit: int = 500) -> Optional[List[Row]]:
    """OKX v5 history-candles. Returns oldest-first rows.

    tf: '1m','5m','15m','1h','4h','1d'
    """
    interval_map = {"1m": "1m", "5m": "5m", "15m": "15m",
                    "1h": "1H", "4h": "4H", "1d": "1D"}
    interval = interval_map.get(tf)
    if interval is None:
        return None
    inst = okx_symbol_map(symbol)
    params = f"?instId={inst}&bar={interval}&limit={limit}"
    if since:
        params += f"&after={since}"
    url = OKX_ROOT + params
    data = _fetch_json(url, timeout=20,
                       headers={"User-Agent": USER_AGENT})
    if not data or not isinstance(data, list):
        return None
    rows = []
    for c in data:
        if len(c) < 6:
            continue
        ts = int(c[0])  # okx returns s
        rows.append((
            ts,
            float(c[1]),
            float(c[3]),
            float(c[4]),
            float(c[2]),
            float(c[5]),
        ))
    return list(reversed(rows))


# ── source: CryptoCompare ──────────────────────────────────────────────────────

CC_ROOT = "https://min-api.cryptocompare.com/data/v2"


def cryptocompare_fetch(symbol: str, tf: str, since: Optional[int] = None,
                        limit: int = 500) -> Optional[List[Row]]:
    """CryptoCompare v2 historical. Daily only on free tier (histoday).
    Also histohour for some pairs.

    Returns oldest-first rows.
    """
    base = symbol[:-4] if symbol.endswith("USDT") else (symbol[:-3] if symbol.endswith("USD") else symbol)
    tosym = "USD"
    if tf == "1d":
        url = (f"{CC_ROOT}/histoday?fsym={base}&tsym={to_sym}&"
               f"limit={limit}&aggregate=1")
    elif tf in ("1h", "4h"):
        url = (f"{CC_ROOT}/histohour?fsym={base}&tsym={to_sym}&"
               f"limit={limit}&aggregate={'4' if tf == '4h' else '1'}")
    else:
        # minute resolution requires paid tier; return None
        return None
    if since:
        url += f"&toTs={since}"
    data = _fetch_json(url, timeout=20,
                       headers={"User-Agent": USER_AGENT})
    if not data or data.get("Response") != "Success" and "Data" not in data:
        return None
    data_payload = data.get("Data", data)
    if isinstance(data_payload, dict):
        data_payload = data_payload.get("Data", [])
    rows = []
    for c in data_payload:
        if not isinstance(c, dict):
            continue
        ts = int(c.get("time", 0))
        if since and ts < since:
            continue
        close = c.get("close")
        high = c.get("high")
        low = c.get("low")
        open_ = c.get("open")
        vol = c.get("volumeto", c.get("volumefrom", 0))
        if close is None or high is None or low is None or open_ is None:
            continue
        rows.append((ts, float(open_), float(high), float(low), float(close), float(vol)))
    return list(reversed(rows))


# ── source: Yahoo Finance (via chart API) ──────────────────────────────────────

YAHOO_ROOT = "https://query1.finance.yahoo.com/v8/finance/chart"


def yahoo_fetch(symbol: str, tf: str, since: Optional[int] = None,
                limit: int = 500) -> Optional[List[Row]]:
    """Yahoo Finance chart API. Works for stocks, ETFs, some crypto, some futures.

    symbol: Yahoo ticker e.g. 'BTC-USD', 'SPY', 'CL=F', 'EURUSD=X'
    tf: '1m','5m','15m','1h','4h','1d'  (1m/5m/15m intraday, 1h/4h/1d daily-ish)
    """
    interval_map = {
        "1m": "1m", "5m": "5m", "15m": "15m",
        "1h": "1h", "4h": "6h", "1d": "1d",
    }
    interval = interval_map.get(tf, "1d")
    period = "1mo" if tf in ("1m", "5m", "15m", "1h") else "2y"
    url = (f"{YAHOO_ROOT}/{urllib.parse.quote(symbol)}?interval={interval}"
           f"&period1={since or 0}&period2={int(time.time())}"
           f"&range={period}&includePrePost=false")
    data = _fetch_json(url, timeout=20,
                       headers={"User-Agent": USER_AGENT})
    if not data or "chart" not in data:
        return None
    chart = data["chart"]
    result = chart.get("result")
    if not result:
        return None
    res0 = result[0]
    ts_list = res0.get("timestamp")
    quotes = res0.get("indicators", {}).get("quote", [{}])[0]
    closes = quotes.get("close")
    opens = quotes.get("open")
    highs = quotes.get("high")
    lows = quotes.get("low")
    vols = quotes.get("volume")
    if not ts_list or not closes:
        return None
    rows = []
    for i, ts in enumerate(ts_list):
        c = closes[i]
        o = opens[i] if opens and i < len(opens) else c
        h = highs[i] if highs and i < len(highs) else c
        l = lows[i] if lows and i < len(lows) else c
        v = vols[i] if vols and i < len(vols) and vols[i] else 0.0
        if c is None:
            continue
        t = int(ts)
        if since and t < since:
            continue
        rows.append((t, float(o), float(h), float(l), float(c), float(v)))
    return list(reversed(rows))


# ── source: Binance (fallback) ─────────────────────────────────────────────────

BINANCE_ROOT = "https://api.binance.com/api/v3/klines"


def binance_fetch(symbol: str, tf: str, since: Optional[int] = None,
                  limit: int = 500) -> Optional[List[Row]]:
    """Binance public klines. May timeout on Termux — fallback only.

    symbol: 'BTCUSDT'
    tf: '1m','5m','15m','1h','4h','1d'
    """
    interval_map = {"1m": "1m", "5m": "5m", "15m": "15m",
                    "1h": "1h", "4h": "4h", "1d": "1d"}
    interval = interval_map.get(tf, "1h")
    params = f"?symbol={symbol}&interval={interval}&limit={limit}"
    if since:
        params += f"&startTime={since}"
    url = BINANCE_ROOT + params
    data = _fetch_json(url, timeout=10,
                       headers={"User-Agent": USER_AGENT})
    if not data or not isinstance(data, list):
        return None
    rows = []
    for k in data:
        if len(k) < 6:
            continue
        ts = int(k[0]) // 1000
        rows.append((
            ts,
            float(k[1]),
            float(k[3]),
            float(k[4]),
            float(k[2]),
            float(k[5]),
        ))
    return list(reversed(rows))


# ── source registry ────────────────────────────────────────────────────────────

# source name → fetcher function + symbol map
SOURCES = {
    "kraken": {
        "fetch": kraken_fetch,
        "map": kraken_symbol_map,
        "class": "crypto",
    },
    "bybit": {
        "fetch": bybit_fetch,
        "map": bybit_symbol_map,
        "class": "crypto",
    },
    "okx": {
        "fetch": okx_fetch,
        "map": okx_symbol_map,
        "class": "crypto",
    },
    "cryptocompare": {
        "fetch": cryptocompare_fetch,
        "map": lambda s: s,
        "class": "crypto",
    },
    "yahoo": {
        "fetch": yahoo_fetch,
        "map": lambda s: s,
        "class": "all",
    },
    "binance": {
        "fetch": binance_fetch,
        "map": lambda s: s,
        "class": "crypto",
    },
}

# priority chain per class: first source that works wins
PRIORITY = {
    "crypto": ["kraken", "bybit", "okx", "cryptocompare", "binance", "yahoo"],
    "equity": ["yahoo"],
    "etf": ["yahoo"],
    "future": ["yahoo"],
    "forex": ["yahoo"],
}


def resolve_symbol(symbol: str, class_: str) -> Dict[str, Any]:
    """Return info for a symbol: class, which sources to try, and per-source mapped symbol."""
    return {
        "symbol": symbol,
        "class": class_,
        "sources": PRIORITY.get(class_, ["yahoo"]),
        "yahoo_symbol": symbol,  # yahoo uses its own tickers
    }


# ── fetch orchestration ────────────────────────────────────────────────────────

FETCH_PARAMS = {
    "1m": {"limit": 500},
    "5m": {"limit": 500},
    "15m": {"limit": 500},
    "1h": {"limit": 500},
    "4h": {"limit": 500},
    "1d": {"limit": 500},
}


def fetch_candles_for(
    db: CandleDB,
    symbol: str,
    class_: str,
    tf: str,
    refresh_minutes: int = 30,
    max_retries_per_source: int = 2,
) -> Tuple[bool, Optional[str], Optional[int]]:
    """Fetch candles for one symbol+TF using source priority chain.

    Returns (ok, source_used, count).
    Handles:
      - check DB for fresh candles (skip if fetch not needed)
      - try each source in priority order until one returns data
      - map symbol per source
      - upsert into DB
    """
    if tf not in FETCH_PARAMS:
        return False, None, 0
    params = FETCH_PARAMS[tf]
    limit = params["limit"]

    # Check freshness: if we have candles and the newest is within refresh_minutes, skip
    latest_ts = db.get_latest_ts(symbol, tf)
    if latest_ts:
        ago = int(time.time()) - latest_ts
        if ago < refresh_minutes * 60:
            log.info("skip %s %s — fresh candles (age %ds)", symbol, tf, ago)
            cnt = db.count_candles(symbol, tf)
            return True, "cached", cnt

    symbol_info = resolve_symbol(symbol, class_)
    sources_to_try = symbol_info["sources"]
    since = latest_ts or None

    for src_name in sources_to_try:
        src = SOURCES.get(src_name)
        if not src:
            continue
        fetcher = src["fetch"]
        mapper = src["map"]
        mapped_sym = mapper(symbol)
        if not mapped_sym:
            continue
        # Try up to max_retries_per_source
        for attempt in range(max_retries_per_source):
            try:
                _delay(0.3, 1.0)
                rows = fetcher(mapped_sym, tf, since=since, limit=limit)
                if rows and len(rows) > 0:
                    db.upsert_candles(symbol, tf, rows, src_name)
                    cnt = len(rows)
                    log.info(
                        "fetched %s %s via %s: %d candles (mapped=%s)",
                        symbol, tf, src_name, cnt, mapped_sym
                    )
                    return True, src_name, cnt
            except Exception as e:
                log.warning(
                    "source %s failed for %s %s (attempt %d/%d): %s",
                    src_name, symbol, tf, attempt + 1, max_retries_per_source, e
                )
            if attempt < max_retries_per_source - 1:
                _delay(1.0, 2.0)
    # No source returned data
    log.warning("all sources failed for %s %s", symbol, tf)
    return False, None, 0


def fetch_all_candles(
    db: CandleDB,
    symbols: Dict[str, str],  # {symbol: class}
    tf: str,
    refresh_minutes: int = 30,
):
    """Fetch candles for all symbols at a given TF."""
    log.info("--- fetch_all_candles tf=%s symbols=%d ---", tf, len(symbols))
    results = {}
    for symbol, class_ in symbols.items():
        ok, source, count = fetch_candles_for(
            db, symbol, class_, tf, refresh_minutes=refresh_minutes
        )
        results[symbol] = {"ok": ok, "source": source, "count": count}
    ok_count = sum(1 for r in results.values() if r["ok"])
    log.info("fetch_all_candles tf=%s done: %d/%d ok", tf, ok_count, len(symbols))
    return results


# ── initial population (backfill) ──────────────────────────────────────────────

def backfill_symbol(
    db: CandleDB,
    symbol: str,
    class_: str,
    tf: str = "1d",
    max_days: int = 730,
):
    """Backfill a symbol's daily candles from the earliest available up to now.
    Uses multiple passes if needed (some APIs cap per request).
    """
    log.info("backfill %s %s %s ...", symbol, class_, tf)
    if tf not in FETCH_PARAMS:
        return
    params = FETCH_PARAMS[tf]
    limit = params["limit"]
    symbol_info = resolve_symbol(symbol, class_)
    existing = db.get_candles(symbol, tf, limit=1, min_ts=0)
    if existing:
        latest_ts = existing[-1][0]
        log.info("  existing latest: %s (%d candles total)",
                 _epoch_to_yahoo(latest_ts), db.count_candles(symbol, tf))
    else:
        latest_ts = 0
    # fetch from start
    for src_name in symbol_info["sources"]:
        src = SOURCES.get(src_name)
        if not src:
            continue
        fetcher = src["fetch"]
        mapper = src["map"]
        mapped_sym = mapper(symbol)
        if not mapped_sym:
            continue
        # Fetch in chunks until we reach now or hit a wall
        fetched_all = False
        current_since = 0
        total_new = 0
        while not fetched_all:
            _delay(0.5, 1.5)
            rows = fetcher(mapped_sym, tf, since=current_since, limit=limit)
            if not rows:
                log.warning("  %s returned no rows for %s", src_name, mapped_sym)
                break
            # Only keep rows newer than what we have
            keep = [r for r in rows if r[0] > latest_ts]
            if keep:
                db.upsert_candles(symbol, tf, keep, src_name)
                total_new += len(keep)
                latest_ts = max(r[0] for r in keep)
            # If we got fewer than limit, we probably reached the end
            if len(rows) < limit:
                fetched_all = True
            else:
                current_since = latest_ts + 1
            _delay(0.5, 1.0)
        if total_new > 0:
            log.info("  backfill %s via %s: +%d candles (total %d)",
                     symbol, src_name, total_new, db.count_candles(symbol, tf))
        if fetched_all:
            break


# ── feature compute from store ─────────────────────────────────────────────────

def compute_features_from_db(
    db: CandleDB,
    symbol: str,
    tf: str,
    limit: int = 500,
) -> Optional[Dict[str, Any]]:
    """Pull candles from DB, compute feature_vector."""
    from zeus_ta import feature_vector
    rows = db.get_candles(symbol, tf, limit=limit)
    if not rows:
        return None
    return feature_vector(rows)


def compute_features_batch(
    db: CandleDB,
    symbols: List[str],
    tf: str,
    limit: int = 500,
) -> Dict[str, Optional[Dict[str, Any]]]:
    """Compute features for a batch of symbols at one TF."""
    from zeus_ta import feature_vector
    result = {}
    for sym in symbols:
        rows = db.get_candles(sym, tf, limit=limit)
        if not rows:
            result[sym] = None
        else:
            result[sym] = feature_vector(rows)
    return result


# ── candle → Row conversion helpers ───────────────────────────────────────────

def to_row(tuple6: Tuple[int, float, float, float, float, float]) -> Row:
    return tuple6


# ── quick self-test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    db = CandleDB()
    try:
        # Register some symbols
        db.upsert_source("BTCUSDT", "crypto", "BTC", tf_map={"1h": "BTC/USDT", "1d": "BTC/USDT"})
        db.upsert_source("ETHUSDT", "crypto", "ETH", tf_map={"1h": "ETH/USDT", "1d": "ETH/USDT"})
        db.upsert_source("EURUSD=X", "forex", "EURUSD", tf_map={"1h": "EURUSD=X", "1d": "EURUSD=X"})
        db.upsert_source("SPY", "equity", "SPY", tf_map={"1h": "SPY", "1d": "SPY"})
        db.upsert_source("CL=F", "future", "CL", tf_map={"1h": "CL=F", "1d": "CL=F"})
        print("registered symbols:", db.list_symbols())

        # Try fetch BTC 1h
        ok, src, cnt = fetch_candles_for(db, "BTCUSDT", "crypto", "1h", refresh_minutes=60)
        print(f"BTCUSDT 1h: ok={ok} source={src} count={cnt}")
        if ok:
            rows = db.get_candles("BTCUSDT", "1h", limit=5)
            print(f"  latest 5: {rows[-1] if rows else None}")
            fv = compute_features_from_db(db, "BTCUSDT", "1h")
            if fv:
                print(f"  features: close={fv['close']} rsi_14={fv['rsi_14']} regime={fv['regime']} macd={fv['macd']}")

        # Try fetch ETH 1d
        ok, src, cnt = fetch_candles_for(db, "ETHUSDT", "crypto", "1d", refresh_minutes=60)
        print(f"ETHUSDT 1d: ok={ok} source={src} count={cnt}")
        if ok:
            fv = compute_features_from_db(db, "ETHUSDT", "1d")
            if fv:
                print(f"  features: close={fv['close']} rsi_14={fv['rsi_14']} regime={fv['regime']}")

        # Yahoo-based symbols
        for sym, class_, tf in [
            ("BTC-USD", "crypto", "1h"),
            ("SPY", "equity", "1d"),
            ("EURUSD=X", "forex", "1h"),
            ("CL=F", "future", "1d"),
            ("GC=F", "future", "1d"),
        ]:
            ok, src, cnt = fetch_candles_for(db, sym, class_, tf, refresh_minutes=60)
            print(f"{sym} {class_} {tf}: ok={ok} source={src} count={cnt}")
            if ok:
                fv = compute_features_from_db(db, sym, tf)
                if fv:
                    print(f"  features: close={fv['close']} rsi_14={fv['rsi_14']} regime={fv['regime']}")

        print("\nsymbol counts:")
        for sym in db.list_symbols():
            cnt1h = db.count_candles(sym, "1h") if db.symbol_exists(sym, "1h") else 0
            cnt1d = db.count_candles(sym, "1d") if db.symbol_exists(sym, "1d") else 0
            print(f"  {sym}: 1h={cnt1h} 1d={cnt1d}")
    finally:
        db.close()
