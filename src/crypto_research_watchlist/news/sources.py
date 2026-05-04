"""News source fetchers.

Each fetcher returns a list of ``NewsArticleDTO`` and never raises on
network errors (it logs and returns []). Tests inject a mock httpx
client; production uses ``httpx.Client``.

Supported sources:
  - CryptoCompare News API (env CRYPTOCOMPARE_API_KEY). Replaced
    CryptoPanic after the Developer tier was discontinued 2026-04-01.
  - CoinDesk RSS.
  - CoinTelegraph RSS.
  - Reddit r/cryptocurrency JSON.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

logger = logging.getLogger(__name__)


# Universe-relevant tickers we extract from headlines via regex when sources
# do not tag the currencies themselves. Word-boundaried, case-insensitive.
_TICKERS = (
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "LINK",
    "MATIC", "POL",
)
_TICKER_RE = re.compile(
    r"\b(" + "|".join(_TICKERS) + r")\b", re.IGNORECASE,
)

# Common name -> ticker lookup. Used as a supplementary pass on titles
# that mention coins by their full name rather than ticker.
_NAME_TO_TICKER = {
    "bitcoin": "BTC",
    "ethereum": "ETH",
    "ether ": "ETH",
    "solana": "SOL",
    "binance coin": "BNB",
    "ripple": "XRP",
    "cardano": "ADA",
    "avalanche": "AVAX",
    "polkadot": "DOT",
    "chainlink": "LINK",
    "polygon": "MATIC",
}


@dataclass(slots=True)
class NewsArticleDTO:
    """In-flight DTO before persistence. ``raw_currencies`` is uppercase."""

    source: str
    url: str
    title: str
    published_at: datetime
    body: str | None = None
    raw_currencies: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class _HTTPClient(Protocol):
    def get(self, url: str, *args: Any, **kwargs: Any) -> Any: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _parse_iso(ts: str | None) -> datetime:
    if not ts:
        return _utcnow()
    try:
        # Handle both 'Z' and '+00:00'
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except Exception:
        return _utcnow()


def _extract_tickers_from_title(title: str) -> list[str]:
    found = {m.upper() for m in _TICKER_RE.findall(title)}
    lower = title.lower()
    for name, ticker in _NAME_TO_TICKER.items():
        if name in lower:
            found.add(ticker)
    # Map POL -> MATIC so the universe tag aligns.
    if "POL" in found:
        found.discard("POL")
        found.add("MATIC")
    return sorted(found)


# ---------------------------------------------------------------------------
# CryptoCompare News API
# CryptoCompare replaces CryptoPanic (Developer tier discontinued 2026-04-01).
# ---------------------------------------------------------------------------

CRYPTOCOMPARE_NEWS_URL = "https://min-api.cryptocompare.com/data/v2/news/"

# Universe symbols we expect; map ticker -> canonical -USD form.
_UNIVERSE_TICKERS = {
    "BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "LINK", "MATIC",
}


def _categories_to_universe(categories: str | None) -> list[str]:
    """Parse CryptoCompare's pipe-delimited ``categories`` field into our
    universe-style symbols (``BTC`` -> ``BTC-USD``). Non-coin tags
    (``Trading``, ``Regulation``, etc.) are dropped.
    """
    if not categories:
        return []
    found: set[str] = set()
    for tok in categories.split("|"):
        tok = tok.strip().upper()
        if not tok:
            continue
        # CryptoCompare sometimes uses POL for Polygon's new token symbol;
        # collapse onto MATIC to match our universe.
        if tok == "POL":
            tok = "MATIC"
        if tok in _UNIVERSE_TICKERS:
            found.add(f"{tok}-USD")
    return sorted(found)


def fetch_cryptocompare(
    *,
    http: _HTTPClient | None = None,
    api_key: str | None = None,
    limit: int = 50,
) -> list[NewsArticleDTO]:
    """Fetch latest English news from CryptoCompare. Returns [] if no key.

    The free tier is generous (~100k calls/month) but we cap each pull at
    ``limit`` (default 50) and rely on store dedup to handle repeats.
    Auth is via the ``Authorization: Apikey <KEY>`` header per the docs.
    """
    api_key = api_key or os.environ.get("CRYPTOCOMPARE_API_KEY") or None
    if not api_key:
        logger.info("CryptoCompare key absent, skipping CryptoCompare fetch")
        return []
    if http is None:
        try:
            import httpx
            http = httpx.Client(timeout=15.0)
        except Exception as exc:
            logger.warning("httpx unavailable: %s", exc)
            return []

    params = {"lang": "EN"}
    headers = {"Authorization": f"Apikey {api_key}"}
    try:
        resp = http.get(CRYPTOCOMPARE_NEWS_URL, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json() or {}
    except Exception as exc:
        logger.warning("CryptoCompare fetch failed: %s", exc)
        return []

    out: list[NewsArticleDTO] = []
    for row in (data.get("Data") or [])[:limit]:
        url = row.get("url") or ""
        title = row.get("title") or ""
        if not url or not title:
            continue
        body = row.get("body") or None
        if body and len(body) > 1000:
            body = body[:1000]
        ts = row.get("published_on")
        try:
            published_at = (
                datetime.fromtimestamp(float(ts), tz=UTC)
                if ts is not None
                else _utcnow()
            )
        except Exception:
            published_at = _utcnow()
        tagged = _categories_to_universe(row.get("categories"))
        if not tagged:
            tagged = [
                f"{t}-USD" for t in _extract_tickers_from_title(title)
                if t in _UNIVERSE_TICKERS
            ]
        out.append(NewsArticleDTO(
            source="cryptocompare",
            url=url,
            title=title,
            body=body,
            published_at=published_at,
            raw_currencies=tagged,
            raw={
                "publisher": row.get("source"),
                "id": row.get("id"),
                "categories": row.get("categories"),
            },
        ))
    return out


# ---------------------------------------------------------------------------
# RSS feeds (CoinDesk, CoinTelegraph)
# ---------------------------------------------------------------------------

COINDESK_RSS = "https://www.coindesk.com/arc/outboundfeeds/rss"
COINTELEGRAPH_RSS = "https://cointelegraph.com/rss"


def _fetch_rss(
    *, source_name: str, url: str, http: _HTTPClient | None, limit: int,
) -> list[NewsArticleDTO]:
    """Generic RSS fetch via httpx + feedparser."""
    if http is None:
        try:
            import httpx
            http = httpx.Client(
                timeout=15.0,
                headers={"User-Agent": "crypto_research_watchlist/0.1"},
            )
        except Exception as exc:
            logger.warning("httpx unavailable for %s: %s", source_name, exc)
            return []
    try:
        resp = http.get(url)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        logger.warning("%s RSS fetch failed: %s", source_name, exc)
        return []
    return parse_rss(source_name, text, limit=limit)


def parse_rss(source_name: str, text: str, *, limit: int = 50) -> list[NewsArticleDTO]:
    """Parse an RSS XML body (string) via feedparser. Returns DTOs."""
    try:
        import feedparser
    except ImportError:
        logger.warning("feedparser not installed, skipping %s", source_name)
        return []

    feed = feedparser.parse(text)
    out: list[NewsArticleDTO] = []
    for entry in (feed.entries or [])[:limit]:
        title = entry.get("title") or ""
        url = entry.get("link") or ""
        if not title or not url:
            continue
        published_iso = entry.get("published") or entry.get("updated") or ""
        try:
            # feedparser usually exposes a parsed_struct on .published_parsed
            from email.utils import parsedate_to_datetime
            published_at = parsedate_to_datetime(published_iso)
            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=UTC)
        except Exception:
            published_at = _utcnow()
        body = entry.get("summary") or None
        currencies = _extract_tickers_from_title(title)
        out.append(NewsArticleDTO(
            source=source_name,
            url=url,
            title=title,
            body=body,
            published_at=published_at,
            raw_currencies=currencies,
        ))
    return out


def fetch_coindesk_rss(
    *, http: _HTTPClient | None = None, limit: int = 50,
) -> list[NewsArticleDTO]:
    return _fetch_rss(source_name="coindesk", url=COINDESK_RSS, http=http, limit=limit)


def fetch_cointelegraph_rss(
    *, http: _HTTPClient | None = None, limit: int = 50,
) -> list[NewsArticleDTO]:
    return _fetch_rss(source_name="cointelegraph", url=COINTELEGRAPH_RSS, http=http, limit=limit)


# ---------------------------------------------------------------------------
# Reddit r/cryptocurrency JSON
# ---------------------------------------------------------------------------

REDDIT_URL = "https://www.reddit.com/r/cryptocurrency/hot.json"


def fetch_reddit(
    *, http: _HTTPClient | None = None, limit: int = 25,
) -> list[NewsArticleDTO]:
    """Fetch r/cryptocurrency hot posts. Custom UA required to avoid 429s."""
    if http is None:
        try:
            import httpx
            http = httpx.Client(
                timeout=15.0,
                headers={"User-Agent": "crypto_research_watchlist/0.1 (research)"},
            )
        except Exception as exc:
            logger.warning("httpx unavailable: %s", exc)
            return []
    try:
        resp = http.get(REDDIT_URL, params={"limit": str(limit)})
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Reddit fetch failed: %s", exc)
        return []

    out: list[NewsArticleDTO] = []
    for child in (data.get("data") or {}).get("children", [])[:limit]:
        d = child.get("data") or {}
        title = d.get("title") or ""
        url = d.get("url_overridden_by_dest") or d.get("url") or ""
        if not title or not url:
            continue
        ts = d.get("created_utc")
        try:
            published_at = datetime.fromtimestamp(float(ts), tz=UTC) if ts else _utcnow()
        except Exception:
            published_at = _utcnow()
        out.append(NewsArticleDTO(
            source="reddit",
            url=url,
            title=title,
            body=d.get("selftext") or None,
            published_at=published_at,
            raw_currencies=_extract_tickers_from_title(title),
            raw={"score": d.get("score"), "subreddit": d.get("subreddit")},
        ))
    return out
