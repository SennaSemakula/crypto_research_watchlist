"""News source fetchers.

Each fetcher returns a list of ``NewsArticleDTO`` and never raises on
network errors (it logs and returns []). Tests inject a mock httpx
client; production uses ``httpx.Client``.

Supported sources:
  - CryptoPanic free Developer plan (env CRYPTOPANIC_API_KEY).
  - CoinDesk RSS.
  - CoinTelegraph RSS.
  - Reddit r/cryptocurrency JSON.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    return datetime.now(timezone.utc)


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
# CryptoPanic
# ---------------------------------------------------------------------------

CRYPTOPANIC_URL = "https://cryptopanic.com/api/v1/posts/"


def fetch_cryptopanic(
    *,
    http: _HTTPClient | None = None,
    api_key: str | None = None,
    currencies: list[str] | None = None,
    limit: int = 50,
) -> list[NewsArticleDTO]:
    """Fetch hot CryptoPanic posts. Returns [] if no API key is configured."""
    api_key = api_key or os.environ.get("CRYPTOPANIC_API_KEY") or os.environ.get("CRYPTOPANIC_KEY")
    if not api_key:
        logger.info("CryptoPanic key absent, skipping CryptoPanic fetch")
        return []
    if http is None:
        try:
            import httpx
            http = httpx.Client(timeout=15.0)
        except Exception as exc:
            logger.warning("httpx unavailable: %s", exc)
            return []
    params = {
        "auth_token": api_key,
        "filter": "hot",
        "kind": "news",
    }
    if currencies:
        # CryptoPanic accepts up to 50 currencies. Strip -USD suffix.
        clean = [c.split("-")[0].upper() for c in currencies]
        params["currencies"] = ",".join(clean[:50])
    try:
        resp = http.get(CRYPTOPANIC_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("CryptoPanic fetch failed: %s", exc)
        return []

    out: list[NewsArticleDTO] = []
    for row in (data.get("results") or [])[:limit]:
        url = row.get("url") or row.get("source", {}).get("domain") or ""
        title = row.get("title") or ""
        if not url or not title:
            continue
        tagged = [
            (c.get("code") or "").upper()
            for c in (row.get("currencies") or [])
            if c.get("code")
        ]
        if not tagged:
            tagged = _extract_tickers_from_title(title)
        out.append(NewsArticleDTO(
            source="cryptopanic",
            url=url,
            title=title,
            published_at=_parse_iso(row.get("published_at")),
            raw_currencies=tagged,
            raw={"votes": row.get("votes"), "domain": row.get("source", {}).get("domain")},
        ))
    return out


# ---------------------------------------------------------------------------
# RSS feeds (CoinDesk, CoinTelegraph)
# ---------------------------------------------------------------------------

COINDESK_RSS = "https://www.coindesk.com/arc/outboundfeeds/rss/"
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
                published_at = published_at.replace(tzinfo=timezone.utc)
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
            published_at = datetime.fromtimestamp(float(ts), tz=timezone.utc) if ts else _utcnow()
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
