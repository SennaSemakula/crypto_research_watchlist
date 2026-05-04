"""Tests for the CoinGecko Demo API provider.

All HTTP calls are mocked through a tiny in-memory transport. No network
is touched. Live integration coverage lives in
``tests/integration/test_coingecko_live.py`` and is skipped by default.
"""

from __future__ import annotations

from typing import Any

from crypto_research_watchlist.data.coingecko_provider import (
    BASE_URL,
    DEMO_KEY_HEADER,
    CoinGeckoProvider,
    MarketSummary,
)


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
    def __init__(self, responses: dict[str, _MockResp]) -> None:
        self._r = responses
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url: str, *args, **kwargs):
        params = kwargs.get("params") or {}
        headers = kwargs.get("headers") or {}
        self.calls.append((url, dict(params), dict(headers)))
        if url in self._r:
            return self._r[url]
        raise RuntimeError(f"no mock for {url}")


def _global_payload() -> dict:
    """A representative slice of the real CoinGecko /global response."""
    return {
        "data": {
            "active_cryptocurrencies": 12000,
            "total_market_cap": {
                "usd": 3_420_000_000_000.0,
                "btc": 33_200_000.0,
            },
            "total_volume": {
                "usd": 145_000_000_000.0,
                "btc": 1_500_000.0,
            },
            "market_cap_percentage": {
                "btc": 52.3,
                "eth": 18.1,
                "usdt": 4.8,
            },
            "market_cap_change_percentage_24h_usd": 0.42,
            "updated_at": 1714694400,
        }
    }


def test_fetch_market_summary_with_key(tmp_path):
    http = _MockHttp({f"{BASE_URL}/global": _MockResp(json_data=_global_payload())})
    provider = CoinGeckoProvider(api_key="DEMO123", http=http, cache_dir=tmp_path)
    summary = provider.fetch_market_summary()

    assert summary is not None
    assert isinstance(summary, MarketSummary)
    assert summary.total_market_cap_usd == 3_420_000_000_000.0
    assert summary.btc_dominance_pct == 52.3
    assert summary.eth_dominance_pct == 18.1
    assert summary.total_volume_24h_usd == 145_000_000_000.0

    # Authentication header must be present.
    assert len(http.calls) == 1
    _, _, headers = http.calls[0]
    assert headers.get(DEMO_KEY_HEADER) == "DEMO123"


def test_fetch_market_summary_no_key_returns_none(tmp_path):
    http = _MockHttp({})
    provider = CoinGeckoProvider(api_key=None, http=http, cache_dir=tmp_path)
    assert provider.fetch_market_summary() is None
    # No HTTP call attempted.
    assert http.calls == []


def test_fetch_market_summary_http_error_returns_none(tmp_path):
    http = _MockHttp({f"{BASE_URL}/global": _MockResp(status_code=500)})
    provider = CoinGeckoProvider(api_key="DEMO", http=http, cache_dir=tmp_path)
    # Should not raise.
    assert provider.fetch_market_summary() is None


def test_fetch_market_summary_malformed_payload_returns_none(tmp_path):
    http = _MockHttp({f"{BASE_URL}/global": _MockResp(json_data={"unexpected": "shape"})})
    provider = CoinGeckoProvider(api_key="DEMO", http=http, cache_dir=tmp_path)
    assert provider.fetch_market_summary() is None


def test_in_process_cache_avoids_second_call(tmp_path):
    http = _MockHttp({f"{BASE_URL}/global": _MockResp(json_data=_global_payload())})
    provider = CoinGeckoProvider(api_key="DEMO", http=http, cache_dir=tmp_path)
    first = provider.fetch_market_summary()
    second = provider.fetch_market_summary()
    assert first is second
    # Only one HTTP call across both invocations.
    assert len(http.calls) == 1


def test_disk_cache_survives_provider_recreate(tmp_path):
    http = _MockHttp({f"{BASE_URL}/global": _MockResp(json_data=_global_payload())})
    p1 = CoinGeckoProvider(api_key="DEMO", http=http, cache_dir=tmp_path)
    s1 = p1.fetch_market_summary()
    assert s1 is not None
    assert len(http.calls) == 1

    # New provider (fresh in-process cache), but same disk dir today.
    http2 = _MockHttp({})  # network unavailable
    p2 = CoinGeckoProvider(api_key="DEMO", http=http2, cache_dir=tmp_path)
    s2 = p2.fetch_market_summary()
    assert s2 is not None
    assert s2.btc_dominance_pct == 52.3
    assert http2.calls == []


def test_fetch_spot_unknown_symbol_returns_none(tmp_path):
    http = _MockHttp({})
    provider = CoinGeckoProvider(api_key="DEMO", http=http, cache_dir=tmp_path)
    assert provider.fetch_spot("ZZZ-USD") is None
    assert http.calls == []


def test_fetch_spot_known_symbol(tmp_path):
    http = _MockHttp({
        f"{BASE_URL}/simple/price": _MockResp(json_data={"bitcoin": {"usd": 103_200.0}}),
    })
    provider = CoinGeckoProvider(api_key="DEMO", http=http, cache_dir=tmp_path)
    px = provider.fetch_spot("BTC-USD")
    assert px == 103_200.0
    _, params, headers = http.calls[0]
    assert params.get("ids") == "bitcoin"
    assert params.get("vs_currencies") == "usd"
    assert headers.get(DEMO_KEY_HEADER) == "DEMO"


def test_fetch_spot_no_key_returns_none(tmp_path):
    http = _MockHttp({})
    provider = CoinGeckoProvider(api_key=None, http=http, cache_dir=tmp_path)
    assert provider.fetch_spot("BTC-USD") is None
    assert http.calls == []
