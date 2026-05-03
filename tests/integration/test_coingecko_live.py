"""Live CoinGecko Demo API integration tests.

Skipped by default. Run with:

    pytest -m integration tests/integration/test_coingecko_live.py

Requires COINGECKO_API_KEY in env (or .env). Hits the real network
against the Demo plan (30 calls/min, 10k/month).
"""

from __future__ import annotations

import os

import pytest

from crypto_research_watchlist.data.coingecko_provider import (
    CoinGeckoProvider,
    MarketSummary,
)

pytestmark = pytest.mark.integration


def _key_or_skip() -> str:
    key = os.environ.get("COINGECKO_API_KEY")
    if not key:
        pytest.skip("COINGECKO_API_KEY not set in environment")
    return key


def test_live_global_market_summary(tmp_path):
    key = _key_or_skip()
    provider = CoinGeckoProvider(api_key=key, cache_dir=tmp_path)
    summary = provider.fetch_market_summary()
    assert summary is not None
    assert isinstance(summary, MarketSummary)
    # Sanity ranges as of 2026 (BTC dominance has historically been
    # 40-60% over the last decade).
    assert 20.0 <= (summary.btc_dominance_pct or 0.0) <= 80.0
    assert (summary.total_market_cap_usd or 0.0) > 1e11


def test_live_simple_price_btc(tmp_path):
    key = _key_or_skip()
    provider = CoinGeckoProvider(api_key=key, cache_dir=tmp_path)
    px = provider.fetch_spot("BTC-USD")
    assert px is not None
    assert px > 1000.0  # BTC has not been below $1k since 2017
