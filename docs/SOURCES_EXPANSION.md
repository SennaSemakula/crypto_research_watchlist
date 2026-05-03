Last reviewed: 2026-05-03

# SOURCES_EXPANSION

Deep landscape research on crypto data and news providers, written as a
direct sequel to `docs/API_RESEARCH.md`. The motivating event is the
deprecation of the CryptoPanic free Developer tier on 2026-04-01: the
v1 news pipeline lost its primary structured headline source and now
relies only on CoinDesk RSS, CoinTelegraph RSS, and Reddit
r/cryptocurrency JSON. This doc maps the broader landscape so the
operator can rebuild the news layer with redundancy and, when budget
appears, layer on the institutional-grade signals that retail-only
free-tier sources cannot deliver.

The previous research doc focused on the free-only v1 cut. This one is
explicitly multi-tier: free wins to wire today, $50/month
"punching-above-their-weight" picks, $300/month serious-retail tier,
and $2k+/month small-institutional tier. Pricing is honest. Where a
provider is overpriced for what it offers, this doc says so.

Conventions: every rate-limit and pricing claim is cited inline with a
URL. Where a provider hides pricing behind a sales conversation, that
is called out explicitly rather than guessed.

---

## 1. News and headlines (immediate replacement for CryptoPanic)

The v1 pipeline currently has three working sources after CryptoPanic's
exit: CoinDesk RSS, CoinTelegraph RSS, Reddit JSON. The first job is
to triple that count using free RSS alone before reaching for paid
tiers. RSS is preferred because it is the contract publishers break
least often, and `feedparser` is already a dependency.

### 1.1 The Block

