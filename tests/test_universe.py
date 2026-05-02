"""Universe construction and filter rules."""

from __future__ import annotations

from crypto_research_watchlist.universe import (
    UniverseEntry,
    build_universe,
    filter_universe,
    universe_symbols,
)


def test_build_universe_returns_entries(cfg_demo):
    entries = build_universe(cfg_demo)
    assert len(entries) == len(cfg_demo.universe.symbols)
    assert all(isinstance(e, UniverseEntry) for e in entries)


def test_filter_excludes_stablecoins(cfg_demo):
    entries = build_universe(cfg_demo)
    entries.append(UniverseEntry(symbol="USDT-USD", base="USDT", quote="USD"))
    out = filter_universe(cfg_demo, entries)
    assert all(e.base != "USDT" for e in out)


def test_filter_excludes_meme(cfg_demo):
    entries = build_universe(cfg_demo)
    entries.append(UniverseEntry(symbol="DOGE-USD", base="DOGE", quote="USD"))
    out = filter_universe(cfg_demo, entries)
    assert all(e.base != "DOGE" for e in out)


def test_filter_drops_low_mcap(cfg_demo):
    entries = build_universe(cfg_demo)
    # Inject a tiny-cap entry; should drop with the 1B floor.
    entries.append(UniverseEntry(symbol="TINY-USD", base="TINY", quote="USD", market_cap_usd=1_000_000))
    out = filter_universe(cfg_demo, entries)
    assert all(e.symbol != "TINY-USD" for e in out)


def test_universe_symbols_returns_strings(cfg_demo):
    syms = universe_symbols(cfg_demo)
    assert isinstance(syms, list)
    assert "BTC-USD" in syms


def test_sector_tagging(cfg_demo):
    cfg_demo.crypto.universe.sectors = {"L1": ["BTC-USD", "ETH-USD"], "oracle": ["SOL-USD"]}
    entries = build_universe(cfg_demo)
    by_sym = {e.symbol: e for e in entries}
    assert by_sym["BTC-USD"].sector == "L1"
    assert by_sym["SOL-USD"].sector == "oracle"
