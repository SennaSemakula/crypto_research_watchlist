"""Tests for the per-signal diagnose command.

The diagnose command must:
  1. Run end-to-end against synthetic price data without network calls.
  2. Print a per-signal explanation for every symbol it scans.
  3. Surface NO_DATA explicitly when a provider returned None.
  4. Surface the parquet freshness so stale-data bugs are visible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from typer.testing import CliRunner

from crypto_research_watchlist.cli import app
from crypto_research_watchlist.config import EnvSettings, load_app_config
from crypto_research_watchlist.diagnose import run_diagnose


def _synth_loader(seed: int = 1):
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


def test_run_diagnose_explains_each_signal(repo_root):
    cfg = load_app_config(repo_root / "config.yml")
    cfg.crypto.universe.symbols = ["BTC-USD", "ETH-USD"]
    env = EnvSettings()  # all keys None

    text = run_diagnose(
        cfg=cfg,
        env=env,
        price_loader=_synth_loader(),
        funding_loader=lambda _s: None,
        oi_loader=lambda _s: {},
        onchain_loader=lambda _s: {},
    )

    # Header shows freshness + thresholds.
    assert "parquet:" in text
    assert "thresholds:" in text

    # Per-symbol blocks.
    assert "BTC-USD" in text
    assert "ETH-USD" in text

    # Every signal name should appear at least once per symbol.
    for sig_name in ("technical", "funding_rate", "open_interest", "onchain", "cross_asset"):
        assert sig_name in text, f"diagnose did not mention {sig_name}"

    # When loaders return nothing, NO_DATA must be surfaced (not a misleading
    # "neutral").
    assert "NO_DATA" in text


def test_run_diagnose_shows_funding_value_when_present(repo_root):
    cfg = load_app_config(repo_root / "config.yml")
    cfg.crypto.universe.symbols = ["BTC-USD"]
    env = EnvSettings()

    text = run_diagnose(
        cfg=cfg,
        env=env,
        price_loader=_synth_loader(),
        funding_loader=lambda _s: [0.0001, 0.0002, 0.0001],
        oi_loader=lambda _s: {},
        onchain_loader=lambda _s: {},
    )
    # Either median_8h appears or NEUTRAL is recorded with a strength.
    assert "median_8h" in text or "funding_rate:" in text


def test_diagnose_cli_command_runs(monkeypatch, repo_root, tmp_path):
    """Smoke: the CLI subcommand wiring works end-to-end."""
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'd.db'}")

    from crypto_research_watchlist import diagnose as diag_mod

    def _fake_run(*, cfg, env, symbols=None, **kwargs):
        return f"DIAGNOSE OK symbols={symbols}"

    monkeypatch.setattr(diag_mod, "run_diagnose", _fake_run)
    # The CLI imports run_diagnose lazily inside the subcommand body, so
    # patch the module attribute the import will resolve to.
    import crypto_research_watchlist.cli as cli_mod
    monkeypatch.setattr(cli_mod, "load_app_config", lambda: load_app_config(repo_root / "config.yml"))

    runner = CliRunner()
    res = runner.invoke(app, ["diagnose", "--symbols", "BTC-USD"])
    assert res.exit_code == 0, res.output
    assert "DIAGNOSE OK" in res.output
    assert "BTC-USD" in res.output
