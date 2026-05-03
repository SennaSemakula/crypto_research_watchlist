"""Tests for news source fetchers using a mock httpx client."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from crypto_research_watchlist.news import sources


class _MockResp:
    def __init__(self, *, status_code: int = 200, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _MockHttp:
    def __init__(self, responses: dict) -> None:
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    def get(self, url: str, *args, **kwargs):
        self.calls.append((url, kwargs))
        if url in self._responses:
            return self._responses[url]
        # Handle params-bearing URLs
        for k, v in self._responses.items():
            if url.startswith(k):
                return v
        raise RuntimeError(f"no mock response for {url}")


def test_parse_rss_extracts_tickers():
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
    <title>CoinDesk</title>
    <item>
        <title>BTC rallies to new ATH after ETF inflows</title>
        <link>https://www.coindesk.com/btc-rally</link>
        <pubDate>Fri, 02 May 2026 12:00:00 +0000</pubDate>
        <description>Bitcoin reaches a new high.</description>
    </item>
    <item>
        <title>Ethereum upgrade scheduled for next week</title>
        <link>https://www.coindesk.com/eth-upgrade</link>
        <pubDate>Fri, 02 May 2026 11:00:00 +0000</pubDate>
        <description>ETH mainnet upgrade.</description>
    </item>
    </channel></rss>
    """
    out = sources.parse_rss("coindesk", rss, limit=10)
    assert len(out) == 2
    assert out[0].source == "coindesk"
    assert "BTC" in out[0].raw_currencies
    assert "ETH" in out[1].raw_currencies


def test_reddit_parses_children():
    payload = {
        "data": {
            "children": [
                {"data": {
                    "title": "Massive ETH rally today",
                    "url": "https://reddit.com/r/cryptocurrency/eth_rally",
                    "url_overridden_by_dest": "https://example.com/eth",
                    "created_utc": 1714651200,
                    "subreddit": "cryptocurrency",
                    "score": 1234,
                }},
                {"data": {
                    "title": "BTC dump scares investors",
                    "url": "https://reddit.com/btc_dump",
                    "url_overridden_by_dest": "https://example.com/btc",
                    "created_utc": 1714651000,
                    "subreddit": "cryptocurrency",
                    "score": 500,
                }},
            ],
        },
    }
    http = _MockHttp({sources.REDDIT_URL: _MockResp(json_data=payload)})
    out = sources.fetch_reddit(http=http)
    assert len(out) == 2
    assert "ETH" in out[0].raw_currencies
    assert "BTC" in out[1].raw_currencies


def test_extract_tickers_dedupes_and_maps_pol():
    out = sources._extract_tickers_from_title("BTC and POL move together; btc up 5%")
    assert "BTC" in out
    # POL is mapped to MATIC for universe alignment.
    assert "MATIC" in out
    assert "POL" not in out
