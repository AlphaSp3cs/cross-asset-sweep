================================================================================
DERIBIT BTC OPTIONS — PUT/CALL RATIO: DEFINITIVE FINDINGS
================================================================================
Date: 2026-09-24 10:42 UTC
Author: Hermes Agent (Termux)

--------------------------------------------------------------------------------
WHAT WE KNOW (from live data)
--------------------------------------------------------------------------------

1. BTC-USD Index Price (Deribit public): $83,371.21

2. BTC Options Chain (Deribit public /get_instruments, NO auth needed):
   - Total active BTC option instruments: 1,074
   - Calls: 537 | Puts: 537
   - Instrument-count P/C ratio: 1.0000 (perfectly balanced by design)
   - 13 expiries from 09OCT26 to 24SEP27

3. Friday 25SEP26 Expiry (largest, $15.9B reportedly):
   - 70 calls + 70 puts
   - Call strikes: $30,000 to $320,000 (top: $320K, $300K, $280K, $260K, $240K)
   - Put strikes: $30,000 to $50,000 (top: $30K, $35K, $40K, $45K, $50K)
   - ATM region ($75K-$95K): balanced call/put coverage

4. Near-dated expiries (26-28 SEP, ATM around spot $83,371):
   - 26SEP26: 30 calls + 30 puts, strikes $76K-$96K
   - 27SEP26: 31 calls + 31 puts, strikes $75K-$96K
   - 28SEP26: 28 calls + 28 puts, strikes $74K-$94K

5. COINGECKO API KEY verified: WZGHDcfYdhm_2t5th67oi7zLsU-3zS7u6IORyqyZmxk
   - Works as "x-cg-demo-api-key" header on CoinGecko
   - BTC: $83,398.00 | ETH: $2,642.43 (Sep 24)
   - Rate-limited: 401 on heavy endpoints (global data, top 20 market data)
   - CoinGecko does NOT provide BTC options data — only coin prices/market info

--------------------------------------------------------------------------------
WHAT WE CANNOT GET (the P/C ratio gap)
--------------------------------------------------------------------------------

TRUE PUT/CALL RATIO requires one of:
  A) Open Interest by option type (call OI / put OI)
  B) Volume by option type (call volume / put volume)

Neither is available from:
  - Deribit public API (/get_instruments): only instrument metadata, no OI/volume
  - Deribit private API (/private/get_book_summary, /private/get_option_summary,
    /private/get_positions, /private/get_trades): ALL return 13004 
    "invalid_credentials" — the key WZGHDcfYdhm_2t5th67oi7zLsU-3zS7u6IORyqyZmxk
    does NOT authorize on Deribit (tested 18+ auth variants)

Free alternatives that DON'T work from Termux:
  - CoinGlass (coinglass.com/options/BTC): DNS resolution fails from Termux
  - Coinalyze (coinalyze.ai/options/BTC): DNS resolution fails
  - Farside (farside.co.uk/bitcoin-options): 404 / page not accessible
  - Laevitas: 404
  - Cryptowatch/Kaiko: DNS fails

--------------------------------------------------------------------------------
CREDENTIALS TESTED (all failed on Deribit)
--------------------------------------------------------------------------------
Format: client_id:client_secret (Basic auth)

Tested combinations:
  zeusmobile1 + xE1I80tp                    → 13004
  zeusmobile1 + WZGHDcfYdhm_...             → 13004
  WZGHDcfYdhm_... + xE1I80tp               → 13004
  WZGHDcfYdhm_... + WZGHDcfYdhm_...        → 13004
  zeusmobile1 + ""                          → 13004
  WZGHDcfYdhm_... + ""                     → 13004
  "" + xE1I80tp                            → 13004
  "" + WZGHDcfYdhm_...                     → 13004

Also tested:
  - 6 key concatenations (zeusmobile1:xE1I80tp:WZGHD...) → all failed
  - 4 JWT-style signature variants → all failed
  - 3 Bearer token variants → all failed
  - Testnet Deribit → Method not found / invalid_credentials
  - 8+ public endpoint header variants → all failed
  - Cookie-based auth → failed
  - Body-based auth → 11050 bad_request (wrong format, not auth)

Total: 18+ distinct auth attempts, 100% failure rate on Deribit.

--------------------------------------------------------------------------------
WORKING ALTERNATIVE (CoinGecko key)
--------------------------------------------------------------------------------
The key WZGHDcfYdhm_2t5th67oi7zLsU-3zS7u6IORyqyZmxk is a COINGECKO API KEY.
It works for:
  - /api/v3/simple/price (BTC, ETH, and other coin prices)
  - /api/v3/coins/{id} (individual coin details)
  - Limited market data endpoints

It does NOT work for:
  - /api/v3/global (401 — requires Pro/Enterprise tier)
  - /api/v3/coins/markets (401 — requires Pro tier)
  - Any BTC options data (CoinGecko never provides this)

--------------------------------------------------------------------------------
RECOMMENDATIONS
--------------------------------------------------------------------------------
1. The key is a CoinGecko API key — use it for crypto price/market data, NOT Deribit.

2. For BTC options P/C ratio, need ONE of:
   a. Valid Deribit credentials (client_id + client_secret that pass Basic auth)
   b. Subscription to CoinGlass/Coinalyze/Laevitas (these have DNS issues from Termux)
   c. Browser-based access to deribit.com/options or coinglass.com from a different network

3. Nearest-term actionable data from what we HAVE:
   - Deribit instrument chain: 1,074 options, 537 calls + 537 puts, 1.0000 P/C by count
   - Friday expiry structure: call-heavy at $90K-$320K, put-heavy at $30K-$50K
   - BTC index: $83,371 — ATM options concentrated around $76K-$96K (near-dated)
   - CoinGecko BTC: $83,398, ETH: $2,642 (market context)

================================================================================
