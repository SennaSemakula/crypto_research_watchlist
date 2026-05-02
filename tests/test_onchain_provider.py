"""Tests for the Blockchair-backed on-chain provider."""

from __future__ import annotations

from typing import Any

from crypto_research_watchlist.data.onchain_provider import (
    BlockchairClient,
    OnChainProvider,
    OnChainSnapshot,
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
        self.calls: list[str] = []

    def get(self, url: str, *args, **kwargs):
        self.calls.append(url)
        if url in self._r:
            return self._r[url]
        raise RuntimeError(f"no mock for {url}")


def test_btc_stats_fetch():
    payload = {"data": {"transactions_24h": 350_000, "blocks": 144}}
    http = _MockHttp({"https://api.blockchair.com/bitcoin/stats": _MockResp(json_data=payload)})
    client = BlockchairClient(http=http)
    provider = OnChainProvider(client=client)
    snap = provider.fetch("BTC-USD")
    assert snap.transactions_24h == 350_000
    # First sample, no z-score yet (warm-up).
    assert snap.active_addresses_z is None


def test_eth_stats_fetch():
    payload = {"data": {"transactions_24h": 1_200_000}}
    http = _MockHttp({"https://api.blockchair.com/ethereum/stats": _MockResp(json_data=payload)})
    client = BlockchairClient(http=http)
    provider = OnChainProvider(client=client)
    snap = provider.fetch("ETH-USD")
    assert snap.transactions_24h == 1_200_000


def test_other_chains_return_empty():
    provider = OnChainProvider(client=BlockchairClient(http=_MockHttp({})))
    snap = provider.fetch("SOL-USD")
    assert snap.transactions_24h is None
    assert snap.active_addresses_z is None
    assert snap.exchange_netflow_usd_7d is None


def test_z_score_after_warmup():
    # Pre-seed history with 30 baseline samples ~mean 100k, then today is
    # 150k (well above the mean -> positive z).
    history = {"BTC": [100_000.0 + i * 100 for i in range(29)]}
    payload = {"data": {"transactions_24h": 150_000}}
    http = _MockHttp({"https://api.blockchair.com/bitcoin/stats": _MockResp(json_data=payload)})
    provider = OnChainProvider(client=BlockchairClient(http=http), history=history)
    snap = provider.fetch("BTC-USD")
    assert snap.active_addresses_z is not None
    assert snap.active_addresses_z > 1.0


def test_overrides_take_precedence():
    provider = OnChainProvider(client=BlockchairClient(http=_MockHttp({})))
    provider.set_overrides([
        OnChainSnapshot(symbol="BTC-USD", active_addresses_z=2.5, exchange_netflow_usd_7d=-1e8),
    ])
    snap = provider.fetch("BTC-USD")
    assert snap.active_addresses_z == 2.5
    assert snap.exchange_netflow_usd_7d == -1e8