URL (site): https://www.theblock.co/. RSS feed at
https://www.theblock.co/rss.xml (the standard convention; verify by
opening it before wiring) per the Feedspot crypto RSS index
[Feedspot top crypto feeds](https://rss.feedspot.com/cryptocurrency_rss_feeds/).
Free for the public RSS, which carries headlines and short summaries
of every editorial story. The Block Pro is a separate institutional
product covering proprietary research, datasets, and a venture
database; pricing is sales-gated and not on the marketing page
[The Block Pro](https://www.theblock.pro/). Public reports from
buyers put The Block Pro in the low five figures per seat per year;
not relevant for v1 or v2 retail tiers. Latency from event to feed is
typically under 10 minutes for breaking stories. Editorial breadth is
strong on US institutional and policy coverage, weaker on Asia-native
exchanges.

Verdict: free RSS is an immediate v1 win. Skip Pro until you have
enterprise budget.

### 1.2 Decrypt

URL: https://decrypt.co/feed (RSS) per
[Decrypt feed listing](https://rss.feedspot.com/decrypt_rss_feeds/).
Free, no auth, full editorial inventory including AI/crypto crossover
stories that other outlets undercover. Latency under 15 minutes.
Reliability has been excellent since 2019; the feed survived the 2024
ownership shuffle when ConsenSys fully spun the publisher out. Breadth
is consumer-leaning, lighter on derivatives and on-chain than The
Block.

Verdict: immediate v1 win.

### 1.3 Bitcoin Magazine

Free RSS published at the standard WordPress
`https://bitcoinmagazine.com/.rss/full/` path; also indexed by Feedspot
[Bitcoin RSS feeds](https://rss.feedspot.com/bitcoin_rss_feeds/).
BTC-only by editorial mandate, which makes it useful as a single-asset
specialist feed. Reliability strong, latency good. Editorial bias is
explicitly maximalist; treat as a sentiment input as well as a news
input.

Verdict: immediate v1 win for the BTC-tagged news bucket.

### 1.4 CoinTelegraph (already wired, health check)

Already in `news/sources.py`. Confirmed live as of 2026-05-03. The
canonical feed `https://cointelegraph.com/rss` plus per-tag feeds
(`/rss/tag/bitcoin`, `/rss/tag/ethereum`, `/rss/tag/altcoin`) are
useful if the orchestrator wants per-coin pre-filtering rather than
post-fetch ticker regex extraction.

Verdict: keep; add the per-tag feeds when convenient.

### 1.5 CoinDesk (already wired) and CoinDesk Indices

Editorial RSS already wired and healthy
[CoinDesk RSS](https://www.coindesk.com/arc/outboundfeeds/rss). The
distinct paid product is CoinDesk Indices (formerly CoinDesk Data,
formerly CryptoCompare which CoinDesk acquired in 2022): institutional
reference rates, BMR-compliant indices, market data feeds. Pricing is
sales-only, listed as "data.coindesk.com" with no public price card
[CoinDesk Data](https://data.coindesk.com/). For most retail and
small-institutional use the editorial RSS is the only relevant cut;
indices are an enterprise SKU.

Verdict: editorial feed already in v1. Indices skip entirely until
small-institutional tier.

### 1.6 CryptoSlate

Free RSS at https://cryptoslate.com/feed/ per Feedspot. Editorial
strength on Asian markets and DeFi. Latency under 15 minutes.

Verdict: immediate v1 win.

### 1.7 Blockworks (RSS) and Blockworks Research

Editorial RSS at https://blockworks.co/feed (free) covers Blockworks's
news desk, which is one of the strongest US institutional desks. The
companion product Blockworks Research is a paid analyst-driven
research subscription. Blockworks does not publish a price card
publicly; the product page funnels through `researchsupport@blockworks.co`
[Blockworks Research support](https://www.blockworksresearch.com/support).
Public reports of seat pricing range $300 to $1,500/month depending
on team size and tier; treat as small-institutional only.

Verdict: free editorial RSS is an immediate v1 win. Research is a v3
small-institutional pick competitive with Messari Pro and Delphi.

### 1.8 Crypto Briefing

Free RSS at https://cryptobriefing.com/feed/ per the publisher's own
RSS landing page [Crypto Briefing feeds](https://cryptobriefing.com/feeds/).
Mid-tier US editorial outlet, useful as a fourth or fifth corroborator
when a story is breaking and you want multi-source confirmation
without paid aggregation.

Verdict: optional v1 win; add if dedup logic in the news pipeline can
handle the increased volume.

### 1.9 Messari News API

Messari covers news as part of its broader Pro API, which includes
AI-summarised coverage from 500+ sources, asset tagging, and topic
clustering [Messari API page](https://messari.io/api). Free tier rate
limit is 20 requests/minute; news endpoints are part of the paid Pro
plan. Pricing is sales-gated; Messari does not publish a price card
[Messari pricing](https://messari.io/pricing). Industry-reported Pro
pricing was historically around $30/month for a single user in
2022-2023, but the product has shifted toward enterprise and the
single-user tier has been progressively de-emphasised. Treat
self-serve Pro pricing as $30 to $60/month per seat in 2026 if it
exists, with the news endpoints potentially as a paid add-on, and
sales-quoted enterprise tiers above that.

Verdict: skip in v1. Strong v2 candidate at the $50/month entry tier
specifically for the asset-tagged news endpoint, which solves the
hardest part of the news pipeline (knowing which coin a headline is
about).

### 1.10 NewsAPI.org

The Developer (free) plan is restricted to non-production use, capped
at 100 requests/day with delayed articles, and explicitly forbids any
production or staging deployment per their pricing terms
[NewsAPI pricing](https://newsapi.org/pricing). The first paid tier
(Business) is $449/month, which is severely overpriced for crypto-only
use given that DeFi-native aggregators offer asset-tagged news at a
fraction of the cost. There is no crypto-specific filter; you query
with text terms ("bitcoin", "ethereum") and get general-news matches
which include heavy noise from non-crypto contexts (e.g. "ethereum"
matched in fashion or chemistry articles is rare but real).

Verdict: skip in v1 and v2. Free tier ToS makes it unusable in
production; paid tier is bad value for crypto specifically. Use the
crypto-native aggregators (CryptoCompare, Messari, LunarCrush) instead.

### 1.11 Google News RSS with crypto query

Google News exposes an undocumented but stable RSS endpoint:
`https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+crypto&hl=en-US&gl=US&ceid=US:en`.
Per the NewsCatcher reverse-engineering writeup
[Google News RSS parameters](https://www.newscatcherapi.com/blog-posts/google-news-rss-search-parameters-the-missing-documentaiton),
the query supports `intitle:`, `when:1h`, geo and language scoping,
and Boolean operators. Free, no auth, no rate limit Google publishes
but anecdotally polite polling at 5-15 minutes is fine. Latency is
typically 5-30 minutes after Google indexes the source article. The
huge upside is breadth: it surfaces stories from regional outlets and
small specialist blogs that none of the crypto-native RSS feeds carry.
The downside is noise; "bitcoin" matches a lot of low-quality
newsletter regurgitation.

Verdict: immediate v1 win when paired with a quality filter (whitelist
of source domains). Especially useful for catching breaking
non-English stories before the US desks pick them up.

### 1.12 Reuters and Bloomberg crypto coverage

Both publish RSS for their crypto desks (Reuters: section feeds at
https://www.reuters.com/arc/outboundfeeds/rss/; Bloomberg's crypto
coverage is paywalled with no free RSS for full articles). Reuters is
free at the headline level via RSS. Bloomberg full feeds require a
Bloomberg Professional Service subscription which starts around
$2,500/month per seat (publicly reported, not on a marketing page).
Refinitiv (formerly Thomson Reuters Eikon, now LSEG Workspace)
similarly five-figure annual.

Verdict: Reuters RSS is a free v1 win for institutional-grade
headlines. Bloomberg/Refinitiv are skip-entirely for any tier the
operator is realistically funding; their pricing is built for trading
desks, not research.

### Recommended additions for v2 (news section)

1. Wire all of The Block, Decrypt, Bitcoin Magazine, CryptoSlate,
   Blockworks editorial, and Reuters crypto RSS today. Combined cost:
   zero. Combined latency: under 15 minutes. Effect: triples the news
   surface area without spending a dollar.
2. Google News RSS with curated query and source whitelist. Zero cost.
   Catches regional and specialist stories the US desks miss.
3. Messari Pro at $30 to $60/month for the asset-tagged news endpoint.
   This is the single highest-value news upgrade because it solves
   ticker disambiguation upstream.

---

## 2. Sentiment and social

The current pipeline does no sentiment quantification beyond
CryptoPanic's now-dead vote counts and the Reddit hot listing's score
field. Building real sentiment signal requires either pulling from a
dedicated provider or running NLP locally on raw text. Both have cost.

### 2.1 LunarCrush

Tiered subscription with free, Individual/Pro, Business, and
Enterprise tiers per the LunarCrush pricing page
[LunarCrush pricing](https://lunarcrush.com/pricing). The free tier
gives basic dashboard access and very limited API; serious API usage
requires a paid plan. Individual plans historically were around
$24/month, Builder/Business around $40 to $99/month for higher rate
limits, Enterprise quoted by sales. LunarCrush exposes Galaxy Score,
AltRank, social volume time series, news feeds, and influencer
metrics across thousands of assets. Latency is near real-time on
paid tiers. Integration is REST.

Verdict: skip in v1. Strong v2 entry pick at the Individual/Builder
tier (around $24 to $40/month) for the Galaxy Score and social-volume
time series.

### 2.2 Santiment

Tiered: Sanbase Pro and Max plans, with a free tier per
[Santiment Sanbase plans](https://academy.santiment.net/products-and-plans/sanbase-plans/).
Restricted metrics on the free and Pro plans run with a 30-day lag;
Max removes the lag. Pricing public on Sanbase: Pro is around
$49/month, Max is around $249/month, with a 20% discount for paying
in SAN tokens. API access is metered separately under SanAPI plans
[Santiment API plans](https://academy.santiment.net/products-and-plans/sanapi-plans/).
Coverage as of February 2026 includes BTC, ETH, XRPL, BNB Chain, BCH,
LTC, ADA, DOGE, ICP, MATIC, AVAX (ERC20), Optimism, Arbitrum.
Santiment uniquely combines on-chain and social into single composite
metrics (e.g. social volume divided by network growth), which is the
real differentiator vs LunarCrush.

Verdict: skip in v1. Strong v2 pick at $49/month Pro for the
on-chain plus social blend, especially the network-growth and
whale-transaction-count metrics that augment the v1 onchain provider.

### 2.3 The Tie

Institutional-only, sales-gated pricing
[The Tie sentiment API](https://www.thetie.io/solutions/sentiment-api/).
The Tie powers sentiment screens at over 150 institutional clients
including hedge funds and market makers. Point-in-time social data
back to 2017 across 1000+ tokens. Pricing is reportedly five-figure
annual minimum.

Verdict: skip entirely until $2k+/month institutional tier. Worth
knowing about because if the operator ever talks to a quant fund, The
Tie will come up.

### 2.4 Augmento

Still alive in 2026, headquartered in Düsseldorf, owned by Postera
Capital since 2020 [Augmento home](https://augmento.ai/). Sentiment
score across 25+ assets, 93 topics, derived from X, Reddit, and
Bitcointalk via a hybrid ML plus linguistic-analysis approach trained
on 32k manually labelled posts. Pricing is sales-only and the public
site is light on a buy button, suggesting the product is mostly sold
B2B. Their GitHub `augmento-ai/quant-research` exposes example data
quickstarts which suggests a researcher-friendly tier exists.

Verdict: skip in v1 and v2. Niche; LunarCrush and Santiment cover the
same ground with cleaner self-serve pricing.

### 2.5 Kaiko social sentiment

Kaiko historically positioned itself as market-data-first; their
sentiment add-on is part of the broader Analytics product. No public
price card; minimum institutional spend per Vendr data is around
$9.5k/year with median around $28.5k/year
[Vendr Kaiko pricing](https://www.vendr.com/buyer-guides/kaiko).

Verdict: skip until small-institutional. Not the right product if
sentiment is what you want; The Tie or LunarCrush are purpose-built.

### 2.6 CoinGecko social score (free, existing key works)

The CoinGecko Demo API includes social score fields on the
`/coins/{id}` endpoint (Twitter followers, Reddit subscribers,
sentiment up/down votes from the CoinGecko platform's own users).
Already covered in `API_RESEARCH.md` 1.7. Coarse but free and
already in budget for the existing CoinGecko key.

Verdict: light v1 win. Already nominally in scope.

### 2.7 Twitter / X firehose via official API v2

X replaced its tiered subscription model with pay-per-use as the
default on 2026-02-06, and the legacy Basic ($200/month) and Pro
($5,000/month) plans are no longer available to new sign-ups
[X API pricing 2026](https://postproxy.dev/blog/x-api-pricing-2026/).
New developers default to pay-per-use: $0.005 per post read (rising
to $0.001 per resource for owned reads from 2026-04-20 per
[X API pricing update April 2026](https://devcommunity.x.com/t/x-api-pricing-update-owned-reads-now-0-001-other-changes-effective-april-20-2026/263025)),
$0.01 per post created (rising to $0.015 in April 2026), capped at
2 million reads per month under the pay-per-use cap. There is no free
tier for production use. For our purposes (read-only sentiment
ingestion), the math is: ingesting 100k posts/day costs around
$500/day at the new $0.005 rate, which is wildly out of budget and
also exceeds the pay-per-use cap.

Verdict: do not build directly on X API for any tier under
$2k/month. The economics make it strictly worse than LunarCrush or
Santiment, both of which already pre-process X data and resell it as
sentiment metrics for one to two orders of magnitude less cost.

### 2.8 Reddit JSON (already wired) and OAuth

Already wired in `news/sources.py`. Per
[Reddit API rate limits guide 2026](https://painonsocial.com/blog/reddit-api-rate-limits-guide),
unauthenticated requests are capped at 10 QPM with frequent 429s, and
OAuth-authenticated apps get 100 QPM under the free tier intended for
personal and academic use. The 2023 commercial pricing crackdown is
still in effect: any commercial use requires a paid agreement with
Reddit, which is sales-quoted and reportedly five-figure annual
minimum [Reddit API cost guide 2026](https://painonsocial.com/blog/how-much-does-reddit-api-cost).
For our research-only use, OAuth registration with `praw` is the
sustainable path; raw JSON suffix scraping continues to work but with
escalating fragility.

Verdict: keep the JSON suffix v1 wire as-is, but plan to migrate to
OAuth via `praw` as soon as a non-trivial sentiment pipeline lands.
Migration is cheap (one PR) and gets you to 100 QPM safely.

### 2.9 Glassnode social on-chain blend

Glassnode does not have a standalone social product; their "social"
signals are derived from on-chain entity behaviour (e.g. whale
transaction count, holder count by cohort). Covered under section 3.

### 2.10 Telegram channels and Discord scraping

Project-specific Telegram channels and Discord servers are where
genuine alpha sits for early-stage protocol news. Telegram exposes a
Bot API (free) for channels you can join; Discord requires a bot
account in each server which is feasible but ToS-restricted for
unattended scraping. Both are legally grey for sentiment ingestion.
Telegram's ToS permits read-only scraping of public channels; Discord's
ToS explicitly forbids selfbots and restricts automated reading.

Verdict: defer entirely. Operationally heavy, legally risky, and the
signal is dominated by manipulators promoting their bags. If the
operator decides to chase the alpha, do it via paid services like
Kaito or Cookie3 that have already negotiated the legal piece, not
DIY scraping.

### Recommended additions for v2 (sentiment section)

1. LunarCrush Builder tier (around $40/month) for Galaxy Score and
   social-volume time series. Best entry-tier sentiment signal.
2. Santiment Pro ($49/month) for the on-chain-plus-social blend,
   specifically the network growth and whale transaction metrics.
3. Migrate Reddit to OAuth with `praw` for free; no incremental cost.

---

## 3. On-chain analytics (the institutional signal)

The largest category by both data volume and price tag. The v1 stack
relies on Blockchair and Etherscan free tiers, both of which can give
basic transaction counts but cannot give labelled exchange netflow,
which is the highest-information on-chain signal per
`API_RESEARCH.md` 1.11.

### 3.1 Glassnode

Three tiers per [Glassnode pricing](https://glassnode.com/pricing/studio):
Standard (free, web dashboard only, T1 metrics at 24h resolution),
Advanced ($29/month, T1 plus T2 metrics at 1h resolution, but
critically API access is NOT included by default), and Professional
($999/month, all three tiers of metrics at up to 10-minute resolution,
with API access available as an add-on per
[Captain Altcoin Glassnode review 2026](https://captainaltcoin.com/glassnode-review/)).
Enterprise is custom.

Tier 1 metrics (free): active addresses, block height, supply, UTXO
count, hash rate, sending/receiving address count. Tier 2 metrics
(Advanced): exchange netflow, exchange balance, transfer volumes,
HODL waves, supply distribution by cohort. Tier 3 metrics
(Professional): SOPR variants, MVRV variants, NUPL, realised cap,
dormancy, entity-adjusted flows, miner cohort flows, the genuinely
load-bearing alpha-bearing metrics per
[Glassnode SOPR docs](https://docs.glassnode.com/guides-and-tutorials/metric-guides/sopr).

Honest cost-vs-value read: the $29/month Advanced tier is the
sweet spot for retail because exchange netflow is a tier-2 metric and
it dramatically improves the on-chain signal. But you cannot use the
API at $29/month; you must scrape from the dashboard, which is
fragile and probably violates ToS. The genuinely-API-usable tier
starts at $999/month Professional, which is a $300+ jump above the
"serious retail" tier we benchmark below.

Verdict: skip in v1 (already concluded in `API_RESEARCH.md`). At v2
$300/month budget, the right play is NOT Glassnode (too expensive)
but rather CryptoQuant or self-built proxies. At v3 $2k+/month
budget, Glassnode Professional is the load-bearing pick.

### 3.2 CryptoQuant

Tiered per [CryptoQuant pricing](https://cryptoquant.com/pricing).
Free Basic tier is web-only with limited metrics. Advanced is around
$29/month for higher-quality dashboard access. Premium is around
$99/month and starts to include API access. Professional and Enterprise
are higher tiers ($799/month for Premium API was the historical
2024-2025 figure cited in `API_RESEARCH.md` 1.12; CryptoQuant has
restructured since with the lower-priced Premium tier including some
API access). Per
[Oreate AI CryptoQuant pricing review](https://www.oreateai.com/blog/unlocking-crypto-insights-a-look-at-cryptoquant-api-pricing-and-value/395dcb07aaf0e23b76f45bccd01a7bd4),
the Premium API tier has come down meaningfully and is now in the
$99 to $200/month range for retail-aimed access.

CryptoQuant's strength is exchange-flow data and miner data: their
exchange inflow/outflow product is competitive with Glassnode's at a
materially lower price point, and their miner reserve metrics are the
best in the market. Weakness: their entity-adjusted metrics are
shallower than Glassnode's.

Verdict: skip in v1. At v2 $300/month budget, CryptoQuant Premium
($99 to $200/month) is the highest-value on-chain spend, materially
beating Glassnode's API-bearing tier on cost.

### 3.3 Nansen

Repriced in 2026: now just two plans per
[Nansen pricing](https://www.nansen.ai/plans), Free and Pro. Pro is
$49/month annual or $69/month monthly per
[Nansen review 2026](https://chainplay.gg/blog/nansen-review/). The
old Pioneer ($129/month) and Professional ($999+/month) tiers are
retired; Pro now includes all premium features previously paywalled,
including Smart Money labels for 10k+ wallets, alerts, and full
dashboard access. Nansen also opened a pay-per-call API model in April
2026 per
[Crowdfund Insider Nansen pay-per-call](https://www.crowdfundinsider.com/2026/04/274494-blockchain-analytics-firm-nansen-enhances-onchain-data-access-with-pay-per-call-model/),
which is friendly to programmatic consumption without committing to a
seat license.

Smart Money labels (10k profitable wallets, classified by cohort
including VCs, traders, funds) are the unique product and very hard
to replicate without a labelling team. Coverage spans Ethereum,
Solana, Base, Arbitrum, Polygon, BNB.

Verdict: skip in v1 if budget is zero. Strong v2 pick at $49/month for
the Smart Money dashboard, and very strong v2 pick if pay-per-call
API is in scope.

### 3.4 Arkham Intelligence

Free tier includes entity labels, which is the unique and notable
fact: Arkham is the only major analytics platform with a no-cost tier
that exposes labelled addresses for major entities (exchanges, funds,
known whales). Per
[Arkham API docs](https://intel.arkm.com/api/docs), the public
intelligence platform is free to use; the API has been gated behind a
pilot program historically and as of late 2026 is moving to a public
self-serve tier per
[The new Arkham API](https://info.arkm.com/announcements/the-new-arkham-api).
Detailed price cards for the API itself are not yet on a public page;
sales-quoted for high-volume.

Arkham's free entity labels mean a v1 implementation can do something
Glassnode-like (label-based exchange flow tracking) for ETH, BTC,
SOL, and several other chains at zero cost, with the caveat that the
API has rate limits and the label coverage is broader on EVM than
non-EVM.

Verdict: immediate v1 win for entity labels. Sign up, pull the labels
into a local SQLite table, use them to compute exchange-flow proxies
on top of the Etherscan and Blockchair raw data the v1 stack already
fetches. This is the highest-impact free addition in this entire doc.

### 3.5 Dune Analytics

Free tier with 2,500 credits/month and API access included by default
per [Dune pricing](https://dune.com/pricing). Pay-as-you-go at
$5.00/100 credits beyond the free allotment. Paid tiers (Analyst, Plus,
Enterprise) offer lower per-credit rates and unlimited concurrent
executions.

A simple daily aggregation query (active addresses for one chain,
30-day window) is roughly 1 to 5 credits; a full-history backfill is
hundreds. 2,500 credits supports several daily-refresh queries
comfortably. Coverage spans EVM chains, Solana, Bitcoin, and a growing
set of L2s.

Verdict: already recommended in `API_RESEARCH.md` 1.18. Confirmed
strong free-tier value. Pay-as-you-go pricing is friendly for bursty
backfill workloads.

### 3.6 Token Terminal

API access available per their product page
[Token Terminal API](https://tokenterminal.com/products/api). No
public price card; sales-quoted. Public reports put self-serve API
pricing in the $1,000 to $3,000/month range as of late 2025. The
strength is normalised revenue, fees, and earnings data per protocol,
which is the closest crypto has to an equity-research fundamentals
dataset. Free dashboard exists.

Verdict: skip until small-institutional. The fundamentals data is
genuinely useful but the price point puts it in the $2k/month bucket
rather than the $300/month bucket.

### 3.7 Coin Metrics

Two tiers: Community (free, HTTP-only, 10 requests/6s, 1,000
requests/10min, last 24h history at higher frequencies per
[Coin Metrics docs](https://gitbook-docs.coinmetrics.io/access-our-data/api))
and Pro/Network Data Pro/Market Data Pro (institutional, sales-only).
Network Data Pro is the institutional-reference dataset for on-chain
metrics across the top assets. Pricing is opaque; per Vendr-style
buyer reports, institutional Coin Metrics pricing is comparable to
Kaiko, in the $10k-50k/year range.

Verdict: Community tier is a v1 backstop for last-24h spot price
sanity-check. Pro is skip until small-institutional ($2k+/month
budget); even then, Glassnode tends to win on metric breadth at
similar price.

### 3.8 Messari Pro (on-chain side)

Same pricing as the news side (see 1.9): around $30 to $60/month
self-serve if the tier exists, sales-quoted enterprise above. Messari's
on-chain coverage is broader (200+ DeFi protocols) but shallower on
each than Glassnode or CryptoQuant.

Verdict: same as for news; v2 pick at $50/month if the asset profiles
and protocol metrics are useful alongside the news endpoints.

### 3.9 DeFi Llama

Free, no auth, no rate limit for normal traffic per
[DefiLlama API docs](https://api-docs.defillama.com/). Pro tier is
$300/month for higher rate limits and additional endpoints per
[DefiLlama pricing](https://docs.llama.fi/pro-api). The free tier is
remarkably generous: TVL by protocol (50,000+ pools tracked),
stablecoin supply (around $310B tracked across all chains as of early
2026), yields, prices, fees, all queryable without a key.

DeFi Llama is the cleanest free institutional-grade source in the
entire crypto data landscape. Wire all relevant endpoints in v1.

Verdict: immediate v1 win. The Pro tier is unnecessary unless you are
building a paid product on top.

### 3.10 Etherscan / Solscan / BscScan / Polygonscan

Etherscan API V2 launched 2025, unifying 60+ EVM chains under a single
key per
[Etherscan API V2 multichain](https://info.etherscan.com/etherscan-api-v2-multichain/).
Free tier is 5 calls/sec, 100,000 calls/day per
[Etherscan rate limits](https://docs.etherscan.io/resources/rate-limits),
with the Nov 2025 free-tier reduction limiting some chains (Avalanche,
Base, BNB Chain, Optimism on free tier are restricted) per
[Etherscan free tier changes Nov 2025](https://info.etherscan.com/whats-changing-in-the-free-api-tier-coverage-and-why/).
ETH and Polygon mainnets remain on free tier.

Solscan: free tier covers basic public endpoints; Pro API starts
around $50 to $100/month per
[Solscan API plans](https://solscan.io/apis). The free Solana
coverage is meaningfully thinner than the equivalent Etherscan
coverage of EVM chains; Solana on-chain in v1 effectively requires
either Helius or Solscan Pro to be useful.

Verdict: Etherscan v2 is already covered in `API_RESEARCH.md`;
confirmed free-tier reductions are real. Solscan free is too thin for
production; if Solana on-chain matters, jump to Helius (3.11) instead.

### 3.11 Helius (Solana)

Free tier: 1M monthly credits, 10 RPC req/s, 2 DAS and Enhanced API
req/s, standard WebSockets, no credit card required per
[Helius pricing](https://www.helius.dev/pricing). Paid tiers:
Developer ($49/month), Business ($499/month), Professional
($999/month). Dedicated nodes start at around $2,900/month.

Helius is the best Solana RPC and indexed-data provider; their
Enhanced API gives parsed transaction data, NFT and DeFi-aware
endpoints, and webhook delivery. The free tier is genuinely usable
for v1 because daily polling for SOL on-chain stats is well within
1M credits.

Verdict: immediate v1 win for Solana on-chain. Wire the Enhanced API
free tier and the address-balance and transaction endpoints; this
fills the Solana gap that Blockchair cannot cover.

### 3.12 Goldsky / Subsquid / The Graph

Goldsky: $0.05/hr workers plus $4 per 100k entities, with a free
Starter tier per [Goldsky pricing](https://goldsky.com/pricing).
The Graph: $1.50 to $2 per 100k queries with 100k free per month per
[Subgraph Studio pricing](https://thegraph.com/studio-pricing/).
Subsquid: pricing is sales-quoted on the indexer side; the SDK is
open-source.

These are subgraph-indexing platforms, designed for protocol-level
queries (Uniswap pools, Aave positions, NFT mint events). They are
not the right tool for active-address counts or basic on-chain stats.
Pick one only when a DeFi-protocol-level signal gets added to the
research stack (e.g. "TVL change on a specific Aave market").

Verdict: skip in v1 and v2. Document for v3 if the signal set grows
to include protocol-level DeFi metrics.

### Recommended additions for v2 (on-chain section)

1. Arkham entity labels (free) plus DeFi Llama (free) plus Helius
   free tier for Solana. All free, all today.
2. CryptoQuant Premium ($99 to $200/month) for exchange flows and
   miner data. Best $200-and-under on-chain spend.
3. Nansen Pro ($49/month) for Smart Money labels. Cheap and
   differentiated.

---

## 4. Derivatives data (funding, OI, liquidations, options)

Funding rate and open interest are already wired via ccxt against
Binance and Bybit per `API_RESEARCH.md` 1.1, 1.2, 1.5. The v1 gaps
are liquidations history (REST is dead, WebSocket capture deferred)
and options (no v1 wiring at all).

### 4.1 Coinglass

Pricing per [Coinglass pricing](https://www.coinglass.com/pricing).
Free tier provides real-time price tracking, liquidation data, funding
rates, OI charts, basic analytics on the website but the API free
quota is severely limited (around 50 calls/day documented). Paid:
Hobbyist around $29/month with limited API rate, Standard around
$299/month with 300 req/min and 150+ endpoints. Annual savings $72 to
$2,160 vs monthly.

Coinglass's value vs DIY: it aggregates derivatives data across 30+
exchanges in a single API surface, and provides liquidation history
(which Binance gutted from REST). For our universe of 10 names
across the top 4 exchanges, you can replicate most of the funding
rate and OI aggregation by summing ccxt calls yourself; the unique
value is liquidations history and the long/short ratio aggregates.

Verdict: skip the free tier (too tight). At v2 $300/month budget,
Coinglass Hobbyist ($29/month) is a reasonable add for liquidation
history specifically. Standard ($299/month) is overpriced relative to
DIY ccxt aggregation for everything except liquidations.

### 4.2 Laevitas

Premium plan around $50/month per public marketing material, with
sales-quoted enterprise tiers above. Per
[Laevitas options API](https://docs.laevitas.ch/options/analytic),
covers complete option chains, implied volatility surfaces, Greeks,
trade flows including blocks and strategies, across Deribit, Binance,
OKX, Bybit, Hyperliquid. Free tier exists for the dashboard; API
access starts at the paid tier.

Verdict: best mid-market options data product. Skip in v1 (no options
signal in scope). Strong v2 pick at $50/month if options signals get
added.

### 4.3 Velo Data

Centralised exchange data platform with free dashboard tier focused
on derivatives per [Velo Data](https://velodata.app/). API pricing
is not fully on a public price card; pricing details for institutional
API are sales-quoted. The free product is unusually generous
(charts, futures, options, market view, CME data) and competes with
Coinglass at the dashboard level.

Verdict: free dashboard is useful as a research aid even without
wiring. API skip until v3.

### 4.4 Skew (now part of Coinbase)

Skew was acquired by Coinbase in 2021 and folded into Coinbase
Institutional analytics. The public Skew dashboards were retired;
some derivatives metrics survived as Coinbase Prime data products,
which require a Coinbase Prime account. No publicly accessible API.

Verdict: dead as a public source. Skip.

### 4.5 Amberdata

Institutional, enterprise pricing per
[Amberdata pricing](https://www.amberdata.io/pricing). Their AD
Derivatives product covers futures, perps, and options across crypto
and crypto-linked equities with normalised data deep enough to
support volatility surface construction. Delivery via WebSockets,
AWS S3, REST, Snowflake. Pricing reportedly five-figure annual
minimum.

Verdict: skip until small-institutional ($2k+/month). Genuinely
strong if budget exists, but Laevitas covers most of the same
ground for two orders of magnitude less.

### 4.6 Kaiko (derivatives)

Same pricing as the broader Kaiko product (see section 5.2 below):
$9.5k to $55k/year per Vendr data. Kaiko's derivatives coverage is
strong but not differentiated above Amberdata.

Verdict: skip until small-institutional.

### 4.7 Direct exchange WebSocket feeds

Free across Binance, Bybit, OKX, Deribit. Binance's
`wss://fstream.binance.com/ws/!forceOrder@arr` is the canonical
liquidation stream (referenced in `API_RESEARCH.md` 1.2). Deribit
WebSocket exposes options chains, mark prices, IV. OKX WebSocket
exposes the same plus their unique cross-margin features.

The work to wire these is non-trivial: WebSocket consumption requires
a long-running process, message buffering, reconnect logic, and a
local store. ccxt.pro (now merged into ccxt under MIT license per
[CCXT Pro merge announcement](https://github.com/ccxt/ccxt/issues/15171))
makes this much easier; the historical concern about ccxt.pro being
a paid commercial license is no longer accurate as of 2026.

Verdict: free; high engineering cost. Defer until liquidation or
options signals are explicitly in scope. When they are, ccxt's
unified WebSocket interface (now free under MIT) is the right
abstraction.

### 4.8 Deribit options API

Free public REST and WebSocket per
[Deribit API docs](https://docs.deribit.com/). Public endpoints
expose option chains, mark prices, Greeks, IV per option, the DVOL
index. No auth required for market data. Deribit is the dominant
crypto options venue and the most useful single source for options
data without paying for an aggregator.

Verdict: immediate v1 win when options signals get added. Free, well
documented, mature. Will eat engineering time to consume the
WebSocket properly.

### Recommended additions for v2 (derivatives section)

1. Coinglass Hobbyist ($29/month) for liquidation history. Cheap
   replacement for the dead Binance REST endpoint.
2. Deribit public API (free) for options chains and IV when options
   signals get added. No spend; just engineering time.
3. ccxt's WebSocket interface (now free) for live OI and funding plus
   liquidation stream consumption. No spend; engineering time only.

---

## 5. Market microstructure and level-2 data

Pure microstructure (full-depth orderbooks, tick-level trades) is
where free tiers genuinely fall off and paid data becomes mandatory
at scale. The v1 stack does not currently consume L2; this section is
forward-looking.

### 5.1 CryptoCompare (now CoinDesk Data)

Free tier with 50 to 200 requests/hour (varies by endpoint and
non-commercial vs commercial designation). Paid commercial plans
$80 to $200/month per Medium reviewer reports
[Top crypto data APIs comparison](https://medium.com/coinmonks/top-5-cryptocurrency-data-apis-comprehensive-comparison-2025-626450b7ff7b);
custom enterprise above. CoinDesk acquired CryptoCompare in 2022 and
the brand has been folded into CoinDesk Data, with the original
CryptoCompare API endpoints still operational at min-cryptocompare.com.

Verdict: free tier is fine for sanity-check and some news access;
paid tier is reasonably priced compared to peers but still inferior
to going direct via ccxt for spot data. Skip unless you need the
historical archive (back to 2014, useful for long-window backtests).

### 5.2 Kaiko L2 and trades

Sales-quoted; Vendr buyer data shows minimum $9,500/year, median
$28,500/year, maximum $55,000/year per
[Vendr Kaiko buyer guide](https://www.vendr.com/buyer-guides/kaiko).
Kaiko is the institutional-reference market data provider; their L2
and trades datasets cover 100+ exchanges, 35,000+ pairs.

Verdict: skip until small-institutional ($2k+/month) and even then
only if microstructure signal is explicitly in scope.

### 5.3 Tardis.dev

Per [Tardis.dev](https://tardis.dev/), high-frequency historical
tick-level data for cryptocurrency markets including order book
updates, trades, quotes, OI, funding, liquidations, options chains
across BitMEX, Deribit, Binance, OKX, Huobi, Bitfinex, Kraken,
Coinbase, Gemini, and others. Public pricing on the site shows a
free tier with limited replay access, paid tiers starting around
$59/month for individual subscribers, and $400+/month for higher
volumes. Most-recent-data latency is approximately 6 minutes; CSV
files for a given day are available next-day around 06:00 UTC.

Tardis is the single best-value historical microstructure source for
backtesting, materially undercutting Kaiko on price for a
research-quality (vs production-feed) use case.

Verdict: skip in v1 (no L2 signal). Strong v2 pick at $59/month if
backtesting on tick data becomes important. Dramatically better value
than Kaiko for research workloads.

### 5.4 Direct exchange WebSocket for live L2

Same as 4.7 above. Free, requires engineering time.

### 5.5 ccxt.pro (WebSocket)

Now merged into ccxt and free under MIT per
[CCXT Pro merge](https://github.com/ccxt/ccxt/issues/15171). The
historical $200/month commercial license referenced in
`API_RESEARCH.md` is no longer accurate as of 2026.

Verdict: revise the v2 stack table in `API_RESEARCH.md` accordingly.
ccxt WebSocket is now free.

### Recommended additions for v2 (microstructure section)

1. ccxt WebSocket interface for live L2 if needed. Free.
2. Tardis.dev paid tier ($59/month) for backtesting on tick data.
   Best price-to-value in microstructure.
3. Kaiko skip until institutional.

---

## 6. Macro and DeFi context

### 6.1 FRED (already used, free)

Already covered comprehensively in `API_RESEARCH.md` 1.16. DXY proxy
(DTWEXBGS), 10y nominal (DGS10), 10y real (DFII10), M2 (M2SL), Fed
balance sheet (WALCL), VIX (VIXCLS). 120 requests/minute, no daily
cap. Government infrastructure, high uptime. Recommended.

### 6.2 DeFi Llama (free)

Already covered in 3.9 above. Stablecoin supply, TVL by chain, yield
aggregation across 50,000+ pools. The free tier is generous enough
that Pro ($300/month) is unnecessary at v1 or v2 scale.

### 6.3 Coin Metrics Network Data Pro

Already covered in 3.7 above. Institutional-only.

### 6.4 Skew (Coinbase)

Dead as public source per 4.4 above.

### 6.5 CB Insights crypto

CB Insights publishes a crypto research subscription. Pricing is
enterprise-sales-only, public reports put it at $50,000+/year per
seat. The product is venture/private-market intelligence rather than
real-time market data.

Verdict: skip entirely. Wrong product for an investment research
stack. Useful only if the operator is fundraising or doing primary
research on private crypto companies.

### 6.6 Glassnode "macro studio"

Glassnode publishes aggregated regime indicators (e.g. their Bitcoin
Risk Signal, NUPL-based market cycle indicators) under their
Professional and Enterprise tiers. Same pricing as 3.1 above.

Verdict: only relevant once Glassnode Professional is in budget.

### Recommended additions for v2 (macro section)

1. FRED already wired (recommended in v1). Zero cost.
2. DeFi Llama (free) for stablecoin supply and TVL macro panel. Wire
   in v1.
3. Skip everything else until v3.

---

## 7. Institutional research feeds (the qualitative layer)

The qualitative research layer is mostly free at the headline level
because the major institutional desks publish for marketing reach.
Paid only kicks in for deeper proprietary research.

### 7.1 Galaxy Digital Research

Free PDFs and weekly research notes published at
https://www.galaxy.com/research and distributed via newsletter. Per
[ChainCatcher 2026 outlook coverage](https://www.chaincatcher.com/en/article/2232985),
Galaxy's 2026 outlook was released in January and continues a pattern
of free-PDF distribution. Easy to ingest via the page's RSS or by
scraping the listing.

Verdict: free, weekly, immediate v1 win for the qualitative layer.

### 7.2 Coinbase Institutional Research

Free reports per [Coinbase Institutional](https://www.coinbase.com/institutional/research-insights/research/insights-reports).
Coinbase One members and Institutional clients get 7-day early access;
public release follows on a 7-day lag. Frequency: weekly insights,
monthly deep dives, quarterly outlooks.

Verdict: free, weekly, immediate v1 win. Subscribe to the newsletter
or scrape the listing.

### 7.3 Bitwise Research

Free reports at https://bitwiseinvestments.com/research and distributed
via newsletter. Bitwise's 2026 top-10-predictions report is free per
the same ChainCatcher coverage.

Verdict: free, monthly cadence, immediate v1 win.

### 7.4 Grayscale Research

Free at [Grayscale research reports](https://research.grayscale.com/reports).
Their 2026 Digital Asset Outlook was published January 2026 free
[Grayscale 2026 outlook](https://research.grayscale.com/reports/2026-digital-asset-outlook-dawn-of-the-institutional-era).
Quarterly deep dives plus monthly market commentary.

Verdict: free, immediate v1 win.

### 7.5 Messari Pro Research

Paid; covered in 1.9 and 3.8 above. The research layer (vs the news
API layer) is part of the same Pro subscription. Strong asset
profiles, sector reports, quarterly state-of-x reports.

Verdict: v2 pick at $50/month; good value alongside the news API.

### 7.6 Delphi Digital

Paid Delphi Pro per [Delphi Pro plans](https://members.delphidigital.io/select-plan).
Pricing on the public select-plan page; reported as around
$59/month for a personal plan with 15% discount on annual. Strong on
DeFi protocol-level research and ecosystem deep dives, particularly
Solana and L2s. Their Year Ahead 2026 reports are paywalled.

Verdict: skip in v1. v2 pick at around $50 to $60/month if the
operator wants deep DeFi protocol research alongside Messari.

### 7.7 The Defiant

Free newsletter plus paid Pro tier at
https://thedefiant.io/. Pro subscription is reportedly around
$30/month and includes proprietary research and a Discord channel.

Verdict: free newsletter is useful; Pro is optional at v2 if DeFi
focus is in scope.

### 7.8 Blockworks Research

Covered in 1.7 above. Sales-gated; small-institutional pricing.

### 7.9 Arcane Research / K33

Arcane Research merged into K33 in 2023. K33 publishes a mix of free
newsletter content and paid research at https://k33.com/. Paid tiers
reported in the $30 to $100/month range for individual access; some
reports remain free. Strong on Nordic and European crypto markets,
which is unique vs the US-dominated competitive set.

Verdict: free newsletter is a v1 win for European market context.
Paid tier optional v2 pick.

### Recommended additions for v2 (research section)

1. Galaxy, Coinbase Institutional, Bitwise, Grayscale, K33 free
   research, all subscribed to via newsletter or scraped from the
   research listing pages. Zero cost.
2. Messari Pro ($30 to $60/month) for asset profiles and sector
   reports, alongside the news API value.
3. Delphi Pro ($59/month) only if DeFi protocol research is the
   priority.

---

## 8. Whale and entity tracking

### 8.1 Whale Alert

Free Twitter feed at @whale_alert plus paid API per
[Whale Alert pricing](https://developer.whale-alert.io/pricing.html).
The Alerts and Analytics paid plan is $29.95/month for real-time
custom alerts. The Enterprise API is sales-quoted and provides
millions of transactions/day with 30 days of historical data per
chain; historical archives available at $499/year/blockchain.

Verdict: free Twitter feed is an immediate v1 win as a fallback whale
signal (consume via Twitter scrape with light parsing). $30/month
paid tier is overpriced for what it gives over the free Twitter feed
unless real-time programmatic alerting is required.

### 8.2 Arkham (whale and entity tracking)

Already covered in 3.4 above. Free entity labels and free dashboard
search make Arkham the highest-value whale tracker for v1.

Verdict: immediate v1 win.

### 8.3 Nansen Smart Money

Already covered in 3.3 above. $49/month Pro now includes Smart Money
labels for 10k profitable wallets, which is the closest thing to
"alpha discovery via wallet copy-tracking" available retail.

Verdict: v2 pick at $49/month.

### 8.4 Lookonchain

Free Twitter at @lookonchain (284k followers, multiple posts/day per
[Altcoin Buzz on-chain Twitter](https://www.altcoinbuzz.io/bitcoin-and-crypto-guide/top-5-twitter-accounts-to-learn-about-on-chain-research/)),
no public API. Manual or scraped consumption only.

Verdict: free, immediate v1 win as a Twitter-feed input. Pair with
Whale Alert and Arkham for triangulation.

### 8.5 DeBank

DeBank Cloud API free tier is up to 3,000 calls/day; paid scales
$149/month (250k calls) to $999/month (2.5M calls), with
custom-quoted enterprise above per
[DeBank Cloud API reference](https://docs.cloud.debank.com/en/readme/api-pro-reference).
Strong for portfolio-by-wallet queries across 100+ EVM chains
including Base, Arbitrum, Optimism, Avalanche, BNB Chain, Polygon.
Custom-ID social tier is $96 one-time on the consumer side.

Verdict: free tier is a v1 win for wallet-portfolio aggregation. Paid
tier is overpriced unless you are running a portfolio tracker as a
product.

### Recommended additions for v2 (whale-tracking section)

1. Arkham (free) plus Lookonchain Twitter (free) plus Whale Alert
   Twitter (free) plus DeBank free API. Zero cost; covers the bulk
   of retail-grade whale tracking.
2. Nansen Pro ($49/month) for Smart Money labels at v2 retail.
3. Whale Alert Enterprise API ($499/year/chain) only if backtesting
   whale-flow signals against historical data is the workload.

---

## 9. News-tagged-by-symbol and event detection

The hard problem in news ingestion is not pulling headlines; it is
classifying which coin a headline is about, and whether it is event-
grade (hack, listing, partnership, regulation) versus noise (price
commentary, retail speculation). The current pipeline does this with
regex + keyword extraction in `news/sources.py:_extract_tickers_from_title`.

### 9.1 CryptoCompare News API

Per CoinDesk's acquisition of CryptoCompare, the news endpoints survive
under the cryptocompare.com domain. News is tagged per asset (the
`coins` field in the response) and per category. Free tier accommodates
news polling at the same 50 to 200 requests/hour as the broader free
tier.

Verdict: immediate v1 win as a structured per-asset news source.
Replaces some of what CryptoPanic provided.

### 9.2 Messari news (asset-tagged)

Already covered in 1.9. Messari's news endpoint tags per asset,
clusters topics, and provides AI-summarised digests. The single best
purpose-built solution for the asset-disambiguation problem in
crypto news.

Verdict: v2 pick at $50/month.

### 9.3 Aggregator APIs that classify event types

CoinTelegraph and others publish category-tagged feeds (regulation,
exchange, hack), but classification of breaking news into event types
(hack vs listing vs partnership) is largely undelivered as a free
product. Messari Pro and the institutional CoinDesk Data product
both do event classification; otherwise it is a DIY problem.

Verdict: v2 candidate at Messari Pro level. Not a v1 win.

### 9.4 DIY: regex + keyword + lightweight classifier

The current pipeline does ticker extraction via regex. The next step
in DIY is event classification via a small finetuned classifier or
keyword rules. Existing public datasets (e.g. CryptoBERT, finetuned
on labelled headlines) make this approachable in Python with
transformers.

Verdict: a lightweight DIY classifier is the right next step before
spending on Messari Pro. It buys time to validate whether event
classification actually moves the needle on the research output
quality.

### Recommended additions for v2 (news-tagging section)

1. CryptoCompare News API (free) for structured per-asset news. Wire
   in v1.
2. Messari Pro ($50/month) for asset-tagged news plus event clustering.
   Highest-value paid news upgrade.
3. DIY event classifier as an interim step. Zero cost; one engineering
   sprint.

---

## V2 paid stack recommendation

If the operator has $50/month to spend, the order of additions is:
LunarCrush Builder ($24 to $40/month) for sentiment, plus Coinglass
Hobbyist ($29/month) for liquidation history. Skip everything else;
the rest of the value at this tier comes from the immediate free wins.

If the operator has $300/month to spend, the stack is: CryptoQuant
Premium ($99 to $200/month) for exchange flows and miner data, plus
Nansen Pro ($49/month) for Smart Money labels, plus Messari Pro ($30
to $60/month) for asset-tagged news and protocol metrics, plus
Coinglass Hobbyist ($29/month) for liquidations. Total around $200 to
$340. Glassnode is intentionally NOT in this bucket because the
$29/month Advanced tier does not include API access and the genuinely
useful Professional tier is $999/month, which jumps straight past the
$300 budget.

If the operator has $2,000+/month to spend, the stack adds: Glassnode
Professional ($999/month) for full on-chain alpha including
entity-adjusted exchange flows, plus Tardis.dev ($59 to $400/month)
for tick-level historical data, plus Laevitas premium ($50/month) for
options chains and Greeks, plus Blockworks Research and Delphi Pro
for the qualitative research layer ($60 to $300/month combined).
Total in the $1,500 to $1,800/month range with headroom for one
specialist add-on. At this level the operator should also consider
whether the marginal alpha justifies a full Coin Metrics or Kaiko
institutional engagement (around $10k to $30k/year), at which point
the budget conversation moves out of self-funding territory and into
fund-or-prop-firm territory.

---

## Immediate free wins (no signup needed beyond an RSS reader)

The agent currently has 3 working news sources. The following list
roughly triples the news surface area at zero cost, plus adds free
on-chain and whale-tracking inputs:

- The Block editorial RSS at `https://www.theblock.co/rss.xml`.
  Latency under 10 minutes. Caveat: confirm exact feed URL by opening
  it before wiring; The Block restructures their site occasionally.
- Decrypt RSS at `https://decrypt.co/feed`. Latency under 15 minutes.
  No caveats.
- Bitcoin Magazine RSS at `https://bitcoinmagazine.com/.rss/full/`.
  BTC-only; useful as the BTC-tagged news bucket. Editorial bias is
  maximalist.
- CryptoSlate RSS at `https://cryptoslate.com/feed/`. Latency under
  15 minutes. Caveat: their site does occasionally republish
  press-release content; whitelist editorial categories if quality
  matters.
- Blockworks editorial RSS at `https://blockworks.co/feed`. Latency
  under 15 minutes. Strong US institutional desk.
- Crypto Briefing RSS at `https://cryptobriefing.com/feed/`.
  Optional fifth source for breaking-news cross-corroboration.
- Reuters crypto-section RSS at
  `https://www.reuters.com/arc/outboundfeeds/rss/category/crypto/`.
  Authoritative for institutional and policy news. Latency typically
  10 to 30 minutes.
- Google News RSS with crypto query, e.g.
  `https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+crypto&hl=en-US&gl=US&ceid=US:en`.
  Caveat: noisy; pair with a domain whitelist.
- CryptoCompare News API (free key) at
  `https://min-api.cryptocompare.com/data/v2/news/`. Returns
  per-asset-tagged news. Replaces a meaningful slice of what
  CryptoPanic gave.
- Arkham public dashboard plus free entity labels at
  `https://intel.arkm.com/`. Use the labels to compute
  exchange-flow proxies on top of free Etherscan and Blockchair raw
  data.
- DeFi Llama free API at `https://api.llama.fi/`. TVL by chain,
  stablecoin supply, yields, fees. No auth, no rate limit for normal
  traffic.
- Helius Solana free tier at `https://docs.helius.dev/`. 1M monthly
  credits, fills the Solana on-chain gap.
- Whale Alert Twitter at `@whale_alert`. Lookonchain Twitter at
  `@lookonchain`. Both free, both useful as whale-flow signals via
  Twitter scrape.
- Galaxy, Coinbase Institutional, Bitwise, Grayscale, K33 research
  newsletter signups. Free institutional-grade qualitative layer.
- Reddit OAuth via `praw`. Migrate from the JSON suffix to OAuth for
  100 QPM and reliability. Zero cost.

---

## Provider mapping update

Extension of the v1-to-v2 mapping table in `docs/API_RESEARCH.md`
section 4, now with v3 small-institutional column:

| Capability | v1 (free, today) | v2 ($300 budget) | v3 ($2k+ budget) |
|---|---|---|---|
| News headlines | CoinDesk RSS, CoinTelegraph RSS, Reddit JSON, plus free additions: The Block, Decrypt, Bitcoin Magazine, CryptoSlate, Blockworks, Reuters, Google News RSS, CryptoCompare News API | Add Messari Pro for asset-tagged news and event clustering ($30 to $60/month) | Add Bloomberg crypto feed via Bloomberg Terminal or LSEG Workspace ($2,500+/month) |
| Sentiment | CoinGecko social score, Reddit OAuth | LunarCrush Builder ($24 to $40/month) plus Santiment Pro ($49/month) | The Tie sentiment API (sales-quoted, five-figure annual) |
| On-chain | Blockchair (BTC, ETH), Etherscan v2 (60 EVM chains), Helius free (Solana), Arkham entity labels, Dune free (2,500 credits/month), DeFi Llama | CryptoQuant Premium ($99 to $200/month) for exchange flows plus Nansen Pro ($49/month) for Smart Money | Glassnode Professional ($999/month) plus Coin Metrics Network Data Pro (sales) |
| Derivatives | ccxt (Binance USDM, Bybit V5) for funding and OI | Coinglass Hobbyist ($29/month) for liquidations | Amberdata or Kaiko derivatives ($10k+/year) |
| Microstructure | None in v1 | Tardis.dev individual ($59/month) for backtest tick data; ccxt WebSocket free for live | Kaiko L2 plus trades ($28k/year median) |
| Macro | FRED, DeFi Llama | No spend; FRED plus DeFi Llama remain sufficient | Coin Metrics Network Data Pro (sales) |
| Research (qualitative) | Galaxy, Coinbase Institutional, Bitwise, Grayscale, K33 newsletters | Messari Pro ($30 to $60/month) plus Delphi Pro ($59/month) | Add Blockworks Research (sales, $300 to $1,500/month per seat) |
| Whale tracking | Arkham labels, Lookonchain Twitter, Whale Alert Twitter, DeBank free API | Nansen Pro ($49/month) | Whale Alert Enterprise (sales, around $500/year/chain plus subscription) |

---

## Open questions

Items I could not pin down to a confident answer; the operator should
resolve before committing to wiring or paid signups.

1. The Block's exact RSS URL. The standard convention
   `https://www.theblock.co/rss.xml` is widely cited but not on the
   publisher's own marketing pages. Resolution: open the URL in a
   browser before wiring; if the site has restructured, fall back to
   discovering the feed via `<link rel="alternate" type="application/rss+xml">`
   in the homepage HTML.

2. Bitcoin Magazine RSS path stability. The WordPress convention
   `/.rss/full/` is functional in 2026 but the publisher could
   restructure. Resolution: same as above; programmatically discover
   the feed link.

3. Messari Pro self-serve pricing in 2026. Their pricing page funnels
   through sales for most tiers; the historical $30/month single-user
   tier may or may not still exist as a self-serve SKU. Resolution:
   sign up for the free tier, attempt to upgrade, observe whether a
   self-serve credit-card flow exists or whether everything routes
   through sales.

4. CryptoQuant Premium API pricing. Public reports range from
   $99/month to $200/month and the older 2024 figure was $799/month
   for an even higher tier. Resolution: pull current pricing from
   their pricing page directly before committing to v2.

5. CoinTelegraph RSS sponsored-content separation. Sponsored posts
   are tagged but the tag scheme has shifted between site redesigns.
   Resolution: inspect a few weeks of RSS items and confirm the
   `<category>` filter is still effective.

6. The Block Pro and Blockworks Research seat pricing. Both are
   sales-gated and public reports vary widely. Resolution: not worth
   resolving until budget actually exists at the institutional tier.

7. Twitter / X API future direction. The pay-per-use migration
   completed February 2026 but X has changed pricing four times in
   three years. The 2026-04-20 owned-reads price reduction to $0.001
   per resource is favourable but small-volume use is still
   uneconomical. Resolution: monitor; do not architect anything that
   depends on stable X API economics.

8. Dune free tier credit cost stability. Dune restructured pricing in
   2024 and added pay-as-you-go in 2025; the 2,500 free credits per
   month is current as of 2026 but the per-credit cost above the free
   tier ($5/100 credits) is on the high side for backfill workloads.
   Resolution: pre-compute query cost before scheduling any
   high-frequency Dune jobs.

9. CoinDesk Indices vs CryptoCompare API rebranding. After CoinDesk
   acquired CryptoCompare in 2022, the API endpoints survived under
   both domain names. As of 2026 the canonical News API URL appears
   to still be `min-api.cryptocompare.com/...` but the CoinDesk Data
   product page suggests migration to `data.coindesk.com`. Resolution:
   test both before wiring; assume some endpoints will redirect.

10. Helius free-tier credit cost per call. The 1M monthly credit
    allowance is generous in aggregate but credit cost per call type
    is not on the public pricing summary; getting account-level
    transaction history can be expensive. Resolution: instrument
    cost-per-call for the specific endpoints the OnChainProvider
    needs before committing.

11. Reddit OAuth commercial use clause. Reddit's free OAuth tier is
    documented as personal/academic use only; it is unclear whether
    a research-only paper-trading workload counts as "commercial".
    Resolution: read the current Reddit Data API ToS carefully before
    promoting Reddit from the v1 best-effort wire to a load-bearing
    sentiment input.

12. ccxt.pro merger completeness. The CCXT Pro repository was merged
    into the free CCXT under MIT in 2022 per the issue thread, but
    some advanced WebSocket features may still be marked as
    "supported only for paid users" in older docs. Resolution:
    smoke-test `watchOrderBook` and `watchLiquidations` against
    Binance and Bybit to confirm they work without a paid license in
    2026.
