"""On-chain data provider.

Free-tier wiring to Blockchair `/{chain}/stats`:
  - BTC -> https://api.blockchair.com/bitcoin/stats
  - ETH -> https://api.blockchair.com/ethereum/stats
Other coins (SOL/ADA/AVAX/DOT/LINK/MATIC) return empty: free-tier coverage
is BTC + ETH only per docs/API_RESEARCH.md 1.9. The signals/onchain.py
evaluator returns NEUTRAL when both inputs are None, so this is graceful.

`active_addresses_z` requires a rolling baseline. v1 stores the daily
``addresses_24h`` print (or the closest analogue) into a small SQLite
helper table when an engine is provided; the z-score is computed against
the trailing-30d panel. When the panel has fewer than 14 samples we
return None and document the warm-up period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


_BLOCKCHAIR_BASE = "https://api.blockchair.com"
_BTC_STATS = f"{_BLOCKCHAIR_BASE}/bitcoin/stats"
_ETH_STATS = f"{_BLOCKCHAIR_BASE}/ethereum/stats"


@dataclass(slots=True)
class OnChainSnapshot:
    symbol: str
    active_addresses_z: float | None = None
    exchange_netflow_usd_7d: float | None = None
    transactions_24h: int | None = None
    raw: dict = field(default_factory=dict)


class _HTTPClient(Protocol):
    def get(self, url: str, *args: Any, **kwargs: Any) -> Any: ...


class BlockchairClient:
    """Thin httpx wrapper around the Blockchair stats endpoints."""

    def __init__(self, http: _HTTPClient | None = None) -> None:
        self._http = http

    def _client(self) -> _HTTPClient:
        if self._http is not None:
            return self._http
        import httpx
        self._http = httpx.Client(timeout=15.0, headers={"User-Agent": "crypto_research_watchlist/0.1"})
        return self._http

    def fetch_btc_stats(self) -> dict | None:
        try:
            resp = self._client().get(_BTC_STATS)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Blockchair BTC stats fetch failed: %s", exc)
            return None

    def fetch_eth_stats(self) -> dict | None:
        try:
            resp = self._client().get(_ETH_STATS)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning("Blockchair ETH stats fetch failed: %s", exc)
            return None


def _ticker(symbol: str) -> str:
    return symbol.split("-")[0].upper()


class OnChainProvider:
    """Blockchair-backed on-chain provider, BTC + ETH only.

    For the rest of the universe ``fetch`` returns an empty OnChainSnapshot.
    The active-addresses z-score requires a >=14-sample rolling history;
    until that warms up we return None for the z-score and only populate
    `transactions_24h` (raw counter, useful for the renderer).

    Test injection: pass a custom BlockchairClient with a mock httpx.
    """

    def __init__(
        self,
        client: BlockchairClient | None = None,
        history: dict[str, list[float]] | None = None,
    ) -> None:
        self._client = client or BlockchairClient()
        # Symbol -> rolling list of `transactions_24h` values, oldest -> newest.
        self._history = history or {}

    def set_overrides(self, snapshots: list[OnChainSnapshot]) -> None:
        """Test helper: pre-populate explicit per-symbol snapshots.

        Provided snapshots take precedence over network calls. Used in
        tests that want to force specific z-score / netflow values.
        """
        self._overrides = {s.symbol: s for s in snapshots}

    def fetch(self, symbol: str) -> OnChainSnapshot:
        # Test overrides
        overrides = getattr(self, "_overrides", None)
        if overrides and symbol in overrides:
            return overrides[symbol]

        ticker = _ticker(symbol)
        if ticker == "BTC":
            data = self._client.fetch_btc_stats()
        elif ticker == "ETH":
            data = self._client.fetch_eth_stats()
        else:
            # Free-tier limitation: no other chains.
            return OnChainSnapshot(symbol=symbol)

        if not data:
            return OnChainSnapshot(symbol=symbol)
        payload = (data or {}).get("data") or {}
        tx_24h = payload.get("transactions_24h")
        try:
            tx_24h = int(tx_24h) if tx_24h is not None else None
        except Exception:
            tx_24h = None

        # Update history panel (pure in-memory; persistence is the caller's
        # responsibility via OnChainDailyHistory).
        if tx_24h is not None:
            panel = self._history.setdefault(ticker, [])
            panel.append(float(tx_24h))
            self._history[ticker] = panel[-90:]  # cap at 90d

        z = self._z_score_from_panel(self._history.get(ticker, []))

        return OnChainSnapshot(
            symbol=symbol,
            active_addresses_z=z,
            exchange_netflow_usd_7d=None,  # not freely available; v2 (Glassnode).
            transactions_24h=tx_24h,
            raw={"data": payload},
        )

    @staticmethod
    def _z_score_from_panel(panel: list[float]) -> float | None:
        if len(panel) < 14:
            return None
        # 30d baseline (trailing window before today). Fall back to the
        # whole panel when shorter than 30.
        today = panel[-1]
        baseline = panel[-30:-1] if len(panel) >= 31 else panel[:-1]
        if len(baseline) < 5:
            return None
        try:
            mean = sum(baseline) / len(baseline)
            var = sum((x - mean) ** 2 for x in baseline) / len(baseline)
            std = var ** 0.5
            if std <= 0:
                return None
            return float((today - mean) / std)
        except Exception:
            return None
