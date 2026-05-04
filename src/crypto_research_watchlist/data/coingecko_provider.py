"""CoinGecko Demo API provider.

Free tier: Demo API key, 30 calls/min, 10k/month.

Endpoints used:
  GET /global                     -> total mcap, BTC dominance, total volume
  GET /simple/price?ids=...       -> spot price for any coin
  GET /coins/{id}/ohlc            -> OHLC fallback if ccxt fails

Authentication uses the ``x-cg-demo-api-key`` request header per the
CoinGecko Demo plan. Anonymous fetches are tolerated but rate-limited
harder; we still authenticate when a key is configured.

Two-layer caching:
  1. In-process 5-minute cache (BTC dominance does not change minute-to-
     minute; total mcap moves slowly enough that a 5-minute snap is fine).
  2. 24h disk cache for ``/global`` under ``.cache/coingecko/global_<date>.json``.

Fail-safe contract: any HTTPError, JSONDecodeError, or timeout returns
``None`` (or [] / empty payload) and logs a WARNING. The caller never
sees an exception. This keeps the daily pipeline green even when
CoinGecko is unreachable.
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
CACHE_DIR = REPO_ROOT / ".cache" / "coingecko"

BASE_URL = "https://api.coingecko.com/api/v3"
DEMO_KEY_HEADER = "x-cg-demo-api-key"

_DEFAULT_INPROC_TTL_SEC = 5 * 60  # 5 minutes
_DEFAULT_TIMEOUT_SEC = 15.0


# yfinance-style universe symbol -> CoinGecko id.
# Source: CoinGecko /coins/list (cached mapping for our 10-symbol universe).
_SYMBOL_TO_CG_ID: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "MATIC": "matic-network",
    "POL": "matic-network",
}


def _to_cg_id(symbol: str) -> str | None:
    """BTC-USD -> 'bitcoin'. Returns None for unknown tickers."""
    if not symbol:
        return None
    base = symbol.split("-")[0].upper()
    return _SYMBOL_TO_CG_ID.get(base)


@dataclass(slots=True)
class MarketSummary:
    """Snapshot of CoinGecko ``/global`` payload, narrowed to fields we use."""

    total_market_cap_usd: float | None
    btc_dominance_pct: float | None
    eth_dominance_pct: float | None
    total_volume_24h_usd: float | None
    fetched_at: datetime


@dataclass(slots=True)
class _CacheEntry:
    payload: Any
    expires_at: float


class _HTTPClient(Protocol):
    def get(self, url: str, *args: Any, **kwargs: Any) -> Any: ...


class CoinGeckoProvider:
    """Thin wrapper around the CoinGecko Demo API.

    Construction is cheap: no network, no httpx instance until first call.
    Pass ``api_key=None`` (or omit) to disable; ``fetch_market_summary``
    will return None and log INFO once. This keeps tests free of network
    surprises.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        http: _HTTPClient | None = None,
        cache_dir: Path | None = None,
        inproc_ttl_sec: float = _DEFAULT_INPROC_TTL_SEC,
        timeout_sec: float = _DEFAULT_TIMEOUT_SEC,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._cache_dir = cache_dir or CACHE_DIR
        self._inproc_ttl = float(inproc_ttl_sec)
        self._timeout = float(timeout_sec)
        self._inproc: dict[str, _CacheEntry] = {}

    # ---- HTTP -------------------------------------------------------------

    def _client(self) -> _HTTPClient | None:
        if self._http is not None:
            return self._http
        try:
            import httpx
            self._http = httpx.Client(
                timeout=self._timeout,
                headers={"User-Agent": "crypto_research_watchlist/0.1"},
            )
            return self._http
        except Exception as exc:
            logger.warning("httpx unavailable for CoinGecko: %s", exc)
            return None

    def _headers(self) -> dict[str, str]:
        if not self._api_key:
            return {}
        return {DEMO_KEY_HEADER: self._api_key}

    # ---- In-process + disk caching ---------------------------------------

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

    def _disk_path_global(self) -> Path:
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        return self._cache_dir / f"global_{date_str}.json"

    def _load_disk_global(self) -> dict | None:
        path = self._disk_path_global()
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save_disk_global(self, payload: dict) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._disk_path_global().write_text(json.dumps(payload))
        except Exception as exc:
            logger.debug("CoinGecko disk cache write failed: %s", exc)

    # ---- Public API -------------------------------------------------------

    def fetch_market_summary(self) -> MarketSummary | None:
        """Fetch /global, return MarketSummary or None on any failure / no key.

        Order of resolution: in-proc cache -> disk cache (today) -> network.
        On network success, both caches are populated.
        """
        if not self._api_key:
            logger.info("CoinGecko API key absent, skipping market summary fetch")
            return None

        cache_key = "global"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        disk = self._load_disk_global()
        if disk is not None:
            summary = _parse_global(disk)
            if summary is not None:
                self._cache_put(cache_key, summary)
                return summary

        client = self._client()
        if client is None:
            return None

        try:
            resp = client.get(
                f"{BASE_URL}/global",
                headers=self._headers(),
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("CoinGecko /global fetch failed: %s", exc)
            return None

        summary = _parse_global(payload)
        if summary is None:
            return None
        self._cache_put(cache_key, summary)
        self._save_disk_global(payload)
        return summary

    def fetch_spot(self, symbol: str) -> float | None:
        """Spot USD price for a universe symbol via /simple/price.

        Returns None on unknown symbol, missing key, or any HTTP failure.
        """
        if not self._api_key:
            return None
        cg_id = _to_cg_id(symbol)
        if cg_id is None:
            logger.debug("CoinGecko: no id mapping for symbol %s", symbol)
            return None
        cache_key = f"spot:{cg_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached

        client = self._client()
        if client is None:
            return None
        try:
            resp = client.get(
                f"{BASE_URL}/simple/price",
                params={"ids": cg_id, "vs_currencies": "usd"},
                headers=self._headers(),
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning("CoinGecko /simple/price (%s) failed: %s", symbol, exc)
            return None

        try:
            value = float(payload[cg_id]["usd"])
        except Exception:
            return None
        self._cache_put(cache_key, value)
        return value


def _parse_global(payload: dict | None) -> MarketSummary | None:
    """Narrow the /global JSON envelope into a MarketSummary."""
    if not payload:
        return None
    data = (payload or {}).get("data") or {}
    if not data:
        return None

    try:
        total_mcap = data.get("total_market_cap") or {}
        total_volume = data.get("total_volume") or {}
        mcap_pct = data.get("market_cap_percentage") or {}
        return MarketSummary(
            total_market_cap_usd=_safe_float(total_mcap.get("usd")),
            btc_dominance_pct=_safe_float(mcap_pct.get("btc")),
            eth_dominance_pct=_safe_float(mcap_pct.get("eth")),
            total_volume_24h_usd=_safe_float(total_volume.get("usd")),
            fetched_at=datetime.now(UTC),
        )
    except Exception as exc:
        logger.warning("CoinGecko /global parse failed: %s", exc)
        return None


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None
