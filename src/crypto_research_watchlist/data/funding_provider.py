"""Funding-rate provider.

Wraps ccxt.binanceusdm primary + ccxt.bybit fallback with two-layer caching:

  1. In-process 30-minute cache (TTL keyed by (symbol, kind)).
  2. Disk cache under .cache/funding/<symbol>_<date>.json (1-day TTL),
     so GitHub Actions reruns on the same day are free.

Symbol translation: yfinance form (BTC-USD) -> ccxt USDT-perp form
(BTC/USDT:USDT) for binanceusdm and BTC/USDT for bybit.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = REPO_ROOT / ".cache" / "funding"

_DEFAULT_INPROC_TTL_SEC = 30 * 60  # 30 minutes


def _binance_perp_symbol(yf_symbol: str) -> str:
    """BTC-USD -> BTC/USDT:USDT (ccxt unified perp form)."""
    base = yf_symbol.split("-")[0].upper()
    return f"{base}/USDT:USDT"


def _bybit_symbol(yf_symbol: str) -> str:
    """BTC-USD -> BTC/USDT:USDT (bybit linear)."""
    base = yf_symbol.split("-")[0].upper()
    return f"{base}/USDT:USDT"


@dataclass(slots=True)
class _CacheEntry:
    payload: Any
    expires_at: float


class _CcxtPerp(Protocol):
    def fetch_funding_rate(self, symbol: str) -> dict: ...
    def fetch_funding_rate_history(self, symbol: str, since=None, limit: int = 3) -> list: ...


class FundingRateProvider:
    """Pulls latest + 24h funding history with caching and exchange fallback."""

    def __init__(
        self,
        binance_perp: Any | None = None,
        bybit_perp: Any | None = None,
        cache_dir: Path | None = None,
        inproc_ttl_sec: float = _DEFAULT_INPROC_TTL_SEC,
        ccxt_provider: Any | None = None,  # legacy kw, kept for back-compat
    ) -> None:
        self._binance = binance_perp
        self._bybit = bybit_perp
        self._cache_dir = cache_dir or CACHE_DIR
        self._inproc_ttl = float(inproc_ttl_sec)
        self._inproc: dict[str, _CacheEntry] = {}
        # Legacy: when only the older CcxtProvider is passed, prefer it as
        # the binance perp client.
        if binance_perp is None and ccxt_provider is not None:
            client = getattr(ccxt_provider, "_perp_client", None)
            try:
                self._binance = client() if callable(client) else None
            except Exception:
                self._binance = None
        # Defer disk cache directory creation until first write.

    # ---- Lazy init for live clients ----------------------------------------
    def _binance_client(self) -> Any | None:
        if self._binance is not None:
            return self._binance
        try:
            import ccxt
            self._binance = ccxt.binanceusdm({"enableRateLimit": True})
            return self._binance
        except Exception as exc:
            logger.warning("ccxt.binanceusdm init failed: %s", exc)
            return None

    def _bybit_client(self) -> Any | None:
        if self._bybit is not None:
            return self._bybit
        try:
            import ccxt
            self._bybit = ccxt.bybit({"enableRateLimit": True, "options": {"defaultType": "linear"}})
            return self._bybit
        except Exception as exc:
            logger.warning("ccxt.bybit init failed: %s", exc)
            return None

    # ---- Cache helpers -----------------------------------------------------
    def _disk_path(self, symbol: str) -> Path:
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        safe = symbol.replace("/", "_").replace(":", "_")
        return self._cache_dir / f"{safe}_{date_str}.json"

    def _load_disk(self, symbol: str) -> dict | None:
        path = self._disk_path(symbol)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save_disk(self, symbol: str, payload: dict) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._disk_path(symbol).write_text(json.dumps(payload))
        except Exception as exc:
            logger.debug("disk cache write failed (%s): %s", symbol, exc)

    def _cache_get(self, key: str) -> Any | None:
        entry = self._inproc.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            self._inproc.pop(key, None)
            return None
        return entry.payload

    def _cache_put(self, key: str, payload: Any) -> None:
        self._inproc[key] = _CacheEntry(payload=payload, expires_at=time.time() + self._inproc_ttl)

    # ---- Public API --------------------------------------------------------
    def latest(self, symbol: str) -> float | None:
        history = self.last_24h(symbol)
        return history[-1] if history else None

    def last_24h(self, symbol: str) -> list[float]:
        """Return up to three 8h funding prints for the trailing 24h.

        Order: (1) in-proc cache, (2) disk cache, (3) Binance, (4) Bybit.
        Returns [] when every source fails.
        """
        cache_key = f"history:{symbol}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return list(cached)

        disk = self._load_disk(symbol)
        if disk is not None and "rates" in disk:
            rates = list(disk["rates"])
            self._cache_put(cache_key, rates)
            return rates

        rates = self._fetch_binance(symbol)
        if not rates:
            rates = self._fetch_bybit(symbol)

        if rates:
            self._cache_put(cache_key, rates)
            self._save_disk(symbol, {"rates": rates, "fetched_at": datetime.now(UTC).isoformat()})
        return rates

    # ---- Per-exchange fetchers --------------------------------------------
    def _fetch_binance(self, symbol: str) -> list[float]:
        client = self._binance_client()
        if client is None:
            return []
        ccxt_sym = _binance_perp_symbol(symbol)
        try:
            rows = client.fetch_funding_rate_history(ccxt_sym, limit=3)
            out = [float(r["fundingRate"]) for r in rows if r.get("fundingRate") is not None]
            return out
        except Exception as exc:
            logger.debug("binance funding fetch (%s) failed: %s", symbol, exc)
            return []

    def _fetch_bybit(self, symbol: str) -> list[float]:
        client = self._bybit_client()
        if client is None:
            return []
        ccxt_sym = _bybit_symbol(symbol)
        try:
            rows = client.fetch_funding_rate_history(ccxt_sym, limit=3)
            out = [float(r["fundingRate"]) for r in rows if r.get("fundingRate") is not None]
            return out
        except Exception as exc:
            logger.debug("bybit funding fetch (%s) failed: %s", symbol, exc)
            return []
