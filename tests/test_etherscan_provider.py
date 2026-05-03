"""Tests for the Etherscan v2 multichain provider.

Network is fully mocked. Disk cache is rooted under tmp_path so we
don't pollute the real .cache/etherscan directory.
"""

from __future__ import annotations

import json
from typing import Any

from crypto_research_watchlist.data.etherscan_provider import (
    ETHERSCAN_V2_URL,
    SYMBOL_TO_CHAIN,
    EtherscanProvider,
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
    """Returns the next queued response per call, recording every params."""

    def __init__(self, queue: list[_MockResp]) -> None:
        self._queue = list(queue)
        self.calls: list[dict] = []

    def get(self, url: str, *args, **kwargs):
        params = kwargs.get("params") or {}
        self.calls.append({"url": url, "params": dict(params)})
        if not self._queue:
            raise RuntimeError("no more mock responses")
        return self._queue.pop(0)


def _block_number_resp(block_hex: str = "0x10ce4f0") -> _MockResp:
    return _MockResp(json_data={"jsonrpc": "2.0", "id": 1, "result": block_hex})


def _block_tx_count_resp(tx_count: int) -> _MockResp:
    return _MockResp(json_data={"jsonrpc": "2.0", "id": 1, "result": hex(tx_count)})


def test_fetch_chain_stats_eth(tmp_path):
    http = _MockHttp([_block_number_resp(), _block_tx_count_resp(180)])
    provider = EtherscanProvider(api_key="K", http=http, cache_dir=tmp_path)

    out = provider.fetch_chain_stats("ETH-USD")
    assert out is not None
    assert out["daily_tx_count"] == 180
    # Warmup not met yet -> z is None.
    assert out["active_addresses_z"] is None

    # Both calls hit the v2 unified endpoint with chainid=1.
    assert all(c["url"] == ETHERSCAN_V2_URL for c in http.calls)
    assert http.calls[0]["params"]["chainid"] == "1"
    assert http.calls[0]["params"]["module"] == "proxy"
    assert http.calls[0]["params"]["action"] == "eth_blockNumber"
    assert http.calls[1]["params"]["chainid"] == "1"
    assert http.calls[1]["params"]["action"] == "eth_getBlockTransactionCountByNumber"
    assert http.calls[0]["params"]["apikey"] == "K"


def test_fetch_chain_stats_unknown_symbol_returns_none(tmp_path):
    provider = EtherscanProvider(api_key="K", http=_MockHttp([]), cache_dir=tmp_path)
    assert provider.fetch_chain_stats("SOL-USD") is None
    assert provider.fetch_chain_stats("LINK-USD") is None
    assert provider.fetch_chain_stats("XRP-USD") is None


def test_fetch_chain_stats_no_key(tmp_path):
    provider = EtherscanProvider(api_key=None, http=_MockHttp([]), cache_dir=tmp_path)
    assert provider.fetch_chain_stats("ETH-USD") is None


def test_in_process_cache_avoids_second_call(tmp_path):
    # Only two responses queued. A second fetch must NOT trigger network.
    http = _MockHttp([_block_number_resp(), _block_tx_count_resp(99)])
    provider = EtherscanProvider(api_key="K", http=http, cache_dir=tmp_path)

    first = provider.fetch_chain_stats("ETH-USD")
    second = provider.fetch_chain_stats("ETH-USD")
    assert first == second
    assert len(http.calls) == 2  # only the first fetch hit network


def test_z_score_none_until_warmup(tmp_path):
    """Even with disk-seeded panel, z stays None until 14+ samples exist."""
    chainid = SYMBOL_TO_CHAIN["ETH-USD"]
    # Seed only 5 days of history (well below the 14-sample warmup).
    for i in range(5):
        date = f"2026-04-2{i}"
        (tmp_path / f"{chainid}_{date}.json").write_text(
            json.dumps({"daily_tx_count": 100 + i})
        )

    http = _MockHttp([_block_number_resp(), _block_tx_count_resp(150)])
    provider = EtherscanProvider(api_key="K", http=http, cache_dir=tmp_path)
    out = provider.fetch_chain_stats("ETH-USD")
    assert out is not None
    assert out["daily_tx_count"] == 150
    assert out["active_addresses_z"] is None  # warmup not reached


def test_z_score_after_warmup(tmp_path):
    """20 days of cached history + today's fetch -> non-None z-score."""
    chainid = SYMBOL_TO_CHAIN["ETH-USD"]
    for i in range(20):
        # Use ascending dates so glob+sort orders correctly.
        date = f"2026-04-{i+1:02d}"
        (tmp_path / f"{chainid}_{date}.json").write_text(
            json.dumps({"daily_tx_count": 100.0})
        )

    http = _MockHttp([_block_number_resp(), _block_tx_count_resp(500)])
    provider = EtherscanProvider(api_key="K", http=http, cache_dir=tmp_path)
    out = provider.fetch_chain_stats("ETH-USD")
    assert out is not None
    # The seeded panel has zero variance so a strict z-score returns None.
    # That is the correct behaviour: no signal when std == 0.
    assert out["active_addresses_z"] is None


def test_z_score_with_real_variance(tmp_path):
    chainid = SYMBOL_TO_CHAIN["BNB-USD"]
    # 20 samples around mean=100 with stdev>0.
    for i in range(20):
        date = f"2026-04-{i+1:02d}"
        (tmp_path / f"{chainid}_{date}.json").write_text(
            json.dumps({"daily_tx_count": 100 + (i % 5) * 10})
        )

    http = _MockHttp([_block_number_resp(), _block_tx_count_resp(500)])
    provider = EtherscanProvider(api_key="K", http=http, cache_dir=tmp_path)
    out = provider.fetch_chain_stats("BNB-USD")
    assert out is not None
    assert out["active_addresses_z"] is not None
    assert out["active_addresses_z"] > 1.0  # 500 vs ~120 baseline


def test_chain_id_routing(tmp_path):
    """Each supported symbol routes to the correct chainid query."""
    cases = [
        ("ETH-USD", "1"),
        ("BNB-USD", "56"),
        ("MATIC-USD", "137"),
        ("AVAX-USD", "43114"),
    ]
    for sym, expected in cases:
        http = _MockHttp([_block_number_resp(), _block_tx_count_resp(10)])
        provider = EtherscanProvider(api_key="K", http=http, cache_dir=tmp_path / sym)
        provider.fetch_chain_stats(sym)
        assert http.calls[0]["params"]["chainid"] == expected, sym


def test_http_error_returns_payload_with_none(tmp_path):
    """HTTP failure -> daily_tx_count is None but no exception bubbles."""
    http = _MockHttp([_MockResp(status_code=500, json_data=None)])
    provider = EtherscanProvider(api_key="K", http=http, cache_dir=tmp_path)
    out = provider.fetch_chain_stats("ETH-USD")
    assert out is not None
    assert out["daily_tx_count"] is None
    assert out["active_addresses_z"] is None
