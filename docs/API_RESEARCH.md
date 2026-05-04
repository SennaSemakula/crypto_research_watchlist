# API_RESEARCH

Free / generous-free-tier crypto data APIs evaluated for wiring into the
v1 stack. Companion to `RESEARCH.md` (which covers the architecture and
the why); this doc covers the what (per-API specifics, rate limits,
client libraries, gotchas) and the how (recommended wiring per stub).

Last reviewed: 2026-05-02. Author: Claude Code (Senna delegated full autonomy).

Universe (10 names): BTC, ETH, SOL, BNB, XRP, ADA, AVAX, LINK, DOT, MATIC.
Cadence: daily routines, hourly intraday. UK-based operator (FCA matters).

---

## 1. Per-API entries

Every entry follows the same shape: what it is / free scope / auth /
rate limits / Python client / reliability / gotchas / verdict.

### 1.1 CCXT (multi-exchange unified library)

**What.** Python library wrapping the public REST + WebSocket APIs of
~108 exchanges with a unified method surface (`fetch_ohlcv`,
`fetch_funding_rate`, `fetch_funding_rate_history`,
`fetch_open_interest_history`, etc.). Already imported in
`ccxt_provider.py`. The single most important dependency in the v1 stack.

**Free scope.** All public endpoints across all listed exchanges. Spot
OHLCV is universal. Perp funding rates and open interest depend on the
exchange implementation:
- `fetch_funding_rate(symbol)` works on Binance, Bybit, OKX, Gate.io,
  Hyperliquid, Bitget. Returns the latest 8h rate plus next-funding
  timestamp.
