"""Tests for the CCXT funding rate provider with caching + bybit fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from crypto_research_watchlist.data.funding_provider import FundingRateProvider


class _FakeCcxt:
    """Mimics the subset of ccxt we exercise."""

    def __init__(self, history: list[dict] | None = None, raise_exc: bool = False) -> None:
        self.history = history or []
        self.calls = 0
        self.raise_exc = raise_exc

    def fetch_funding_rate_history(self, symbol: str, limit: int = 3, since=None) -> list[dict]:
        self.calls += 1
        if self.raise_exc:
            raise RuntimeError("boom")
        return list(self.history[-limit:])


def test_last_24h_uses_binance_first(tmp_path):
    bin_client = _FakeCcxt(history=[
        {"fundingRate": 0.0001},
        {"fundingRate": 0.0002},
        {"fundingRate": 0.00015},
    ])
    bybit_client = _FakeCcxt(history=[{"fundingRate": 0.99}])
    provider = FundingRateProvider(
        binance_perp=bin_client, bybit_perp=bybit_client, cache_dir=tmp_path,
    )
    out = provider.last_24h("BTC-USD")
    assert out == [0.0001, 0.0002, 0.00015]
    # Bybit must NOT be called when Binance succeeds.
    assert bybit_client.calls == 0


def test_last_24h_falls_back_to_bybit(tmp_path):
    bin_client = _FakeCcxt(history=[], raise_exc=True)
    bybit_client = _FakeCcxt(history=[
        {"fundingRate": 0.00018},
        {"fundingRate": 0.00022},
    ])
    provider = FundingRateProvider(
        binance_perp=bin_client, bybit_perp=bybit_client, cache_dir=tmp_path,
    )
    out = provider.last_24h("ETH-USD")
    assert out == [0.00018, 0.00022]
    assert bybit_client.calls == 1


def test_inproc_cache_avoids_repeat_call(tmp_path):
    bin_client = _FakeCcxt(history=[{"fundingRate": 0.0001}])
    provider = FundingRateProvider(
        binance_perp=bin_client, bybit_perp=None, cache_dir=tmp_path,
    )
    provider.last_24h("BTC-USD")
    provider.last_24h("BTC-USD")
    provider.last_24h("BTC-USD")
    # First call hits client; subsequent calls hit cache.
    assert bin_client.calls == 1


def test_disk_cache_persists_across_provider_instances(tmp_path):
    bin_client = _FakeCcxt(history=[{"fundingRate": 0.0001}, {"fundingRate": 0.0002}])
    p1 = FundingRateProvider(binance_perp=bin_client, cache_dir=tmp_path)
    p1.last_24h("BTC-USD")
    assert bin_client.calls == 1

    # New provider instance with NO live client; should still serve from disk.
    p2 = FundingRateProvider(binance_perp=None, bybit_perp=None, cache_dir=tmp_path)
    out = p2.last_24h("BTC-USD")
    assert out == [0.0001, 0.0002]


def test_latest_returns_last_entry(tmp_path):
    bin_client = _FakeCcxt(history=[{"fundingRate": 0.001}, {"fundingRate": 0.0005}])
    provider = FundingRateProvider(binance_perp=bin_client, cache_dir=tmp_path)
    assert provider.latest("BTC-USD") == 0.0005


def test_returns_empty_when_all_sources_fail(tmp_path):
    bin_client = _FakeCcxt(raise_exc=True)
    bybit_client = _FakeCcxt(raise_exc=True)
    provider = FundingRateProvider(
        binance_perp=bin_client, bybit_perp=bybit_client, cache_dir=tmp_path,
    )
    assert provider.last_24h("DOT-USD") == []
