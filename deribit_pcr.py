#!/usr/bin/env python3
"""Deribit BTC Options — precise Put/Call Ratio from live OI data."""

import urllib.request, json
from collections import defaultdict

base = "https://www.deribit.com/api/v2/public"

def get(path, params):
    url = base + path + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read())

opts = get("/get_instruments", {
    "currency": "BTC", "kind": "option",
    "per_page": 1000, "include_open_interest": True,
})["result"]

print(f"Deribit BTC Options — {len(opts)} instruments (live)")
print()

calls = [o for o in opts if o.get("option_type") == "call" and o.get("state") == "open"]
puts = [o for o in opts if o.get("option_type") == "put" and o.get("state") == "open"]

call_oi = sum((o.get("open_interest") or 0) for o in calls)
put_oi = sum((o.get("open_interest") or 0) for o in puts)
call_vol = sum((o.get("total_quantity") or 0) for o in calls)
put_vol = sum((o.get("total_quantity") or 0) for o in puts)

print(f"Calls: {len(calls)} contracts | OI: {call_oi:,.0f} units | Vol: {call_vol:,.0f}")
print(f"Puts:  {len(puts)} contracts | OI: {put_oi:,.0f} units | Vol: {put_vol:,.0f}")

total_oi = call_oi + put_oi
if total_oi > 0:
    print(f"\nTotal Open Interest: {total_oi:,.0f} BTC-USD option units")

if call_oi > 0:
    pc_oi = put_oi / call_oi
    label = "BEARISH (puts heavy)" if pc_oi > 1.2 else "BULLISH (calls heavy)" if pc_oi < 0.8 else "NEUTRAL"
    print(f"\n>>> P/C OI RATIO: {pc_oi:.4f}  [{label}]")
    print(f"    {put_oi:,.0f} puts / {call_oi:,.0f} calls")
else:
    print("\n>>> P/C OI RATIO: N/A (no call OI)")

if call_vol > 0:
    pc_vol = put_vol / call_vol
    vlabel = "BEARISH flow" if pc_vol > 1.2 else "BULLISH flow" if pc_vol < 0.8 else "NEUTRAL flow"
    print(f"\n>>> P/C VOLUME RATIO: {pc_vol:.4f}  [{vlabel}]")
    print(f"    {put_vol:,.0f} put contracts / {call_vol:,.0f} call contracts")
else:
    print("\n>>> P/C VOLUME RATIO: N/A (no call volume)")

# By expiry breakdown
print()
print("By Expiry:")
print(f"  {'Expiry':<10} {'#C':>5} {'#P':>5} {'Call OI':>12} {'Put OI':>12} {'P/C OI':>8} {'→':>4}")
for exp in sorted(set(o.get("instrument_name", "").split("-")[1] for o in opts if o.get("state") == "open")):
    e_calls = [o for o in calls if o.get("instrument_name","").split("-")[1] == exp]
    e_puts = [o for o in puts if o.get("instrument_name","").split("-")[1] == exp]
    e_co = sum((o.get("open_interest") or 0) for o in e_calls)
    e_po = sum((o.get("open_interest") or 0) for o in e_puts)
    pc = e_po / e_co if e_co > 0 else 0
    flag = "←" if pc > 1.2 else ("→" if pc < 0.8 else "")
    print(f"  {exp:<10} {len(e_calls):>5} {len(e_puts):>5} {e_co:>12,.0f} {e_po:>12,.0f} {pc:>8.4f} {flag:>4}")

print()
# Nearest expiry detail
nearest = sorted(set(o.get("instrument_name","").split("-")[1] for o in opts if o.get("state")=="open"))[0]
e_calls = [o for o in calls if o.get("instrument_name","").split("-")[1] == nearest]
e_puts = [o for o in puts if o.get("instrument_name","").split("-")[1] == nearest]
print(f"  Nearest expiry ({nearest}):")
n_co = sum((o.get("open_interest") or 0) for o in e_calls)
n_po = sum((o.get("open_interest") or 0) for o in e_puts)
print(f"    P/C OI: {n_po/n_co:.4f} | Calls: {n_co:,.0f} | Puts: {n_po:,.0f}")
top_calls = sorted(set(o.get("strike") for o in e_calls), reverse=True)[:5]
top_puts = sorted(set(o.get("strike") for o in e_puts))[:5]
print(f"    Top call strikes: {', '.join(f'${s:,.0f}' for s in top_calls)}")
print(f"    Top put strikes:  {', '.join(f'${s:,.0f}' for s in top_puts)}")
