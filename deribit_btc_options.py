#!/usr/bin/env python3
"""Deribit BTC Options — Put/Call Ratio Calculator & Chain Summary."""

import urllib.request, json, ssl, datetime, sys
from collections import defaultdict

base = "https://www.deribit.com/api/v2/public"

def get(path, params=None):
    url = base + path
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"status": "error", "error": str(e)}

def main():
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    print("╔" + "═" * 76 + "╗")
    print(f"║  DERIBIT BTC OPTIONS — PUT/CALL RATIO & CHAIN SUMMARY  ║ {now_utc.strftime('%Y-%m-%d %H:%M UTC')}")
    print("╚" + "═" * 76 + "╝")
    print(f"  Index Price (BTC-USD): {get('/get_index_price', {'index_name':'btc_usd'})['result']['index_price']:,.2f}")
    print()

    # Fetch BTC options — paginate
    all_opts = []
    cursor = None
    page = 0
    while True:
        params = {"currency": "BTC", "kind": "option", "per_page": 1000, "include_open_interest": True}
        if cursor:
            params["after"] = cursor
        r = get("/get_instruments", params)
        if r.get("status") == "error":
            print(f"  ERROR on page {page+1}: {r.get('error')}")
            break
        items = r.get("result", [])
        if not items:
            break
        all_opts.extend(items)
        cursor = items[-1].get("instrument_id")
        page += 1
        print(f"  Page {page}: {len(items)} instruments (cumulative: {len(all_opts)})")
        if len(items) < 1000 or page >= 5:
            break

    print(f"\n  Total BTC option instruments: {len(all_opts)}")
    print()

    # Group by expiry and type
    buckets = defaultdict(lambda: {"call": [], "put": [], "call_oi": 0, "put_oi": 0, "call_vol": 0, "put_vol": 0})

    for opt in all_opts:
        if opt.get("state") != "open" or not opt.get("is_active"):
            continue
        name = opt.get("instrument_name", "")
        otype = opt.get("option_type", "")
        if otype not in ("call", "put"):
            continue
        # Decode expiry from name: BTC-25SEP26-XXXXX-C/P
        try:
            parts = name.split("-")
            expiry_str = parts[1]  # e.g. "25SEP26"
            strike = float(parts[2])
            typ = parts[3]  # C or P
        except (IndexError, ValueError):
            continue

        ts = opt.get("expiration_timestamp", 0)
        try:
            dt = datetime.datetime.fromtimestamp(ts / 1000, tz=datetime.timezone.utc)
            expiry_date = dt.strftime("%d%b%y").upper()
        except:
            expiry_date = expiry_str

        oi = opt.get("open_interest") or 0
        vol = opt.get("total_quantity") or 0

        buckets[expiry_date]["call" if typ == "C" else "put"].append(opt)
        if typ == "C":
            buckets[expiry_date]["call_oi"] += oi
            buckets[expiry_date]["call_vol"] += vol
        else:
            buckets[expiry_date]["put_oi"] += oi
            buckets[expiry_date]["put_vol"] += vol

    total_call_oi = sum(b["call_oi"] for b in buckets.values())
    total_put_oi = sum(b["put_oi"] for b in buckets.values())
    total_call_vol = sum(b["call_vol"] for b in buckets.values())
    total_put_vol = sum(b["put_vol"] for b in buckets.values())

    print("╔" + "═" * 76 + "╗")
    print("║  BTC OPTIONS — PUT/CALL RATIOS (Open Interest + Volume)  ║")
    print("╚" + "═" * 76 + "╝")
    print()
    print(f"  {'Expiry':<10} {'Strike Range':<16} {'#C':>4} {'#P':>4} {'Call OI':>12} {'Put OI':>12} {'P/C OI':>8} {'Call Vol':>11} {'Put Vol':>11} {'P/C Vol':>8}")
    print(f"  {'─'*10} {'─'*16} {'─'*4} {'─'*4} {'─'*12} {'─'*12} {'─'*8} {'─'*11} {'─'*11} {'─'*8}")

    expiry_order = sorted(buckets.keys())
    for ep in expiry_order:
        b = buckets[ep]
        n_calls = len(b["call"])
        n_puts = len(b["put"])
        call_oi = b["call_oi"]
        put_oi = b["put_oi"]
        call_vol = b["call_vol"]
        put_vol = b["put_vol"]

        p_c_oi = put_oi / call_oi if call_oi > 0 else f"{'∞' if put_oi > 0 else 'N/A':>8}"
        p_c_vol = put_vol / call_vol if call_vol > 0 else f"{'∞' if put_vol > 0 else 'N/A':>8}"

        strikes = [float(o.get("strike", 0)) for o in b["call"] + b["put"]]
        strike_range = f"${min(strikes):,.0f}-${max(strikes):,.0f}" if strikes else "N/A"

        oi_str = f"{call_oi:>12,.0f}" if call_oi > 0 else "N/A"
        po_oi_str = f"{put_oi:>12,.0f}" if put_oi > 0 else "N/A"
        cv_str = f"{call_vol:>11,.0f}" if call_vol > 0 else "N/A"
        pv_str = f"{put_vol:>11,.0f}" if put_vol > 0 else "N/A"
        pc_oi_s = f"{p_c_oi:>8.2f}" if isinstance(p_c_oi, float) else str(p_c_oi)
        pc_vol_s = f"{p_c_vol:>8.2f}" if isinstance(p_c_vol, float) else str(p_c_vol)

        print(f"  {ep:<10} {strike_range:<16} {n_calls:>4} {n_puts:>4} {oi_str} {po_oi_str} {pc_oi_s} {cv_str} {pv_str} {pc_vol_s}")

    print(f"  {'─'*10} {'─'*16} {'─'*4} {'─'*4} {'─'*12} {'─'*12} {'─'*8} {'─'*11} {'─'*11} {'─'*8}")
    total_oi_str = f"{total_call_oi+total_put_oi:>12,.0f}"
    print(f"  {'TOTAL':<10} {'ALL':<16} {sum(len(b['call']) for b in buckets.values()):>4} {sum(len(b['put']) for b in buckets.values()):>4} {total_call_oi:>12,.0f} {total_put_oi:>12,.0f} {total_put_oi/total_call_oi:>8.2f} {total_call_vol:>11,.0f} {total_put_vol:>11,.0f} {total_put_vol/total_call_vol:>8.2f}")

    print()
    print("━━━ KEY TAKEAWAYS ━━━")
    if total_call_oi > 0:
        ratio = total_put_oi / total_call_oi
        label = "BEARISH" if ratio > 1.2 else "BULLISH" if ratio < 0.8 else "NEUTRAL"
        print(f"  • Total P/C OI Ratio: {ratio:.3f} ({label}) — {total_put_oi:,.0f} puts vs {total_call_oi:,.0f} calls")
    else:
        print(f"  • Total P/C OI Ratio: N/A (no open interest data)")

    if total_call_vol > 0:
        vratio = total_put_vol / total_call_vol
        vlabel = "BEARISH" if vratio > 1.2 else "BULLISH" if vratio < 0.8 else "NEUTRAL"
        print(f"  • Total P/C Volume Ratio: {vratio:.3f} ({vlabel}) — {total_put_vol:,.0f} put contracts vs {total_call_vol:,.0f} call contracts traded")
    else:
        print(f"  • Total P/C Volume Ratio: N/A (no volume data)")

    if expiry_order:
        nearest = expiry_order[0]
        b = buckets[nearest]
        print(f"  • Nearest expiry ({nearest}): {len(b['call'])} calls, {len(b['put'])} puts")
        if b["call_oi"] > 0:
            print(f"    P/C OI: {b['put_oi']/b['call_oi']:.3f} | Calls: {b['call_oi']:,.0f} | Puts: {b['put_oi']:,.0f}")
            print(f"    Top call strikes: {', '.join(f'${s:,.0f}' for s in sorted(set(opt['strike'] for opt in b['call']), reverse=True)[:5])}")
            print(f"    Top put strikes: {', '.join(f'${s:,.0f}' for s in sorted(set(opt['strike'] for opt in b['put']))[:5])}")

    print(f"\n  Data: {len(all_opts)} instruments fetched from Deribit public API")
    print(f"  Index: {get('/get_index_price', {'index_name':'btc_usd'})['result']['index_price']:,.2f} BTC-USD")
    print(f"  Free source — no API key required")

if __name__ == "__main__":
    main()
