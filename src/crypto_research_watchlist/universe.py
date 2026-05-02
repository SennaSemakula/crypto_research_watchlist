"""Crypto universe assembly + filter.

The yaml-defined universe is the authoritative seed. This module provides
the dataclass + filter so the pipeline can treat membership lookups, sector
tagging, and stablecoin/meme exclusions uniformly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from .config import AppConfig

logger = logging.getLogger(__name__)


# Bases that are excluded by category. Keep narrow and expand cautiously.
_STABLECOIN_BASES = {"USDT", "USDC", "DAI", "BUSD", "TUSD", "USDP", "FRAX", "GUSD", "FDUSD"}
_MEMECOIN_BASES = {"DOGE", "SHIB", "PEPE", "FLOKI", "BONK", "WIF", "MEME"}
_WRAPPED_BASES = {"WBTC", "WETH", "STETH", "WSTETH", "RETH"}


@dataclass(slots=True)
class UniverseEntry:
    symbol: str            # yfinance-style, e.g. "BTC-USD"
    base: str              # e.g. "BTC"
    quote: str             # e.g. "USD"
    sector: str | None = None
    market_cap_usd: float | None = None
    listed_on_binance: bool = True
    listed_on_coinbase: bool = True


def _split(symbol: str) -> tuple[str, str]:
    if "-" in symbol:
        a, b = symbol.split("-", 1)
        return a.upper(), b.upper()
    if "/" in symbol:
        a, b = symbol.split("/", 1)
        return a.upper(), b.upper()
    return symbol.upper(), "USD"


def _sector_for(symbol: str, sectors: dict[str, list[str]]) -> str | None:
    for sector, members in sectors.items():
        if symbol in members:
            return sector
    return None


def build_universe(cfg: AppConfig) -> list[UniverseEntry]:
    """Materialise the configured universe into UniverseEntry rows."""
    uni = cfg.universe
    sectors = uni.sectors or {}
    out: list[UniverseEntry] = []
    for sym in uni.symbols:
        base, quote = _split(sym)
        out.append(
            UniverseEntry(
                symbol=sym,
                base=base,
                quote=quote,
                sector=_sector_for(sym, sectors),
            )
        )
    return out


def filter_universe(cfg: AppConfig, entries: list[UniverseEntry]) -> list[UniverseEntry]:
    """Apply config-driven exclusion rules. Pure function."""
    uni = cfg.universe
    out: list[UniverseEntry] = []
    dropped: list[tuple[str, str]] = []

    for e in entries:
        if uni.exclude_stablecoins and e.base in _STABLECOIN_BASES:
            dropped.append((e.symbol, "stablecoin"))
            continue
        if uni.exclude_meme and e.base in _MEMECOIN_BASES:
            dropped.append((e.symbol, "memecoin"))
            continue
        if e.base in _WRAPPED_BASES:
            dropped.append((e.symbol, "wrapped"))
            continue
        if e.market_cap_usd is not None and e.market_cap_usd < uni.min_market_cap_usd:
            dropped.append((e.symbol, f"mcap < {uni.min_market_cap_usd:,}"))
            continue
        out.append(e)

    if dropped:
        logger.info("Universe filter dropped %d: %s", len(dropped), dropped)
    return out


def universe_symbols(cfg: AppConfig) -> list[str]:
    """Convenience: just the filtered ticker strings."""
    return [e.symbol for e in filter_universe(cfg, build_universe(cfg))]
