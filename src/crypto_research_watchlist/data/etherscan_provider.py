"""Etherscan v2 multichain on-chain provider.

The v2 unified endpoint covers 60+ EVM chains with a single API key:
``https://api.etherscan.io/v2/api?chainid=<id>&module=...&action=...``.

For our universe we cover ETH, BNB, AVAX, MATIC. LINK is deferred (it
is an ERC-20 on Ethereum so a contract-address query gives token tx
counts, not chain activity, which is misleading). Solana / XRP / ADA /
DOT are non-EVM so they are not addressable from here.

What we extract: a daily ``daily_tx_count`` proxy for chain activity.
The simplest cross-chain free metric is ``module=proxy &
action=eth_blockNumber`` paired with the latest block's transaction
count. We use the per-block transactions as a coarse activity proxy:
fast and uniform across every EVM chain. The real "active addresses
24h" stat is a paid endpoint on most explorers, so we do not pretend
to populate it. A z-score on the daily tx-count panel is the closest
free analogue, and that is what ``active_addresses_z`` returns.

Caching: 4-hour in-process + 24h disk under ``.cache/etherscan/``.

Fail-safe: every method swallows network/HTTP/JSON errors and returns
None. The pipeline never crashes on a dead Etherscan call.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = REPO_ROOT / ".cache" / "etherscan"

ETHERSCAN_V2_URL = "https://api.etherscan.io/v2/api"

# Universe symbol -> Etherscan v2 chain id.
SYMBOL_TO_CHAIN: dict[str, int] = {
    "ETH-USD": 1,
    "BNB-USD": 56,
    "MATIC-USD": 137,
    "AVAX-USD": 43114,
    # LINK-USD intentionally omitted: it is an ERC-20 on Ethereum and
    # a contract-address query would give token-only tx counts, not
    # chain activity. Deferred to a v2 indexer.
}

_DEFAULT_INPROC_TTL_SEC = 4 * 60 * 60  # 4h
_HTTP_TIMEOUT_SEC = 15.0
# Z-score warmup: same threshold as the Blockchair provider for
# cross-source consistency.
_Z_WARMUP_SAMPLES = 14


class _HTTPClient(Protocol):
    def get(self, url: str, *args: Any, **kwargs: Any) -> Any: ...


@dataclass(slots=True)
class _CacheEntry:
    payload: dict
    expires_at: float


def _date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class EtherscanProvider:
    """Per-symbol chain stats via Etherscan v2.

    ``fetch_chain_stats(symbol)`` returns
    ``{"daily_tx_count": int|None, "active_addresses_z": float|None}``
    or ``None`` for symbols outside SYMBOL_TO_CHAIN.

    The z-score is computed over the trailing 30d disk-cached panel of
    daily tx counts. Until the panel reaches ``_Z_WARMUP_SAMPLES``
    samples ``active_addresses_z`` stays None.
    """

    def __init__(
        self,
        api_key: str | None = None,
        http: _HTTPClient | None = None,
        cache_dir: Path | None = None,
        inproc_ttl_sec: float = _DEFAULT_INPROC_TTL_SEC,
    ) -> None:
        self._api_key = api_key
        self._http = http
        self._cache_dir = cache_dir or CACHE_DIR
        self._inproc_ttl = float(inproc_ttl_sec)
        self._inproc: dict[str, _CacheEntry] = {}

    # ---- HTTP --------------------------------------------------------------
    def _client(self) -> _HTTPClient | None:
        if self._http is not None:
            return self._http
        try:
            import httpx
            self._http = httpx.Client(
                timeout=_HTTP_TIMEOUT_SEC,
                headers={"User-Agent": "crypto_research_watchlist/0.1"},
            )
            return self._http
        except Exception as exc:
            logger.warning("httpx unavailable for Etherscan: %s", exc)
            return None

    def _api_get(self, chainid: int, module: str, action: str, **extra: str) -> dict | None:
        client = self._client()
        if client is None:
            return None
        params = {
            "chainid": str(chainid),
            "module": module,
            "action": action,
            "apikey": self._api_key or "",
        }
        params.update(extra)
        try:
            resp = client.get(ETHERSCAN_V2_URL, params=params)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.warning(
                "Etherscan v2 fetch failed (chain=%s module=%s action=%s): %s",
                chainid, module, action, exc,
            )
            return None

    # ---- Cache -------------------------------------------------------------
    def _disk_path(self, chainid: int, date: str) -> Path:
        return self._cache_dir / f"{chainid}_{date}.json"

    def _load_disk(self, chainid: int, date: str) -> dict | None:
        path = self._disk_path(chainid, date)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _save_disk(self, chainid: int, date: str, payload: dict) -> None:
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._disk_path(chainid, date).write_text(json.dumps(payload))
        except Exception as exc:
            logger.debug("etherscan disk cache write failed (%s): %s", chainid, exc)

    def _panel(self, chainid: int) -> list[float]:
        """Read the last 30 days of cached daily_tx_count for this chain."""
        if not self._cache_dir.exists():
            return []
        prefix = f"{chainid}_"
        rows: list[tuple[str, float]] = []
        for path in self._cache_dir.glob(f"{prefix}*.json"):
            stem = path.stem  # e.g. "1_2026-05-03"
            date = stem[len(prefix):]
            try:
                blob = json.loads(path.read_text())
                tx = blob.get("daily_tx_count")
                if tx is not None:
                    rows.append((date, float(tx)))
            except Exception:
                continue
        rows.sort()
        return [v for _, v in rows[-30:]]

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

    # ---- Stats fetching ----------------------------------------------------
    def _latest_block_tx_count(self, chainid: int) -> int | None:
        """Best free cross-chain activity proxy: tx count in the latest block.

        ``proxy.eth_blockNumber`` gives the head block, then
        ``proxy.eth_getBlockTransactionCountByNumber`` returns the tx
        count for it. Both work uniformly on every EVM chain via the v2
        endpoint.
        """
        head = self._api_get(chainid, "proxy", "eth_blockNumber")
        if not head:
            return None
        block_hex = head.get("result")
        if not block_hex or not isinstance(block_hex, str):
            return None
        body = self._api_get(
            chainid, "proxy", "eth_getBlockTransactionCountByNumber",
            tag=block_hex,
        )
        if not body:
            return None
        cnt_hex = body.get("result")
        try:
            return int(cnt_hex, 16) if cnt_hex else None
        except Exception:
            return None

    def fetch_chain_stats(self, symbol: str) -> dict | None:
        """Return chain-level activity stats for the symbol.

        Returns ``None`` for unsupported symbols (LINK and the non-EVM
        coins) or when no API key is configured. Returns a dict with
        ``daily_tx_count`` (int or None) and ``active_addresses_z``
        (float or None — None during the 14-day warmup) otherwise.
        """
        if not self._api_key:
            logger.info("Etherscan key absent, skipping chain stats for %s", symbol)
            return None
        chainid = SYMBOL_TO_CHAIN.get(symbol)
        if chainid is None:
            return None

        cache_key = f"{symbol}:{_date_str()}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return dict(cached)

        date = _date_str()
        disk = self._load_disk(chainid, date)
        if disk is not None and "daily_tx_count" in disk:
            self._cache_put(cache_key, disk)
            return dict(disk)

        tx = self._latest_block_tx_count(chainid)
        # daily_tx_count is a deliberate naming overload: this is a
        # proxy. We persist the latest-block count once per UTC day per
        # chain, then z-score the panel of those proxies.
        payload: dict = {"daily_tx_count": tx, "active_addresses_z": None}
        if tx is not None:
            self._save_disk(chainid, date, {"daily_tx_count": tx})

        panel = self._panel(chainid)
        z = self._z_score(panel)
        payload["active_addresses_z"] = z

        self._cache_put(cache_key, payload)
        return dict(payload)

    # ---- z-score -----------------------------------------------------------
    @staticmethod
    def _z_score(panel: list[float]) -> float | None:
        if len(panel) < _Z_WARMUP_SAMPLES:
            return None
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
