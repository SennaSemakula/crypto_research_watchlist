"""Live Etherscan v2 multichain API integration tests.

Skipped by default. Run with:

    pytest -m integration tests/integration/test_etherscan_live.py

Requires ETHERSCAN_API_KEY in env (or .env). Hits the real network
on the free tier (5 calls/sec).
"""

from __future__ import annotations

import os

import pytest

from crypto_research_watchlist.data.etherscan_provider import EtherscanProvider

pytestmark = pytest.mark.integration


def _key_or_skip() -> str:
    key = os.environ.get("ETHERSCAN_API_KEY")
    if not key:
        pytest.skip("ETHERSCAN_API_KEY not set in environment")
    return key


def test_live_chain_stats_eth(tmp_path):
    key = _key_or_skip()
    provider = EtherscanProvider(api_key=key, cache_dir=tmp_path)
    out = provider.fetch_chain_stats("ETH-USD")
    assert out is not None
    assert out["daily_tx_count"] is not None
    # Ethereum has hundreds of tx per block historically.
    assert out["daily_tx_count"] > 10


def test_live_chain_stats_bnb(tmp_path):
    key = _key_or_skip()
    provider = EtherscanProvider(api_key=key, cache_dir=tmp_path)
    out = provider.fetch_chain_stats("BNB-USD")
    assert out is not None
    assert out["daily_tx_count"] is not None
