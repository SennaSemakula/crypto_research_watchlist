"""CCXT-backed market data provider.

Wraps the parts of CCXT we actually use:
  * fetch_ohlcv (spot, daily/hourly)
  * fetch_funding_rate
  * fetch_open_interest_history (Binance-style)

The constructor takes an optional ``client`` so tests can inject a fake.
No network is touched until a method is called.

Symbol convention: callers pass yfinance-style ``BTC-USD``; we translate
to CCXT-style ``BTC/USDT`` (Binance has no USD spot pairs; USDT is the
canonical quote). The translation is one-way and explicit so the rest
of the system stays in yfinance form.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol

import pandas as pd

logger = logging.getLogger(__name__)


# Per-symbol overrides where the default mapping is wrong.
_CCXT_SYMBOL_OVERRIDES = {
    "MATIC-USD": "MATIC/USDT",
    "POL-USD": "POL/USDT",
}


def to_ccxt_symbol(yf_symbol: str) -> str:
    """Translate ``BTC-USD`` to ``BTC/USDT``."""
    if yf_symbol in _CCXT_SYMBOL_OVERRIDES:
        return _CCXT_SYMBOL_OVERRIDES[yf_symbol]
    if "-" not in yf_symbol:
        return yf_symbol
    base, quote = yf_symbol.split("-", 1)
    if quote.upper() == "USD":
        return f"{base}/USDT"
    return f"{base}/{quote}"


class _CcxtClient(Protocol):
    def fetch_ohlcv(self, symbol: str, timeframe: str, limit: int) -> list: ...
    def fetch_funding_rate(self, symbol: str) -> dict: ...


@dataclass(slots=True)
class FundingRateSnapshot:
    symbol: str
    funding_rate: float
    next_funding_time_ms: int | None
    raw: dict


class CcxtProvider:
    """Thin wrapper around a CCXT exchange client.

    Defaults to ``ccxt.binance()`` for spot and a separate ``ccxt.binanceusdm()``
    for funding rates. Tests can pass any object implementing the protocol."""

    def __init__(
        self,
        spot_client: Any | None = None,
        perp_client: Any | None = None,
        rate_limit_seconds: float = 1.0,
    ) -> None:
        self._spot = spot_client
        self._perp = perp_client
        self._rate_limit_seconds = rate_limit_seconds
        self._last_call_at = 0.0

    # ---- Lazy init ----
    def _spot_client(self) -> Any:
        if self._spot is not None:
            return self._spot
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("ccxt is not installed") from exc
        self._spot = ccxt.binance({"enableRateLimit": True})
        return self._spot

    def _perp_client(self) -> Any:
        if self._perp is not None:
            return self._perp
        try:
            import ccxt  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("ccxt is not installed") from exc
        self._perp = ccxt.binanceusdm({"enableRateLimit": True})
        return self._perp

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_call_at
        wait = self._rate_limit_seconds - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_call_at = time.monotonic()

    # ---- API ----
    def fetch_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 500) -> pd.DataFrame:
        """Returns a DataFrame with columns date, open, high, low, close, volume."""
        ccxt_sym = to_ccxt_symbol(symbol)
        client = self._spot_client()
        self._throttle()
        rows = client.fetch_ohlcv(ccxt_sym, timeframe, limit=limit)
        df = pd.DataFrame(rows, columns=["timestamp_ms", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True)
        return df[["date", "open", "high", "low", "close", "volume"]]

    def fetch_funding_rate(self, symbol: str) -> FundingRateSnapshot | None:
        ccxt_sym = to_ccxt_symbol(symbol)
        client = self._perp_client()
        self._throttle()
        try:
            raw = client.fetch_funding_rate(ccxt_sym)
        except Exception as exc:
            logger.debug("fetch_funding_rate(%s) failed: %s", ccxt_sym, exc)
            return None
        rate = raw.get("fundingRate")
        if rate is None:
            return None
        return FundingRateSnapshot(
            symbol=symbol,
            funding_rate=float(rate),
            next_funding_time_ms=raw.get("fundingTimestamp"),
            raw=raw,
        )
