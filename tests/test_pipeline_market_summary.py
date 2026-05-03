"""Pipeline behaviour around the new market_loader hook.

The pipeline must:
  * surface the loader's MarketSummary on result.market["summary"]
  * never crash if the loader raises (collapses to None)
  * keep market["summary"] = None when no loader is provided (back-compat)
"""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from crypto_research_watchlist.data.coingecko_provider import MarketSummary
from crypto_research_watchlist.pipeline import run_once


def _synthetic_loader(seed: int = 1):
    rng = np.random.default_rng(seed)
    cache: dict[str, pd.DataFrame] = {}

    def loader(symbol: str) -> pd.DataFrame | None:
        if symbol in cache:
            return cache[symbol]
        n = 250
        dates = pd.date_range("2024-01-01", periods=n, freq="D")
        rets = rng.normal(0.001, 0.03, n)
        close = 100 * pd.Series(rets).cumsum().apply(np.exp).values
        df = pd.DataFrame({
            "date": dates,
            "open": close,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": rng.uniform(1e8, 5e8, n),
            "symbol": symbol,
        })
        cache[symbol] = df
        return df

    return loader


def _summary() -> MarketSummary:
    return MarketSummary(
        total_market_cap_usd=3.42e12,
        btc_dominance_pct=52.3,
        eth_dominance_pct=18.1,
        total_volume_24h_usd=1.45e11,
        fetched_at=datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc),
    )


def test_market_loader_summary_is_attached(cfg_demo, engine):
    summary = _summary()
    loader = _synthetic_loader()
    result = run_once(
        cfg=cfg_demo,
        engine=engine,
        price_loader=loader,
        market_loader=lambda: summary,
        write_report=False,
    )
    assert result.market.get("summary") is summary
    assert result.market["summary"].btc_dominance_pct == 52.3


def test_market_loader_failure_collapses_to_none(cfg_demo, engine):
    def boom() -> MarketSummary | None:
        raise RuntimeError("CoinGecko down")

    loader = _synthetic_loader(2)
    result = run_once(
        cfg=cfg_demo,
        engine=engine,
        price_loader=loader,
        market_loader=boom,
        write_report=False,
    )
    # Run still completes; summary collapses to None.
    assert result.market.get("summary") is None
    # Other market fields still populated.
    assert "btc" in result.market
    assert "eth" in result.market


def test_market_loader_omitted_keeps_summary_none(cfg_demo, engine):
    loader = _synthetic_loader(3)
    result = run_once(
        cfg=cfg_demo,
        engine=engine,
        price_loader=loader,
        write_report=False,
    )
    assert result.market.get("summary") is None
