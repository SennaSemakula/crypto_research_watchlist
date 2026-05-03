"""Tests for the CryptoCompare news fetcher.

Network is fully mocked; live calls are exercised only by the
@pytest.mark.integration tests under tests/integration/.
"""

from __future__ import annotations

from typing import Any

from crypto_research_watchlist.news import sources


class _MockResp:
    def __init__(self, *, status_code: int = 200, json_data: Any = None) -> None:
        self.status_code = status_code
        self._json = json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _MockHttp:
    def __init__(self, response: _MockResp) -> None:
        self._resp = response
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url: str, *args, **kwargs):
        params = kwargs.get("params") or {}
        headers = kwargs.get("headers") or {}
        self.calls.append((url, params, headers))
        return self._resp


SAMPLE_PAYLOAD = {
    "Type": 100,
    "Message": "News list successfully returned",
    "Data": [
        {
            "id": "12345",
            "guid": "https://example.com/btc-etf",
            "published_on": 1746187200,  # 2025-05-02 12:00:00 UTC
            "url": "https://example.com/btc-etf",
            "title": "Spot BTC ETF clears regulatory hurdle",
            "body": "The SEC approved a new spot BTC ETF today" + (" filler" * 200),
            "source": "CoinDesk",
            "categories": "BTC|ETH|Trading|Regulation",
        },
        {
            "id": "12346",
            "guid": "https://example.com/sol-outage",
            "published_on": 1746183600,
            "url": "https://example.com/sol-outage",
            "title": "Solana network experiences brief outage",
            "body": "Validators report a 30 minute halt.",
            "source": "CoinTelegraph",
            "categories": "SOL|Outage",
        },
    ],
}


def test_fetch_cryptocompare_with_key():
    http = _MockHttp(_MockResp(json_data=SAMPLE_PAYLOAD))
    out = sources.fetch_cryptocompare(http=http, api_key="fake-key")

    assert len(out) == 2
    assert out[0].source == "cryptocompare"
    assert out[0].url == "https://example.com/btc-etf"
    assert out[0].title == "Spot BTC ETF clears regulatory hurdle"
    # Body capped at 1000 chars.
    assert out[0].body is not None
    assert len(out[0].body) <= 1000
    # Categories -> universe symbols. Trading/Regulation dropped.
    assert "BTC-USD" in out[0].raw_currencies
    assert "ETH-USD" in out[0].raw_currencies
    assert all(c.endswith("-USD") for c in out[0].raw_currencies)

    # Auth header present, query lang=EN.
    url, params, headers = http.calls[0]
    assert url == sources.CRYPTOCOMPARE_NEWS_URL
    assert params == {"lang": "EN"}
    assert headers.get("Authorization") == "Apikey fake-key"


def test_fetch_cryptocompare_no_key_returns_empty(monkeypatch):
    monkeypatch.delenv("CRYPTOCOMPARE_API_KEY", raising=False)
    http = _MockHttp(_MockResp(json_data=SAMPLE_PAYLOAD))
    out = sources.fetch_cryptocompare(http=http, api_key=None)
    assert out == []
    # No HTTP attempted.
    assert http.calls == []


def test_fetch_cryptocompare_http_error_returns_empty():
    http = _MockHttp(_MockResp(status_code=500, json_data=None))
    out = sources.fetch_cryptocompare(http=http, api_key="fake-key")
    assert out == []


def test_currency_extraction_from_categories():
    out = sources._categories_to_universe("BTC|ETH|Trading")
    assert out == ["BTC-USD", "ETH-USD"]
    # Empty / None
    assert sources._categories_to_universe(None) == []
    assert sources._categories_to_universe("") == []
    # POL collapses onto MATIC.
    out_pol = sources._categories_to_universe("POL|Trading")
    assert out_pol == ["MATIC-USD"]
    # Non-universe tokens dropped silently.
    out_misc = sources._categories_to_universe("DOGE|SHIB|BTC")
    assert out_misc == ["BTC-USD"]


def test_fallback_ticker_extraction_when_no_categories():
    payload = {
        "Data": [
            {
                "id": "1",
                "url": "https://example.com/x",
                "title": "Bitcoin and Ethereum jump on positive macro",
                "published_on": 1746187200,
                "body": "",
                "source": "Reuters",
                "categories": "",
            }
        ]
    }
    http = _MockHttp(_MockResp(json_data=payload))
    out = sources.fetch_cryptocompare(http=http, api_key="fake-key")
    assert len(out) == 1
    assert "BTC-USD" in out[0].raw_currencies
    assert "ETH-USD" in out[0].raw_currencies
