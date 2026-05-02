"""Open-interest provider.

Wraps ccxt.binanceusdm primary + ccxt.bybit fallback.

Returns a dict with ``open_interest_today`` and ``open_interest_7d_ago`` in
quote-currency notional (USDT for our exchanges, USD-comparable). The
``signals/open_interest.py`` evaluator reads these two keys directly.

CCXT's ``fetch_open_interest_history(symbol, '8h', limit=24)`` returns the
trailing 24 prints at 8h cadence; we use indices [-1] and [-22] (7 days *
3 prints/day = 21 prints back). On Binance the per-call limit is 30 days
of 8h candles; 24 is plenty.

12h in-process cache + disk cache under .cache/openinterest/<symbol>_<date>.json.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = REPO_ROOT / ".cache" / "openinterest"

_DEFAULT_INPROC_TTL_SEC = 12 * 60 * 60  # 12h


def _binance_perp_symbol(yf_symbol: str) -> str:
    base = yf_symbol.split("-")[0].upper()
    return f"{base}/USDT:USDT"


def _bybit_symbol(yf_symbol: str) -> str:
    base = yf_symbol.split("-")[0].upper()
    return f"{base}/USDT:USDT"


@dataclass(slots=True)
class _CacheEntry:
    payload: dict
    expires_at: float


class OpenInterestProvider:
    """Pulls today + 7d-ago OI for derivative-symbol candidates."""

    def __init__(
        self,
        binance_perp: Any | None = None,
        bybit_perp: Any | None = None,
        cache_dir: Path | None = None,
        inproc_ttl_sec: float = _DEFAULT_INPROC_TTL_SEC,
    ) -> None:
        self._binance = binance_perp
        self._bybit = bybit_perp
        self._cache_dir = cache_dir or CACHE_DIR
        self._inproc_ttl = float(inproc_ttl_sec)
        self._inproc: dict[str, _CacheEntry] = {}

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

    # ---- Cache -------------------------------------------------------------
    def _disk_path(self, symbol: str) -> Path:
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
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

    def _cache_get(self, key: str) -> dict | None:
        entry = self._inproc.get(key)
        if entry is None:
            return None
        if entry.expires_at < time.time():
            self._inproc.pop(key, None)
            return None
        return entry.payload

    def _cache_put(self, key: str, payload: dict) -> None:
        self._inproc[key] = _CacheEntry(payload=payload, expires_at=time.time() + self._inproc_ttl)

    # ---- Public ------------------------------------------------------------
    def fetch(self, symbol: str) -> dict:
        """Return {open_interest_today, open_interest_7d_ago} in USD notional."""
        cached = self._cache_get(symbol)
        if cached is not None:
            return dict(cached)

        disk = self._load_disk(symbol)
        if disk is not None and "open_interest_today" in disk:
            self._cache_put(symbol, disk)
            return dict(disk)

        payload = self._fetch_binance(symbol)
        if not payload:
            payload = self._fetch_bybit(symbol)
        if not payload:
            return {}
        self._cache_put(symbol, payload)
        self._save_disk(symbol, payload)
        return payload

    # ---- Per-exchange ------------------------------------------------------
    def _normalise_history(self, rows: list) -> dict:
        """Reduce an OI history list to today + 7d-ago floats."""
        if not rows:
            return {}
        # Each row may carry openInterestValue (quote) or openInterestAmount
        # (base); prefer value as it is USD-comparable.
        def value_of(row):
            if isinstance(row, dict):
                v = row.get("openInterestValue") or row.get("openInterestAmount")
                if v is None:
                    info = row.get("info") or {}
                    v = info.get("sumOpenInterestValue") or info.get("sumOpenInterest")
                try:
                    return float(v) if v is not None else None
                except Exception:
                    return None
            return None
        rows_clean = [r for r in rows if value_of(r) is not None]
        if not rows_clean:
            return {}
        today = value_of(rows_clean[-1])
        # 7 days * 3 prints/day = 21 prints back. Index from the start
        # given limit=24.
        seven_back_idx = max(0, len(rows_clean) - 22)
        seven = value_of(rows_clean[seven_back_idx])
        return {
            "open_interest_today": float(today) if today is not None else None,
            "open_interest_7d_ago": float(seven) if seven is not None else None,
        }

    def _fetch_binance(self, symbol: str) -> dict:
        client = self._binance_client()
        if client is None:
            return {}
        ccxt_sym = _binance_perp_symbol(symbol)
        try:
            rows = client.fetch_open_interest_history(ccxt_sym, "8h", limit=24)
        except Exception as exc:
            logger.debug("binance OI fetch (%s) failed: %s", symbol, exc)
            return {}
        return self._normalise_history(rows)

    def _fetch_bybit(self, symbol: str) -> dict:
        client = self._bybit_client()
        if client is None:
            return {}
        ccxt_sym = _bybit_symbol(symbol)
        try:
            rows = client.fetch_open_interest_history(ccxt_sym, "8h", limit=24)
        except Exception as exc:
            logger.debug("bybit OI fetch (%s) failed: %s", symbol, exc)
            return {}
        return self._normalise_history(rows)
