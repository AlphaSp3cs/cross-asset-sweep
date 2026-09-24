#!/usr/bin/env python3
"""Fetch BTC options from Deribit public API and compute put/call ratio."""

import urllib.request
import json
import ssl
import datetime

base = "https://www.deribit.com/api/v2/public"

def get(path, params=None):
    url = base + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return json.loads(resp.read())
    except Exception as e:
        return {"status": "error", "error": str(e)}

results = {}

# 1. Index price
r = get("/get_index_price", {"index_name": "btc_usd"})
results["index_price"] = r

# 2. Ticker (mark price)
r = get("/get_ticker", {"instrument_name": "BTC-PERPETUAL"})
results["ticker"] = r

# 3. BTC options count by type and expiry
r = get("/get_instruments", {
    "currency": "BTC",
    "kind": "option",
    "per_page": 1000,
})
results["instruments"] = r

# 4. BTC futures (for expiry calendar context)
r = get("/get_instruments", {
    "currency": "BTC",
    "kind": "future",
    "per_page": 20,
})
results["futures"] = r

print("=== Deribit API Response ===")
for key, val in results.items():
    print(f"\n--- {key} ---")
    print(json.dumps(val, indent=2)[:3000])
