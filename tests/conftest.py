"""Shared pytest fixtures.

Keeps tests offline and prevents the user's local .env from leaking into
test behaviour. Mirrors the pattern from the stock side after the
TELEGRAM_BOT_TOKEN-leak incident.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]


# Sensitive env vars that must not influence tests.
_SENSITIVE_ENV_KEYS = (
    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "DEMO_MODE",
    "DATABASE_URL",
    "PAPER_TRADING",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _SENSITIVE_ENV_KEYS:
        monkeypatch.delenv(k, raising=False)
    yield


@pytest.fixture(autouse=True)
def _no_network_news(monkeypatch):
    """Prevent any test from hitting live RSS / news APIs.

    Several callsites import refresh_news lazily (inside functions), so we
    patch every known import path. The replacement returns an empty
    NewsRefreshReport so callers that read .inserted / .by_source still work.
    """
    from crypto_research_watchlist.news.orchestrator import NewsRefreshReport

    def _noop(*args, **kwargs):
        return NewsRefreshReport()

    # Canonical home of refresh_news.
    monkeypatch.setattr(
        "crypto_research_watchlist.news.orchestrator.refresh_news",
        _noop,
        raising=False,
    )
    # Re-exported binding on the news package.
    monkeypatch.setattr(
        "crypto_research_watchlist.news.refresh_news",
        _noop,
        raising=False,
    )
    yield


@pytest.fixture()
def repo_root() -> Path:
    return ROOT


@pytest.fixture()
def env_demo(tmp_path):
    from crypto_research_watchlist.config import EnvSettings
    return EnvSettings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        demo_mode=True,
    )


@pytest.fixture()
def cfg_demo():
    """Tight universe + default thresholds for fast tests."""
    from crypto_research_watchlist.config import load_app_config
    cfg = load_app_config(ROOT / "config.yml")
    cfg.crypto.universe.symbols = ["BTC-USD", "ETH-USD", "SOL-USD"]
    return cfg


@pytest.fixture()
def engine(env_demo):
    from crypto_research_watchlist.db import init_db
    return init_db(env_demo.database_url)


@pytest.fixture()
def synthetic_price_df():
    """A 250-day synthetic OHLCV frame with mild upward drift + volatility."""
    import numpy as np
    rng = np.random.default_rng(42)
    n = 250
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    drift = 0.0008
    vol = 0.03
    log_rets = rng.normal(drift, vol, n)
    close = 100 * pd.Series(log_rets).cumsum().apply(lambda x: float(np.exp(x)))
    df = pd.DataFrame({
        "date": dates,
        "open": close * (1 + rng.normal(0, 0.002, n)),
        "high": close * (1 + np.abs(rng.normal(0, 0.005, n))),
        "low": close * (1 - np.abs(rng.normal(0, 0.005, n))),
        "close": close.values,
        "volume": rng.uniform(1e8, 5e8, n),
    })
    return df
