# Hermes Cross-Asset Sweep — Verified Source Registry
# =====================================================
# All URLs verified working on Termux as of 2026-09-24.
# Free. No credit card. No API key required (unless noted).

## 1. CRYPTO — CoinGecko API
#    Status: ✅ LIVE — 36 coins fetched successfully
#    Rate limit: 30 req/min, no key required
#    Endpoint:
#      https://api.coingecko.com/api/v3/simple/price
#        ?ids=bitcoin,ethereum,solana,ripple,zcash,cardano,dogecoin,...
#        &vs_currencies=usd
#        &include_24hr_change=true
#        &include_market_cap=true
#        &include_24hr_vol=true
#    Returns: price, market_cap, 24h_change, 24h_vol for each coin
#    Fallback: CoinMarketCap (10k credits/mo, free key), Kraken public API

## 2. FUTURES / COMMODITIES — Yahoo Finance Chart API
#    Status: ✅ LIVE — 38/39 symbols returned data
#    Rate limit: Undocumented, seems generous
#    Endpoint:
#      https://query1.finance.yahoo.com/v8/finance/chart/{SYMBOL}
#        ?interval=1d&range=1d
#    Symbols tested and working:
#      Indices:  ES=F NQ=F YM=F RTY=F
#      Rates:    ZB=F ZN=F ZF=F ZT=F UB=F
#      Metals:   GC=F SI=F PL=F PA=F HG=F
#      Energy:   CL=F BZ=F NG=F HO=F RB=F
#      Grains:   ZC=F ZS=F ZW=F ZM=F ZL=F
#      Softs:    CT=F SB=F CC=F KC=F OJ=F
#      Meats:    LE=F GF=F HE=F
#      Forex:    6E=F 6B=F 6J=F 6S=F 6A=F 6C=F
#    Known issues:
#      - DX=F (Dollar Index) NOT working on Yahoo — use FRED DTWEXBGS or alternative
#      - JPY futures (6J=F) price shows as USD value per contract, not JPY/USD rate
#        (CME JPY is quoted JPY per USD, so price ~157 — need to invert for display)
#    Fallback: tradingcharts.com (futures.tradingcharts.com) for delayed quotes

## 3. RATES / MACRO — FRED (Federal Reserve Economic Data)
#    Status: ✅ LIVE — 10/10 series returned data
#    Rate limit: Polite — add 0.3s between requests
#    Endpoint (CSV, no key):
#      https://fred.stlouisfed.org/graph/fredgraph.csv?id={SERIES_ID}
#    Series verified:
#      DGS10    = 10Y Treasury Yield      ✅ Latest: 4.96 (Sep 22)
#      DGS2     = 2Y Treasury Yield       ✅ Latest: 4.71 (Sep 22)
#      DGS30    = 30Y Treasury Yield      ✅ Latest: 5.29 (Sep 22)
#      DGS5     = 5Y Treasury Yield       ✅ Latest: 4.83 (Sep 22)
#      DGS7     = 7Y Treasury Yield       ✅ Latest: 4.89 (Sep 22)
#      BAMLH0A0HYM2   = ICE BofA HY OAS    ✅ Latest: 2.68 (Sep 22)
#      BAMLC0A0CMEY   = ICE BofA IG OAS    ✅ Latest: 5.69 (Sep 22)
#      SOFR     = Secured Overnight Rate  ✅ Latest: 3.87 (Sep 22)
#      EFFR     = Effective Fed Funds     ✅ Latest: 3.88 (Sep 22)
#      VIXCLS   = CBOE VIX                ⚠️  FRED has 1-2 DAY LAG — uses Yahoo ^VIX for current
#    IMPORTANT — VIX IS REAL-TIME NOW:
#      FRED VIXCLS has 1-2 day lag (Sep 22 data on Sep 24). The script now
#      fetches ^VIX from Yahoo Finance for the current reading (e.g. 16.35).
#      This overrides FRED VIXCLS in the output automatically.
#      Yahoo endpoint: https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX
#    Removed series:
#      DXY      = ICE US Dollar Index     ❌ Not on FRED as "DXY"
#      T10Y2Y   = 10Y-2Y Spread           ❌ Calculate manually: DGS10 - DGS2
#      T5Y2Y    = 5Y-2Y Spread            ❌ Calculate manually: DGS5 - DGS2
#    Alternative for DXY (if needed):
#      - FRED DTWEXBGS = Nominal Broad Dollar Index (correlated proxy)
#      - Stooq: https://stooq.com/q/?s=usdindex
#    For REAL-TIME yields (intraday), Treasury.gov has delayed data.
#    FRED is acceptable for end-of-day sweeps.

## 4. OPTIONS GAMMA — algoxflow.com
#    Status: ✅ LIVE — SPY, QQQ, IWM, TLT all returned data
#    Rate limit: Undocumented, free, no key, CORS open
#    Endpoint:
#      https://algoxflow.com/api/gexmap?ticker={SYMBOL}
#    Returns: spot, regime (positive/negative gamma), gamma_flip,
#             callWall, putWall, maxPain, totalGex, expMove, expMovePct
#    Symbols tested: SPY, QQQ, IWM, TLT — all working
#    Caveat: Snapshot capped at 250 contracts per call — flip can shift on wide chains
#    Fallback: zer0dte.trade (MCP, free beta 3 sessions/day, SPX 0DTE focus)
#             FlashAlpha (free tier, API key required, ES/NQ futures + 6000+ equities)

