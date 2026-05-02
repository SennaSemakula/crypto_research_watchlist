"""Funding-rate provider.

In v1 this is a thin wrapper around ``CcxtProvider.fetch_funding_rate`` plus
optional history fetch. The history variant is best-effort: the public
endpoint exposes only Binance perp data reliably, and the format differs
across exchanges, so callers should treat None / [] as a normal outcome.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class FundingRateProvider:
    """Pulls the most recent funding print and (best-effort) the last 24h."""

    def __init__(self, ccxt_provider: Any | None = None) -> None:
        self._ccxt = ccxt_provider

    def latest(self, symbol: str) -> float | None:
        if self._ccxt is None:
            return None
        snap = self._ccxt.fetch_funding_rate(symbol)
        return snap.funding_rate if snap else None

    def last_24h(self, symbol: str) -> list[float]:
        """Return up to three funding prints (8h cadence) for the last 24h.

        Best-effort: when the underlying client cannot return history, we
        fall back to a single-element list with the most recent print, or
        an empty list when even that is missing."""
        if self._ccxt is None:
            return []
        # Prefer ccxt's fetchFundingRateHistory if the underlying client
        # exposes it; otherwise fall back to the latest snapshot.
        client = getattr(self._ccxt, "_perp_client", None)
        if client is not None:
            try:
                perp = client()
            except Exception:
                perp = None
            if perp is not None and hasattr(perp, "fetch_funding_rate_history"):
                try:
                    from .ccxt_provider import to_ccxt_symbol  # local import
                    rows = perp.fetch_funding_rate_history(to_ccxt_symbol(symbol), limit=3)
                    return [float(r["fundingRate"]) for r in rows if r.get("fundingRate") is not None]
                except Exception as exc:
                    logger.debug("fetch_funding_rate_history(%s) failed: %s", symbol, exc)
        latest = self.latest(symbol)
        return [latest] if latest is not None else []