- `fetch_funding_rate_history(symbol, limit)` works reliably on Binance
  USDM perps and Bybit V5. Patchier on Gate.io (issue #24275) and
  Hyperliquid honours `limit` inconsistently (issue #24144).
- `fetch_open_interest_history(symbol, timeframe, limit)` works on
  Binance USDM and OKX. Bybit returns OI but with a different shape;
  ccxt normalises it.
- Liquidations: no unified `fetch_liquidations` for historical data.
  WebSocket streams (`watchLiquidations`) require ccxt.pro.

**Auth.** None for public endpoints. API keys only needed for trading.

**Rate limits.** Inherited from each exchange. ccxt's `enableRateLimit:
True` self-throttles to the exchange's published limit (already set in
`ccxt_provider.py`). For our cadence (10 symbols x hourly = 240
calls/hour) this is not a concern.

**Python client.** `ccxt` on PyPI, latest 4.x as of 2026-04-20. Install
`ccxt`. Async variant is `ccxt.async_support` (free); WebSocket / pro
variant is `ccxt.pro` and is paid (commercial license).

**Reliability.** Mature project, ~10 years old, broad community use.
Breaking changes are common at major versions; pin the version. Binance
and Bybit are the two most-tested exchanges through ccxt; Coinbase via
ccxt has historically had quirks (issue #21226, #22571).

**Gotchas.**
- Symbol translation: yfinance form (`BTC-USD`) -> ccxt form (`BTC/USDT`)
  for Binance because Binance has no spot USD pairs. The translation is
  already in `to_ccxt_symbol()`; verify per-exchange when you swap.
- `fetch_ohlcv` with no `since` defaults to recent bars only. To backfill,
  loop with explicit `since` timestamps.
- `binanceusdm` vs `binance`: spot lives on `binance`, perp funding /
  OI live on `binanceusdm`. Already split correctly in the provider.
- ccxt.pro (WebSocket) is paid; do not depend on it in v1.
- UK access: Binance.com REST endpoints are reachable from UK IPs for
  read-only public data. Trading auth from UK retail is restricted, but
  read-only is fine.

**Verdict.** Recommended for v1. Foundation of spot / funding / OI.

Source: [ccxt PyPI](https://pypi.org/project/ccxt/),
[ccxt GitHub](https://github.com/ccxt/ccxt),
[issue #24144](https://github.com/ccxt/ccxt/issues/24144),
[issue #24275](https://github.com/ccxt/ccxt/issues/24275).

### 1.2 Binance public API (spot + USDM futures)

**What.** Direct REST API at `api.binance.com` (spot) and `fapi.binance.com`
(USD-margined perps). Authoritative source for the deepest perp book in
crypto; ccxt is a wrapper around this for our purposes. Worth knowing the
raw endpoints in case of ccxt regressions.

**Free scope (relevant endpoints).**
- `GET /api/v3/klines`: spot OHLCV, max 1000 bars per call.
- `GET /fapi/v1/klines`: perp OHLCV.
- `GET /fapi/v1/fundingRate`: funding rate history. Up to 1000 entries,
  filter by `symbol`, `startTime`, `endTime`. Shares a 500/5min/IP weight
  bucket with `fundingInfo`.
- `GET /fapi/v1/openInterest`: current OI snapshot.
- `GET /futures/data/openInterestHist`: historical OI by interval (5m,
  15m, 30m, 1h, 2h, 4h, 6h, 12h, 1d), max 500 bars per call. IP-rate-
  limited at 1000/5min.
- `GET /fapi/v1/allForceOrders`: public force-order (liquidation)
  history. Note: Binance has progressively gutted this endpoint; in
  practice only the WebSocket stream `forceOrder@arr` is reliable for
  liquidations.
- WebSocket: `!forceOrder@arr` (all-symbol liquidation stream),
  `<symbol>@forceOrder` (per-symbol).

**Auth.** None for the listed endpoints.

**Rate limits.** Per-IP weight system. Default 6000 weight per minute
on `fapi`. Each endpoint costs 1-10 weight. At our cadence we are
nowhere near the cap.

**Python client.** `binance-futures-connector-python` (official, but
sparsely maintained), or hit endpoints with `httpx`/`requests` directly.
Through ccxt is the path of least resistance.

**Reliability.** Industry standard; uptime is high. Endpoints occasionally
get deprecated with limited notice; track the
[Binance change log](https://developers.binance.com/docs/derivatives/change-log).

**Gotchas.**
- UK retail: derivatives trading on Binance.com is restricted post-2023
  FCA action, but read-only public endpoints are not geo-blocked.
- Binance.US (binance.us) is a separate exchange with a thinner book and
  different symbols; do not confuse the two.
- `allForceOrders` is unofficially deprecated for non-account-holders.
  Treat liquidation REST as unavailable; use the WebSocket if you need it.
- Funding rate is per-perp, not per-spot. Symbol form: `BTCUSDT` (no
  slash, no hyphen).

**Verdict.** Recommended for v1, accessed via ccxt. Direct REST as a
fallback if ccxt regresses.

Source: [Binance USDS-M Funding History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History),
[Binance OI Stats](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Open-Interest-Statistics),
[Binance liquidation streams](https://developers.binance.com/docs/derivatives/usds-margined-futures/websocket-market-streams/Liquidation-Order-Streams),
[Binance change log](https://developers.binance.com/docs/derivatives/change-log).

### 1.3 Coinbase Advanced Trade public API

**What.** REST API for Coinbase's flagship exchange. The intended live-
execution venue per `RESEARCH.md` section 5. Spot-only.

**Free scope.**
- `GET /api/v3/brokerage/market/products`: public product list.
- `GET /api/v3/brokerage/market/products/{product_id}/candles`: public
  candles. UNAUTHENTICATED in 2026 per the public-candles endpoint, but
  v3 historically required auth for some candle ranges. Test both before
  shipping.
- `GET /api/v3/brokerage/market/products/{product_id}/ticker`: last trade.
- No perp data: Coinbase International (Bermuda entity) hosts perps but
  is not part of the Advanced Trade API and is geo-blocked from the UK.

**Auth.** Public market data: none in 2026 (`market/` namespace).
Account/order endpoints: ECDSA-signed JWT (CDP keys) - not relevant for
v1 read-only.

**Rate limits.** Public endpoints share a tighter bucket than authenticated
ones (Coinbase explicitly recommends signing requests if possible). The
exact public limit is undocumented but anecdotally ~10/sec/IP. Easily
within budget for daily polls.

**Python client.** `coinbase-advanced-py` (official, PyPI). ccxt also
covers Coinbase but with documented quirks.

**Reliability.** Strong; Coinbase is one of the highest-uptime venues.
The Advanced Trade API replaced the legacy Pro / Exchange APIs; older
docs still floating around the web are stale.

**Gotchas.**
- v2 vs v3: v2 (`api.coinbase.com/v2/`) is the consumer Coinbase API
  (price tickers, simple). v3 (`/api/v3/brokerage/`) is Advanced Trade.
  Use v3.
- USD-quoted pairs natively (BTC-USD, ETH-USD, etc.). No symbol mapping
  pain, unlike Binance.
- No MATIC-USD historically; Coinbase listed POL after the Polygon
  rebrand. Use POL-USD on Coinbase, alias to MATIC in our universe.
- UK-friendly: Coinbase is FCA-registered for UK retail.

**Verdict.** Recommended for v1 as a fallback / cross-check for spot
OHLCV, especially for symbols where the Binance USDT pair has tracking
error vs the USD pair. Primary execution venue in a future live phase.

Source: [Coinbase Advanced Trade overview](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/overview),
[Get public candles](https://docs.cloud.coinbase.com/advanced-trade/docs/apis/get-public-candles).

### 1.4 Kraken public REST

**What.** Long-standing UK-friendly exchange with public OHLC, ticker,
order book, and trade endpoints.

**Free scope.**
- `GET /0/public/OHLC?pair=XBTUSD&interval=1440`: daily candles, max
  720 bars per call.
- `GET /0/public/Ticker`, `Depth`, `Trades`, `Spread`.
- No futures: Kraken Futures has a separate API (`futures.kraken.com`)
  with its own funding rate endpoint, but the volume is a fraction of
  Binance/Bybit so it's not the primary funding source.

**Auth.** None for public endpoints.

**Rate limits.** Per-IP-per-pair, soft; Kraken support says 1/sec is safe.
Rate limit headers are not exposed; you find out by hitting `EAPI:Rate
limit exceeded`.

**Python client.** `krakenex` (official), `python-kraken-sdk`, ccxt.

**Reliability.** Solid uptime; older API versions are kept around.

**Gotchas.**
- BTC is `XBT` on Kraken, BCH is `BCH`, weird altname rules
  (`XXBTZUSD` etc): use the `wsname` field to map.
- 720-bar limit on OHLC means full backfill needs pagination via
  `since` in nanoseconds.
- Listed altcoin coverage is good but not comprehensive (e.g. some
  smaller alts in our universe are USD-pair-only on certain dates).

**Verdict.** Fallback for v1. Primary fallback for UK-execution
considerations and as a tertiary spot source.

Source: [Kraken OHLC endpoint](https://docs.kraken.com/api/docs/rest-api/get-ohlc-data/),
[Kraken rate limits](https://support.kraken.com/articles/206548367-what-are-the-api-rate-limits-).

### 1.5 Bybit V5 public

**What.** Bybit is the second-deepest perp venue after Binance and often
has cleaner funding-rate history coverage. V5 is the unified API.

**Free scope.**
- `GET /v5/market/funding/history?category=linear&symbol=BTCUSDT`:
  per-symbol funding rate history. No auth.
- `GET /v5/market/open-interest?category=linear&symbol=BTCUSDT&intervalTime=1d`:
  OI history with intervals 5min/15min/30min/1h/4h/1d.
- `GET /v5/market/kline`: perp OHLCV.
- `GET /v5/market/recent-trade`, `tickers`, `orderbook`.

**Auth.** None for `/market/*`.

**Rate limits.** Per-UID-per-second sliding window; the exact public-
endpoint default is documented as 600/5s shared across IPs but in
practice you get hard 429s well below that under load. Headers
`X-Bapi-Limit`, `X-Bapi-Limit-Status`, `X-Bapi-Limit-Reset-Timestamp`
expose remaining quota.

**Python client.** `pybit` (official, well maintained), ccxt.

**Reliability.** Good. Less battle-tested than Binance for archival
queries (1-year-old funding rates can return 4xx).

**Gotchas.**
- `category=linear` is USDT perps, `inverse` is coin-margined. Pick one.
- Symbol form: `BTCUSDT`.
- Bybit is technically restricted for UK retail trading; read-only
  public data is reachable.

**Verdict.** Recommended as the funding-rate fallback when Binance
data is missing or sparse.

Source: [Bybit funding history](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate),
[Bybit open interest](https://bybit-exchange.github.io/docs/v5/market/open-interest),
[Bybit rate limits](https://bybit-exchange.github.io/docs/v5/rate-limit).

### 1.6 Coinglass

**What.** Aggregator for derivatives data across 30+ exchanges:
funding rates, OI, liquidations, long/short ratios, OI/MC ratio. The
"easy button" for cross-exchange aggregates. Heavily used in retail
research dashboards.

**Free scope.** As of 2026 there is no free API tier in the traditional
sense. The lowest paid plan ("Hobbyist" / starter) is ~$35/month. There
are throttled "free key" queries through the Developer Center but the
documented daily caps are too low (~50 calls/day) to drive a 10-symbol
daily routine reliably. The website itself remains free for visual use.

**Auth.** API key (paid).

**Rate limits.** Tier-dependent; starter is ~30 calls/min.

**Python client.** No official Python lib; community wrappers exist on
GitHub but staleness varies. DIY HTTP if used.

**Reliability.** Reliable but the free tier has been progressively
tightened. Treat as "v2 only".

**Gotchas.**
- Marketing pages mention "free tier" but the practical free-tier API
  surface is essentially unusable for daily polling.
- Cross-exchange aggregates are nice but you can build the same thing
  by summing CCXT calls across Binance + Bybit + OKX yourself.

**Verdict.** Skip in v1. Document for v2 only. The cross-exchange
aggregation is nice-to-have, not need-to-have.

Source: [Coinglass pricing](https://www.coinglass.com/pricing),
[Coinglass docs](https://docs.coinglass.com/).

### 1.7 CoinGecko Demo API

**What.** The de facto free price + market-cap API. Powers most retail
dashboards. The free Demo plan is what we want.

**Free scope (Demo).**
- `GET /coins/markets`: top coins by market cap with price, 24h
  change, mcap, volume.
- `GET /coins/{id}/market_chart`: historical OHLCV (price, market_cap,
  total_volume) for any range.
- `GET /global`: global market cap, total volume, BTC dominance,
  ETH dominance, market_cap_change_percentage_24h.
- `GET /simple/price`: fast spot snapshot for any coins x any
  vs_currencies, with `include_24hr_vol`, `include_market_cap`.
- `GET /exchanges/{id}/tickers`: per-exchange ticker data.

**Auth.** Free Demo API key. Sign up at coingecko.com, generate the
key, pass as `x_cg_demo_api_key` query param. Anonymous access without
the key is also allowed but rate-limited harder and considered legacy.

**Rate limits.** 30 calls/min and 10,000 calls/month on the Demo plan
(2026-05-02). The published 30/min is the actual practical limit, in
my reading. Burst cleanly handled with HTTP 429.

**Python client.** Two viable choices:
- `pycoingecko` (community, version 3.2.0). Simple wrapper.
- `coingecko-sdk` (official, version 1.13.0 released 2026-02-25).
  Newer; better long-term bet.

**Reliability.** Strong. Largest user base of any free crypto API.
Occasional 502s at peak load.

**Gotchas.**
- Symbol form: CoinGecko ids (`bitcoin`, `ethereum`, `solana`, ...) not
  tickers. `coins/list` gives the mapping; cache it.
- 10k/month cap is comfortably enough for daily polls (10 symbols * 10
  endpoints * 30 days = 3,000) but be careful with `market_chart`
  (can be 1 call per symbol per timeframe).
- Historical data resolution: minute-granularity only for the last 1
  day on Demo; hourly within last 90 days; daily beyond. Same on the
  free public endpoint without a key.

**Verdict.** Recommended for v1 cross-asset (BTC dominance, total
market cap, ETH/BTC) and supplemental price snapshots. Best free option
for non-OHLCV market data.

Source: [CoinGecko free plan rate limit](https://support.coingecko.com/hc/en-us/articles/4538771776153-What-is-the-rate-limit-for-CoinGecko-API-public-plan),
[Demo signup](https://support.coingecko.com/hc/en-us/articles/21880397454233-User-Guide-How-to-sign-up-for-CoinGecko-Demo-API-and-generate-an-API-key),
[Crypto global endpoint](https://docs.coingecko.com/reference/crypto-global),
[coingecko-sdk PyPI](https://pypi.org/project/coingecko-sdk/).

### 1.8 CoinMarketCap free Basic

**What.** CMC's commercial Pro API has a free Basic plan that overlaps
with CoinGecko Demo.

**Free scope.** 10,000 credits/month, 30 requests/min, latest market
data, limited historical data, exchange asset reserve endpoints.

**Auth.** Free API key from `pro.coinmarketcap.com`.

**Rate limits.** 30 req/min, 10k credits/month. Critical: a single API
call can cost 1 to 100+ credits depending on parameters (pagination
past 100, multiple fiats, multiple coins per call). 10 symbols
in one call is cheaper but the credit math is convoluted.

**Python client.** `coinmarketcapapi`, `python-coinmarketcap`, all
community.

**Reliability.** Strong, but CMC is positioned as a paid product; the
free tier is a teaser.

**Gotchas.**
- The credit accounting is the trap. Many people burn through 10k credits
  in a few days of careless polling.
- Personal-use clause in Basic plan ToS: fine for our paper-trading
  use, but check before any commercial deployment.
- Historical OHLCV is restricted on free tier compared to CoinGecko.

**Verdict.** Skip in v1. CoinGecko Demo covers the same ground with
cleaner pricing semantics. Document as a fallback if CoinGecko goes
down or changes terms.

Source: [CMC API pricing](https://coinmarketcap.com/api/pricing/).

### 1.9 Blockchair

**What.** Multi-chain block explorer with a clean REST API. Best free
on-chain BTC + ETH source.

**Free scope.**
- `GET /bitcoin/stats`: daily-aggregated chain stats (transactions
  count, blocks, difficulty, market data, hashrate).
- `GET /bitcoin/dashboards/address/{addr}`: address state (balance,
  tx count, last 100 txs).
- `GET /bitcoin/transactions?q=time(YYYY-MM-DD..)`: SQL-ish filter
  syntax, returns transactions matching the predicate.
- `GET /ethereum/stats` and equivalents on the ETH side.
- 41 blockchains supported including BTC, ETH, LTC, BCH, BSV, DOGE,
  but NOT SOL/ADA/AVAX/DOT/LINK/MATIC. Those need other providers.

**Auth.** None for free tier (no API key needed).

**Rate limits (2026-05-02).** 1,000 calls/day without a key, hard cap
30 req/min, soft 5 req/sec. Higher load returns HTTP 435.

**Python client.** No official; DIY with `httpx`. Endpoints return JSON
with a `data` and `context` envelope, easy to wrap.

**Reliability.** Generally good. Stats endpoint occasionally lags by a
day at month boundaries.

**Gotchas.**
- "Active addresses" is not a first-class metric. You compute it from
  the daily aggregate response by deduplicating addresses in the day's
  transactions, which is expensive on free tier. Better: pull
  `addresses_24h` (24h unique active addresses count) from the stats
  endpoint, which is precomputed and one call.
- Exchange netflow is NOT directly exposed. You would need known
  exchange address labels (Wintermute publishes some, Glassnode
  monetises them). Without labels, "exchange netflow" via Blockchair
  is a research project, not a one-liner.
- 1,000 calls/day means roughly one stats fetch per chain per minute is
  the cap. Plenty for daily routines.

**Verdict.** Recommended for v1 BTC/ETH active-address metric. NOT a
viable v1 source for exchange netflow without labelled-address overlay.

Source: [Blockchair API plans](https://blockchair.com/api/plans),
[Blockchair API docs](https://blockchair.com/api/docs).

### 1.10 Etherscan / family (BscScan, Solscan, Polygonscan, etc.)

**What.** Block-explorer-backed REST APIs. Free key required.

**Free scope (Etherscan, after the 2025 reduction).**
- `GET /api?module=account&action=balance&address={...}`: address state.
- `GET /api?module=stats&action=ethsupply`: ETH supply.
- `GET /api?module=account&action=tokentx&...`: ERC20 transfers.
- `module=gastracker`: gas oracle.
- Verified-contract endpoints (source/abi) remain on free tier across
  all chains.
- API v2 unifies multi-chain queries with a single key per the November
  2025 rollout.

**Auth.** Free API key, generate at etherscan.io.

**Rate limits (2026-05-02).** 5 calls/sec, 100,000 calls/day per key.
No-key access is no longer supported. The 2025 "10% reduction" cut some
chain coverage on free tier (Avalanche, Base, BNB Chain, Optimism are
now restricted on free tier; ETH and Polygon mainnets remain).

**Python client.** `etherscan-python`, `etherscan-py`. Both community.

**Reliability.** Strong on ETH mainnet. The 2025 free-tier cuts mean
multi-chain projects now hit unexpected restrictions on smaller chains.

**Gotchas.**
- Solscan is a separate ecosystem (Solana, not EVM). Solscan's free
  tier is shrinking; the Pro API is paid. As of 2026, basic public
  endpoints are free but most useful endpoints require a paid plan.
- BscScan is technically "Etherscan family" but with separate keys
  pre-v2; v2 unifies.
- "Active addresses" is again not a single endpoint. You count unique
  `from` addresses in `tokentx` over a window (expensive) or use a
  pre-aggregated provider (Glassnode/Coinmetrics, paid).
- Exchange netflow: same problem as Blockchair, needs labelled
  exchange addresses. Etherscan tags some major exchanges in the UI,
  but the labels are not exposed via the free API.

**Verdict.** Useful for ETH-side address-balance queries and gas. NOT a
practical free source for active-addresses or exchange-netflow at our
cadence. Use Blockchair for ETH stats instead.

Source: [Etherscan rate limits](https://docs.etherscan.io/resources/rate-limits),
[Etherscan free tier changes Nov 2025](https://info.etherscan.com/whats-changing-in-the-free-api-tier-coverage-and-why/),
[Solscan API plans](https://solscan.io/apis).

### 1.11 Glassnode

**What.** Premier on-chain analytics provider. The MVRV, SOPR, UTXO
age band, exchange netflow, etc., that crypto research papers cite are
typically Glassnode metrics.

**Free scope.** Studio Standard (Free) gives Tier 1 metrics at daily
resolution in the web dashboard. API access is NOT included on the
free plan. You need at least the Advanced plan (~$29/month) for API
access at all, and the genuinely useful exchange-flow / SOPR / MVRV
metrics are gated behind Tier 2 / Tier 3 (Professional and Pro plans).

**Auth.** API key (paid).

**Rate limits.** Plan-tier dependent; not relevant for v1.

**Python client.** `glassnode-api`.

**Reliability.** Industry-leading data quality. Their definition of
"exchange netflow" is the labelled-address gold standard.

**Gotchas.**
- Many third-party guides claim Glassnode "has a free API"; strictly
  speaking the API tier is a paid SKU; only the web dashboard has a
  free read tier.
- Tier 1 metrics are the basics (tx count, supply); the alpha-bearing
  metrics (entity-adjusted, exchange-labelled flows, realized cap
  variants) are paid.

**Verdict.** Skip for v1. Strong v2 candidate for the on-chain provider
upgrade specifically for exchange netflow and entity-adjusted metrics.

Source: [Glassnode pricing](https://glassnode.com/pricing/studio),
[Glassnode docs](https://docs.glassnode.com/).

### 1.12 CryptoQuant

**What.** Exchange-flow specialist; competitor to Glassnode with more
emphasis on exchange-side data (CEX inflows/outflows, miner outflows).

**Free scope.** Basic plan is severely limited; web-only. API key is
gated behind the Premium ($799/mo) and Institutional plans.

**Auth.** API key (paid, expensive).

**Rate limits.** Plan-tier dependent.

**Python client.** No official; community wrappers exist.

**Verdict.** Skip in v1 and v2. Premium is too expensive for the
incremental signal value; if budget appears, Glassnode Professional
delivers more for less.

Source: [CryptoQuant pricing](https://cryptoquant.com/pricing).

### 1.13 CryptoPanic — DISCONTINUED

**Status (2026-04-01).** CryptoPanic discontinued its free Developer
tier. The replacement in this codebase is CryptoCompare News (see
docs/SOURCES_EXPANSION.md §1). The notes below are kept for historical
reference; do not wire new integrations against CryptoPanic.

**What.** Aggregated crypto news with vote-based sentiment ("bullish"/
"bearish"/"important" votes from the platform's user base).

**Free scope.**
- `GET /api/v1/posts/?auth_token={key}&currencies=BTC,ETH,...&filter=...`
- Filters: `rising`, `hot`, `bullish`, `bearish`, `important`, `saved`,
  `lol`.
- Returns headline, source, currencies tagged, votes (bullish, bearish,
  important counts), published_at.

**Auth.** Free auth token. Sign up at cryptopanic.com, get token from
developer dashboard.

**Rate limits (2026-05-02).** Free Developer plan: documented at
~50-200 requests/hour depending on the source. CryptoPanic has been
opaque about exact numbers; safest assumption is 60/hour. The
historical RESEARCH.md note of "100 calls/min" is optimistic; verify
on your actual key before relying on it.

**Python client.** `cryptopanic` (unofficial wrapper, version varies).
DIY HTTP is fine.

**Reliability.** Good uptime; the sentiment vote signal is noisy
(retail-driven).

**Gotchas.**
- Vote counts are population-of-CryptoPanic-users sentiment, not market
  sentiment. Use as a coarse "this story is being discussed" filter,
  not a directional signal.
- Free plan does not return the full article body, just the metadata.
  For body text follow the `url` to the source.

**Verdict.** Recommended for v1 as a news-headline aggregator. Treat
sentiment scores as low-information.

Source: [CryptoPanic API plans](https://cryptopanic.com/developers/api/plans).

### 1.14 Reddit JSON endpoints

**What.** Append `.json` to any Reddit URL for a JSON response (e.g.
`https://www.reddit.com/r/cryptocurrency/hot.json?limit=100`). No
official "free API tier", but the JSON suffix has been around for
years and is still functional.

**Free scope.** Any public subreddit listing (`hot`, `new`, `top`,
`controversial`), comments by post id, user activity. r/cryptocurrency,
r/bitcoin, r/ethereum, r/solana are the relevant subs.

**Auth.** None. But: a custom `User-Agent` header is REQUIRED, otherwise
you get 429s immediately. Reddit's TOS technically wants registered apps;
in practice JSON suffix without registration still works.

**Rate limits (2025).** Unauthenticated JSON requests: ~10 QPM,
heavily user-agent-dependent. Banned user-agents (default `python-
requests/...`) get 429d in seconds. With a custom UA and polite pacing,
multi-hour stable scraping is possible.

**Python client.** `praw` (official, requires OAuth registration) or
`httpx`/`requests` for raw JSON. For our cadence, raw JSON is enough.

**Reliability.** Mediocre. Reddit has progressively tightened
unauthenticated access since the 2023 API price changes; expect breakage.

**Gotchas.**
- 1,000-post-per-listing ceiling: cannot paginate beyond.
- No real "sentiment": would need a separate VADER / FinBERT pass on
  comments. Out of scope for v1.
- Crypto subs are dominated by retail noise; alpha-to-noise ratio is
  poor.

**Verdict.** Marginal for v1. Useful if you want a "mention count
spike" feature for headline-driven moves. Skip if scope is tight.

Source: [Reddit API rate limits, 2025 status](https://data365.co/blog/reddit-api-limits),
[Reddit JSON suffix scraping notes](https://til.simonwillison.net/reddit/scraping-reddit-json).

### 1.15 CoinDesk and Cointelegraph RSS

**What.** Plain-old RSS / Atom feeds from the two largest English crypto
news outlets. Free, unauthenticated, stable.

**Free scope.**
- CoinDesk: `https://www.coindesk.com/arc/outboundfeeds/rss/`, every
  story they publish, updated on publish.
- Cointelegraph: `https://cointelegraph.com/rss` (general),
  `https://cointelegraph.com/rss/tag/bitcoin`, `.../ethereum`,
  `.../altcoin`, etc. for topic feeds.

**Auth.** None.

**Rate limits.** None enforced; polite polling at 5-15 minute intervals
is fine. Both publishers cache feeds at the CDN layer.

**Python client.** `feedparser` (the canonical RSS lib).

**Reliability.** Excellent. RSS is a stable contract that publishers
break only by mistake.

**Gotchas.**
- CoinDesk has had ownership changes (Bullish acquired in 2023);
  editorial direction has shifted but the feed continues.
- Cointelegraph occasionally publishes sponsored content tagged the
  same as editorial; filter on the `<category>` tag.
- Feeds give title + summary + link, not full body.

**Verdict.** Recommended for v1 as a headline-source supplement to
CryptoPanic. Free, reliable, easy.

Source: [CoinDesk RSS pointer](https://www.coindesk.com/coindesk-news/2021/09/17/coindesk-rss),
[Cointelegraph RSS index](https://cointelegraph.com/rss).

### 1.16 FRED (Federal Reserve Economic Data)

**What.** St. Louis Fed's open data API. Already used by the stock
sibling. Source of macro context (DXY, real yields, M2, etc.).

**Free scope.** Every series in FRED's catalog, full history. For
crypto-relevant macro:
- `DTWEXBGS`: Trade-weighted USD index (broad).
- `DGS10`: 10-year Treasury yield.
- `DFII10`: 10-year TIPS (real yield).
- `M2SL`: M2 money supply (monthly).
- `WALCL`: Fed balance sheet (weekly).
- `VIXCLS`: VIX (also via yfinance ^VIX, lower latency).

**Auth.** Free API key. Sign up at fred.stlouisfed.org.

**Rate limits.** 120 requests/minute per key. No daily cap.

**Python client.** `fredapi` (PyPI), `fedfred` (newer, supports async
and built-in rate limiting).

**Reliability.** Government infrastructure; uptime is high. Series get
new vintages on the publication schedule (DGS10 daily, M2SL monthly).

**Gotchas.**
- DXY proper (the ICE futures index) is not on FRED. `DTWEXBGS` is the
  Fed's broader trade-weighted equivalent, close cousin but not
  identical; document the divergence in code comments.
- M2SL is monthly, not daily. Forward-fill in your panel.

**Verdict.** Recommended for v1 macro panel. Reuse the stock sibling's
FRED provider when porting.

Source: [FRED API key terms](https://fred.stlouisfed.org/docs/api/terms_of_use.html),
[FRED API errors / rate limits](https://fred.stlouisfed.org/docs/api/fred/errors.html),
[fredapi PyPI](https://pypi.org/project/fredapi/).

### 1.17 Messari free / Pro

**What.** Crypto market intelligence with asset profiles, metrics, news.
Has been ratcheting down their free API surface since 2023.

**Free scope.** ~20 requests/minute, basic asset metrics
(`/v1/assets/{slug}/metrics`), profiles (`/v2/assets/{slug}/profile`).
Some endpoints accessible without an API key but rate-limited harder;
all endpoints in 2026 want the `x-messari-api-key` header.

**Auth.** Free API key from messari.io dashboard.

**Rate limits.** 20 req/min on free tier.

**Python client.** `messari` (official, in `messari/messari-python-api`)
but maintenance has lagged.

**Reliability.** Mid. The product strategy has shifted toward enterprise;
the free API is not a priority.

**Gotchas.**
- The "free API for 40,000 assets" tagline is partly marketing; the
  most useful enriched fields are AI-tier or paid.
- Asset slugs differ from CoinGecko ids (`bitcoin` vs `btc`).

**Verdict.** Skip in v1. CoinGecko + Messari overlap and CoinGecko is
the cleaner free option. Reconsider in v2 if you need their qualitative
profiles.

Source: [Messari API page](https://messari.io/api).

### 1.18 Dune Analytics

**What.** SQL-on-onchain. Write a query against indexed blockchain tables
(Ethereum, Solana, Bitcoin, Polygon, etc.), execute it via API, get a
result CSV/JSON. The community pre-builds thousands of dashboards you
can re-execute.

**Free scope.** Free plan: 2,500 credits/month, basic SQL engine, 100MB
storage, API access. A query execution costs credits proportional to
data scanned and time. A simple daily-aggregation query is roughly 1-5
credits; a full-history backfill scan can be hundreds.

**Auth.** Free API key, sign up at dune.com.

**Rate limits.** Credit-based, not request-rate-based. Free-tier queries
are deprioritised in the execution queue.

**Python client.** `dune-client` (official, PyPI).

**Reliability.** Strong; Dune has become the de facto on-chain SQL layer.
Refresh latency on community queries depends on the query owner's plan;
for self-authored queries you control refresh.

**Gotchas.**
- 2,500 credits/month is enough for ~10-50 daily scheduled re-executions
  of a small query, depending on size. Tight but workable for a few
  bespoke queries (e.g. "ETH active addresses last 30 days").
- Pre-built community queries may stop refreshing if the author
  downgrades. Self-author the queries you depend on.
- Solana is supported but the schema is harder to navigate than EVM.

**Verdict.** Recommended for v1 as a niche on-chain backstop. Useful
specifically if you want a pre-aggregated "active addresses last N days"
query for ETH and BTC at zero rate-limit pressure on Blockchair / Etherscan.

Source: [Dune pricing](https://dune.com/pricing),
[Dune execute query API](https://docs.dune.com/api-reference/executions/endpoint/execute-query).

### 1.19 The Graph

**What.** Decentralised query layer for blockchain data (Ethereum,
Polygon, Arbitrum, Optimism, etc.). Subgraphs index contract events into
queryable GraphQL APIs.

**Free scope.** Subgraph Studio free tier: 100,000 queries/month
across The Graph Network. Hosted Service was fully deprecated in 2026.

**Auth.** API key from Subgraph Studio.

**Rate limits.** 100k queries/month free, then GRT-billed (~$1.50-$2 per
100k queries).

**Python client.** No official; query GraphQL endpoints with `httpx` +
`gql` library.

**Reliability.** Decentralised network with multiple indexers; redundancy
is good but query latency varies by indexer pricing strategy.

**Gotchas.**
- Designed for protocol-level queries (Uniswap pools, Aave positions),
  not generic active-address counts. To get our metric you would need
  a custom subgraph or a community one tracking the right tables.
- GRT-token-billed once you exceed free, which is administratively
  more friction than a credit card.
- For our universe (BTC + ETH + L1 alts), most of the chains are not
  EVM, so subgraph coverage is mostly ETH-only.

**Verdict.** Skip in v1. Document for v2 if a DeFi/protocol-level signal
gets added (e.g. "TVL change on Aave"); not relevant for the current
signal set.

Source: [Subgraph Studio pricing](https://thegraph.com/studio-pricing/).

### 1.20 yfinance (already wired, listed for completeness)

**What.** Unofficial Yahoo Finance scraper. Already used in the stock
sibling and the crypto backfill script.

**Free scope.** Daily OHLCV for any Yahoo-tracked ticker including
crypto in `BTC-USD` form.

**Auth.** None.

**Rate limits.** Yahoo's rate limiting is fuzzy; 1 req/sec is safe.
Yahoo periodically breaks the unofficial endpoints (most recently in
2024) and yfinance gets patched in response.

**Python client.** `yfinance` (PyPI).

**Reliability.** Adequate for daily; Yahoo's intraday data is unreliable
and not a serious source.

**Gotchas.**
- Crypto tickers on Yahoo are aggregated across exchanges; the price is
  Yahoo's choice, not Coinbase's or Binance's. Acceptable for daily but
  not for tick-accurate work.
- MATIC-USD: Yahoo continues to publish under MATIC even after the
  POL rebrand. Aliased correctly in the universe loader already.

**Verdict.** Already wired. Stays as the primary daily-OHLCV source.

---

## 2. Recommended v1 stack (free-only)

Single-source-of-truth for what to wire on day one. Names library +
exact endpoint / call.

### Spot OHLCV
- **Daily**: `yfinance` (already wired). Function: `yfinance.Ticker(...)
  .history(period="5y", interval="1d")`. Survivorship-correct for our
  10-name universe.
- **Hourly / intraday**: `ccxt` against Binance spot. Call:
  `binance.fetch_ohlcv("BTC/USDT", "1h", limit=500)`. Already covered by
  `CcxtProvider.fetch_ohlcv` in `ccxt_provider.py`.

### Funding rate (per symbol, 8h cadence)
- Primary: `ccxt` against Binance USDM. Call:
  `binanceusdm.fetch_funding_rate("BTC/USDT")` for the latest 8h print
  and `fetch_funding_rate_history("BTC/USDT", limit=3)` for the trailing
  24h required by `signals/funding_rate.py`.
- Fallback: ccxt against Bybit V5 linear category (when Binance is
  missing a symbol or returns an empty window).

### Open interest (per symbol, daily snapshot or 7d delta)
- Primary: `ccxt.binanceusdm.fetch_open_interest_history("BTC/USDT",
  "1d", limit=10)` returns a list of `{timestamp, openInterestAmount,
  openInterestValue}` dicts. `signals/open_interest.py` needs
  `oi_today` and `oi_7d_ago`; index `[-1]` and `[-8]`.
- Fallback: Bybit V5 `/v5/market/open-interest` (intervalTime=1d).

### Liquidations (last 24h aggregate)
- v1 status: stay stubbed. The Binance REST `allForceOrders` is
  effectively dead for non-account-holders, and the WebSocket capture
  pipeline is out of v1 scope per `RESEARCH.md` 3.4.
- If you must populate: pre-aggregate from the public WebSocket stream
  `wss://fstream.binance.com/ws/!forceOrder@arr` over a 24h rolling
  buffer in a separate process. Defer.

### On-chain (BTC / ETH active addresses, exchange netflow)
- Active addresses: `Blockchair`. Call:
  `GET https://api.blockchair.com/bitcoin/stats` and
  `https://api.blockchair.com/ethereum/stats`. Field:
  `data.transactions_24h` (proxy) or compute z-score from a rolling
  panel of `addresses_24h` (when present) over 30d / 1y.
- Exchange netflow: NOT freely available without labelled exchange
  addresses. Recommendation: leave the field None in `OnChainProvider`
  for v1, document this gap, plan for Glassnode in v2.

### Cross-asset (BTC dominance, ETH/BTC, total mcap)
- `CoinGecko` Demo API. Call:
  - `GET https://api.coingecko.com/api/v3/global?x_cg_demo_api_key=...`
    -> `data.market_cap_percentage.btc` for dominance,
    `data.total_market_cap.usd` for total mcap.
  - For ETH/BTC: derive from the price panel we already have in
    `signals/cross_asset.py`; a separate API call is unnecessary.

### News + sentiment
- Headlines: `CryptoCompare News` free tier
  (`min-api.cryptocompare.com/data/v2/news/`). Replaces CryptoPanic
  since 2026-04-01 (free Developer tier discontinued).
- Backup: CoinDesk + Cointelegraph RSS via `feedparser`, Reddit JSON.
- Sentiment numeric: NLTK VADER lexicon scoring per article.

### Macro
- `FRED` (already used by stock sibling). Series: `DTWEXBGS` (USD
  index), `DGS10` (10y nominal), `DFII10` (10y real), `M2SL` (M2
  monthly), `VIXCLS` (or yfinance `^VIX`). Library: `fredapi`.

### Sketch (Python, what `funding_provider.py` v1 wiring looks like)

```python
import ccxt

class FundingRateProvider:
    def __init__(self, ccxt_provider):
        self._ccxt = ccxt_provider

    def latest(self, symbol):
        snap = self._ccxt.fetch_funding_rate(symbol)
        return snap.funding_rate if snap else None

    def last_24h(self, symbol):
        # Binance USDM funding cadence is 8h; 3 prints = 24h
        perp = self._ccxt._perp_client()
        ccxt_sym = to_ccxt_symbol(symbol)
        rows = perp.fetch_funding_rate_history(ccxt_sym, limit=3)
        return [float(r["fundingRate"]) for r in rows]
```

(This is approximately what is already there; the missing piece is
an explicit Bybit fallback, not a rewrite.)

---

## 3. Recommended v2 stack (paid, when budget allows)

Trigger conditions for v2: paper portfolio shows a real edge over
buy-and-hold over 6+ months, and Senna decides to graduate.

| Need | v2 upgrade | Rough cost |
|------|-----------|------------|
| On-chain (exchange netflow, MVRV, SOPR, entity-adjusted) | Glassnode Advanced or Professional | ~$29/mo (Advanced); ~$799/mo (Pro) for full API |
| Cross-exchange derivatives aggregates | Coinglass Hobbyist+ | $35/mo+ |
| Liquidation history (REST) | Coinglass or self-host the WebSocket capture from Binance/Bybit | $35/mo (Coinglass) or DIY |
| Real-time websocket spot/perp | ccxt.pro | ~$200/mo commercial license |
| Higher-fidelity macro | Bloomberg / Refinitiv | several thousand/mo, skip; FRED is enough |
| News sentiment with NLP | Santiment Pro or LunarCrush API | ~$50-$135/mo |
| Multi-chain on-chain (SOL, AVAX, etc.) | Coinmetrics, Token Terminal | $99-$500/mo |

The biggest single uplift in v2 is Glassnode (Professional). It
unlocks the labelled-address exchange netflow that v1 cannot derive
freely, which is the load-bearing input for the on-chain signal in
`signals/onchain.py`.

---

## 4. Provider mapping

```
funding_provider.py
  primary:  ccxt (binanceusdm) via CcxtProvider.fetch_funding_rate +
            fetch_funding_rate_history(limit=3)
  fallback: ccxt (bybit V5 linear) via the same method surface

onchain_provider.py
  primary:  Blockchair REST (BTC + ETH stats endpoint) for
            active-address inputs; netflow stays None in v1
  fallback: Dune Analytics free tier with a self-authored daily
            aggregation query, only if Blockchair quota becomes tight
  v2:       Glassnode Professional for exchange-labelled netflow

ccxt_provider.py
  primary:  ccxt (already correct)
  exchange order: binance (spot + USDM perps) -> bybit (linear) ->
                  coinbase (USD-quoted, fallback for symbols missing
                  on Binance) -> kraken (final fallback for UK
                  execution-side cross-checks)

(implicit: cross_asset via CoinGecko Demo, news via CryptoPanic +
RSS, macro via FRED. These are not currently in dedicated provider
files; suggest adding `cross_asset_provider.py`, `news_provider.py`,
`macro_provider.py` parallel to the existing stubs.)
```

---

## 5. UK / FCA considerations

Senna is UK-based. The two API-relevant restrictions:

1. **Binance derivatives**: Binance.com restricts derivatives products
   for UK retail. Read-only public endpoints (which is all we use in v1)
   are NOT geo-blocked; you can pull funding rates and OI from Binance
   USDM REST without issue. Trading those derivatives, separate matter,
   not in scope.
2. **Bybit**: similar status to Binance for UK retail trading. Public
   read-only endpoints are reachable.
3. **Binance.US** (binance.us): blocks non-US visitors; do NOT use as a
   substitute for Binance.com.
4. **Coinbase**: FCA-registered for UK retail; the recommended live-
   execution venue per `RESEARCH.md`.
5. **Kraken**: UK-friendly; spot trading available, leverage limited.

UK-friendly fallback chain for spot OHLCV:
`Binance public read -> Coinbase Advanced -> Kraken public.`

UK-friendly chain for funding / OI:
`Binance USDM public read -> Bybit V5 public read.`
(Both are read-only; FCA derivatives restrictions do not apply to
public market data ingestion.)

---

## 6. Build plan

Ordered work items to wire the v1 stack into the existing provider
stubs. Each item: file path, API call, response shape, caching,
test fixture.

### 6.1 Wire funding rates in `data/funding_provider.py`

- File: `src/crypto_research_watchlist/data/funding_provider.py`.
- API: ccxt `binanceusdm.fetch_funding_rate_history(symbol, limit=3)`.
- Response field: each row has `fundingRate` (float, e.g. 0.0001),
  `fundingTimestamp` (ms), `symbol`. Take `[r["fundingRate"] for r in
  rows]`.
- Caching: on-disk JSON cache keyed by `(symbol, date)` with 1h TTL.
  Funding only changes every 8h, so a 1h cache is generous. Use an
  existing cache helper if `stock_research_watchlist` has one we can
  port.
- Rate-limit concern: minimal at our cadence; ccxt's `enableRateLimit:
  True` is already on.
- Fallback: try `bybit.fetch_funding_rate_history(symbol_with_USDT,
  limit=3)` if Binance returns []. Wrap in `try/except` with logger.
- Test fixture: capture one `fetch_funding_rate_history` JSON response
  per major symbol (BTC, ETH) into `tests/fixtures/binance_funding_*.json`,
  inject via the `_perp_client` constructor parameter (already supported
  by `CcxtProvider.__init__`).

### 6.2 Wire open interest fields onto `SignalContext`

- File: `src/crypto_research_watchlist/data/ccxt_provider.py` (extend),
  `src/crypto_research_watchlist/signals/__init__.py` (verify
  SignalContext has `open_interest_today`, `open_interest_7d_ago`).
- API: `binanceusdm.fetch_open_interest_history(symbol, "1d", limit=10)`.
- Response field: each row has `openInterestAmount` (in base coin) and
  `openInterestValue` (in quote / USDT). Use `openInterestValue` for
  USD-comparable numbers. Index `[-1]` and `[-8]` for the 7d delta.
- Caching: 12h TTL. Daily OI does not need fresher fetches.
- Rate-limit concern: 10 symbols x 1 call/12h is trivial.
- Fallback: Bybit `GET /v5/market/open-interest?...&intervalTime=1d`.
- Test fixture: `tests/fixtures/binance_oi_BTC.json` with 10 daily rows.

### 6.3 Wire BTC + ETH on-chain in `data/onchain_provider.py`

- File: `src/crypto_research_watchlist/data/onchain_provider.py`.
- API: Blockchair `GET https://api.blockchair.com/{bitcoin|ethereum}/stats`.
- Response field: `data.transactions_24h` for BTC; for active-addresses
  proxy use the difference between successive daily snapshots stored
  locally in SQLite. The 30d / 1y baseline for the z-score is a rolling
  computation against the local panel, not an API call.
- Caching: persist daily snapshots to `crypto_research_watchlist.db`
  (table `onchain_daily(symbol, date, transactions_24h, blocks)`).
  TTL: 24h.
- Rate-limit concern: 2 calls/day, well under the 1000/day cap.
- Fallback: skip; if Blockchair is down for a single day the gap is
  acceptable.
- For SOL / ADA / AVAX / DOT / LINK / MATIC: leave OnChainSnapshot
  fields None in v1. The `signals/onchain.py` evaluator already returns
  NEUTRAL when both inputs are None.
- Test fixture: `tests/fixtures/blockchair_btc_stats.json`,
  `tests/fixtures/blockchair_eth_stats.json`. Inject via a `client`
  parameter on a new `BlockchairClient` class so tests are offline.

### 6.4 Add `data/cross_asset_provider.py` (new file)

- API: CoinGecko `GET https://api.coingecko.com/api/v3/global` with
  `x_cg_demo_api_key` query param.
- Response field: `data.market_cap_percentage.btc` (float, e.g. 52.3),
  `data.total_market_cap.usd` (float).
- Caching: 1h TTL.
- Library: `coingecko-sdk` 1.13.0 (official). Could also use raw
  `httpx` to avoid the dependency.
- Test fixture: `tests/fixtures/coingecko_global.json`.
- Rate concern: 30 calls/min limit; we use 1 call/hour. Trivial.

### 6.5 Add `data/news_provider.py` (new file)

- Primary: CryptoPanic posts endpoint with the universe symbol list.
- Secondary: feedparser over CoinDesk + Cointelegraph RSS.
- Cache: SQLite table `news_items(id, source, published_at, url, title,
  symbols, raw_json)`. Dedupe on `url`.
- Fixtures: snapshot one CryptoPanic JSON page and one RSS feed XML
  to `tests/fixtures/`.

### 6.6 Add `data/macro_provider.py` (new file)

- API: FRED via `fredapi.Fred(api_key=...).get_series("DTWEXBGS")`.
- Series: DTWEXBGS, DGS10, DFII10, M2SL.
- Cache: write-through to SQLite `macro_series(series_id, date,
  value)`. TTL: 1d.
- Fixture: pickle a small DataFrame snapshot to
  `tests/fixtures/fred_dtwexbgs.parquet`.

### 6.7 Update `config.yml`

Add a `data_sources.api_keys_env` section listing the env var names
the providers will read from (`COINGECKO_DEMO_KEY`, `CRYPTOPANIC_KEY`,
`FRED_API_KEY`). Update `.env.example` with the same list, blank values.

### 6.8 Add a thin retry wrapper

- File: `src/crypto_research_watchlist/data/_http.py` (new).
- Wraps `httpx.Client` with: per-host rate-limit token bucket, retry on
  429/5xx with jittered backoff, structured logging on failure.
- Used by Blockchair, CoinGecko, CryptoPanic, FRED clients.

### 6.9 Document the verdict + provider map in `RESEARCH.md`

Append a "v1 wiring resolution" section to `RESEARCH.md` once the wiring
PR lands, pointing at this doc as the source of decisions.

---

## 7. Open questions

Items I could not pin down to a confident answer; the operator should
resolve before / during the wiring PR.

1. **CryptoPanic free Developer plan rate limit, exact number.** Their
   public docs in 2026 do not commit to a number. Sources range from
   "50/hour" to "200/hour" to the older "100/min" cited in `RESEARCH.md`.
   Resolution: sign up, generate the key, hammer it briefly in a
   dev session, observe the 429 threshold. Document the actual limit
   inline in `news_provider.py`.

2. **Coinbase Advanced Trade public-candles auth requirement.** Docs in
   2026 list `market/products/{id}/candles` as a "public" endpoint, but
   community reports (ccxt issue #22571) suggest some candle ranges
   still require a signed JWT. Resolution: hit the endpoint anonymously
   from a dev box for BTC-USD daily candles; if it returns 200, we
   are clear. Document either way.

3. **Binance `allForceOrders` REST live status for non-account
   holders.** Anecdotal that it returns 401 / 403 without account-level
   auth, even though the docs imply public. Resolution: try one
   anonymous call. If dead, accept liquidations are WebSocket-only and
   defer.

4. **CCXT version pin.** CCXT releases breaking changes at major
   versions. The current dependency surface (`fetch_funding_rate`,
   `fetch_funding_rate_history`, `fetch_open_interest_history`) is
   stable on 4.x. Resolution: pin `ccxt>=4.4,<5` in `pyproject.toml`
   and bump deliberately.

5. **Glassnode v2 budget.** The signal lift from labelled exchange
   netflow is real but the cheapest API-bearing tier (Advanced) starts
   at ~$29/mo and the genuinely useful Tier 2 metrics need
   Professional. Resolution: only revisit when paper-portfolio results
   justify any spend.

6. **Solscan Pro vs DIY.** Solscan's free public surface keeps
   shrinking. Solana on-chain coverage (active addresses, large
   transfers) is the gap in our v1 onchain story. Resolution: accept
   the gap in v1 (`OnChainSnapshot` for SOL stays None); revisit at
   v2 with either Solscan Pro, Helius, or a custom RPC + query.

7. **MATIC vs POL across providers.** Each provider has migrated on a
   different timeline:
   - yfinance: still `MATIC-USD`.
   - Binance: trades both `MATICUSDT` and `POLUSDT`; MATIC volume has
     thinned post-rebrand.
   - Coinbase: only `POL-USD`.
   - CoinGecko: id is `matic-network` historically, watch for migration.
   Resolution: keep `MATIC-USD` as the canonical universe symbol but add
   a per-provider override map (the seed already exists in
   `_CCXT_SYMBOL_OVERRIDES`); extend the override pattern to CoinGecko
   ids and Coinbase product ids.

8. **Reddit JSON suffix longevity.** Functional in 2025-2026 but
   Reddit has been progressively tightening unauthenticated access since
   the 2023 API price changes. Resolution: do not depend on Reddit for
   any signal in v1; mention in `RESEARCH.md` 2.7 as a deprecated
   experiment.

9. **CCXT.pro license cost in 2026.** Public pricing is opaque (case-by-
   case quote). Resolution: irrelevant for v1; document at the v2
   threshold if real-time websocket data becomes a v2 requirement.

10. **The ccxt unified `fetch_open_interest` vs `fetch_open_interest_history`
    return shapes per exchange.** Documented as unified but real-world
    quirks exist (Bybit returns OI in different units depending on
    `category`). Resolution: smoke-test both Binance and Bybit return
    paths in the wiring PR; capture as fixtures.