## 5. BTC ETF FLOWS — Farside Investors
#    Status: ✅ LIVE — daily flows returned
#    Rate limit: Unknown, free
#    Endpoint:
#      https://farside.co.uk/btc          (BTC ETF flows by provider)
#      https://farside.co.uk/eth/         (ETH ETF flows)
#      https://farside.co.uk/bitcoin-futures/  (BTC options from Deribit)
#    Returns: HTML table — parse with regex for latest row
#    Coverage: IBIT, FBTC, BITB, ARKB, BTCO, EZBC, BRRR, HODL, BTCW, MSBT, GBTC, BTC
#    Gap: Only crypto ETFs. No free source for SPY/QQQ/IWM daily flows.

## 6. INTERNATIONAL EQUITIES — Free sources
#    Status: Not yet integrated into sweep script — available for future expansion
#    Source options:
#      Twelve Data: 190k stocks, 250+ exchanges, 800 req/day free
#        → https://twelvedata.com/stocks (API key required, free tier)
#      Alpha Vantage: stocks, ETFs, forex, crypto, fundamentals
#        → https://alphavantage.co (API key required, 25 req/day free)
#      Finnhub: real-time prices, fundamentals, news
#        → https://finnhub.io (free tier: 60 calls/min)
#      London Strategic Edge: 18,694 series, 220 countries, free Parquet/CSV
#        → https://londonstrategicedge.com (free API key, no credit card)
#      Yahoo Finance: international indices delayed
#        → https://finance.yahoo.com/markets/stocks/

## 7. EMERGING MARKET CURRENCIES — Free sources
#    Status: Not yet integrated — available for future expansion
#    Source options:
#      Bank of China: 40+ currencies, buying/selling/middle rates, 2x daily
#        → https://www.bankofchina.com/sourcedb/whpj/enindex_1619.html
#      BSP (Philippines Central Bank): 32 currencies vs USD/EUR/PHP, daily
#        → https://www.bsp.gov.ph/sitepages/statistics/exchangerate.aspx
#      ECB Reference Rates: 30+ currencies vs EUR, daily
#        → https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates
#      Banque de France: daily parities, 30+ currencies
#        → https://www.banque-france.fr/en/statistics/rates-and-prices/exchange-rates-daily-parities
#      ExchangeRates.org.uk: rates + forecasts, 30+ pairs
#        → https://www.exchangerates.org.uk
#      Twelve Data / Alpha Vantage: forex API (G10 + some EM)

## 8. BROADER COMMODITIES — Beyond the futures sweep
#    Status: Yahoo Finance covers major futures; TradingEconomics covers everything else
#    Yahoo Finance futures (already in sweep): ES, NQ, YM, RTY, ZB, ZN, ZF, ZT, UB,
#      GC, SI, PL, PA, HG, CL, BZ, NG, HO, RB, ZC, ZS, ZW, ZM, ZL, CT, SB, CC, KC, OJ,
#      LE, GF, HE, 6E, 6B, 6J, 6S, 6A, 6C
#    TradingEconomics (free, web): Comprehensive commodity list including:
#      Energy: crude, brent, nat gas, gasoline, heating oil, coal, EU gas, UK gas,
#        ethanol, naphtha, propane, uranium, LNG JKM, Urals oil
#      Agriculture: soybeans, wheat, corn, lumber, palm oil, cheese, milk, rubber,
#        orange juice, coffee, cotton, rice, canola, oats, wool, sugar, cocoa, tea,
#        sunflower oil, rapeseed, barley, butter
#      Industrial: aluminum, copper, nickel, zinc, lead, tin, cobalt, molybdenum,
#        palladium, rhodium, lithium, gallium, germanium, indium, manganese, tellurium,
#        neodymium, etc.
#      Livestock: feeder cattle, live cattle, lean hogs, beef, poultry, eggs (US+China), salmon
#    URL: https://tradingeconomics.com/commodities
#    Gap: No API — web only. Intraday prices require paid source.

## 9. BTC OPTIONS (Deribit) — for expiry analysis
#    Status: Available via Farside, not yet integrated
#    Source:
#      Farside: https://farside.co.uk/bitcoin-futures/
#        → BTC options: call/put OI, volume, volatility (from Deribit)
#      Deribit public API: https://www.deribit.com/api/v2/public/
#        → Get option chain, open interest, IV for BTC/ETH options
#    Gap: Need to parse Deribit API for full option chain analysis.
#    The $16B BTC options expiry (Sep 25) thesis needs Deribit data for verification.

## KNOWN GAPS (no free solution)
#  - Real-time Level 2 / order book depth (stocks): Paid only (Polygon, Alpaca, etc.)
#  - Broad equity ETF daily flows (SPY, QQQ, IWM): No free source — infer from price/volume
#  - Credit Default Swap (CDS) indices (CDX, iTraxx): Paid (Bloomberg, Markit)
#  - Real-time European/Asian equities: Most free sources are EOD/delayed
#  - EM FX intraday rates: Central bank fixings only; intraday is paid (Bloomberg, Reuters)
#  - Structured news sentiment/NLP: Paid (Bloomberg, RavenPack)
#  - ICE US Dollar Index (DXY) exactly: Not free in real-time; use DTWEXBGS (FRED) as proxy
#  - Binance API on Termux: Known timeout issue (curl exit 23). Use CoinGecko/Kraken instead.

## QUICK RECOVERY — If any source goes down
#  CoinGecko fails       → CoinMarketCap (free key) or Kraken public API
#  Yahoo Finance fails   → tradingcharts.com (delayed) or Investing.com
#  FRED fails            → Treasury.gov direct (home.treasury.gov) for yields
#                         NY Fed direct (newyorkfed.org) for SOFR/EFFR
#  algoxflow fails       → zer0dte.trade (MCP, SPX 0DTE) or FlashAlpha (free tier)
#  Farside fails         → No alternative for free BTC ETF flows
#  Any source rate-limited → Add delays between requests, cache results locally
