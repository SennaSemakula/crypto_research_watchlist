"""On-chain data provider stubs.

v1 supports two metrics per symbol:
  * active_addresses_z — z-score of 30d active address count vs 1y baseline
  * exchange_netflow_usd_7d — net USD flowing onto exchanges over 7d

Free providers (Blockchair, Etherscan) cover BTC and ETH well; alts are
patchier. This stub returns ``None`` for everything; the on-chain wiring
is a Phase E task.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class OnChainSnapshot:
    symbol: str
    active_addresses_z: float | None = None
    exchange_netflow_usd_7d: float | None = None


class OnChainProvider:
    """v1 stub. Override per-symbol values via ``set_overrides`` for tests."""

    def __init__(self) -> None:
        self._overrides: dict[str, OnChainSnapshot] = {}

    def set_overrides(self, snapshots: list[OnChainSnapshot]) -> None:
        self._overrides = {s.symbol: s for s in snapshots}

    def fetch(self, symbol: str) -> OnChainSnapshot:
        return self._overrides.get(symbol, OnChainSnapshot(symbol=symbol))
