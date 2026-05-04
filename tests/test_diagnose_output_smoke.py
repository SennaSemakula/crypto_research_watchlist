"""Smoke test that runs the diagnose command against the real parquet
+ stub providers, prints the output, so the operator can sanity-check
what the diagnose explainer says for BTC and ETH after the signal fixes.

This is a smoke test, not a validation test: it prints and asserts
basic shape only. Useful for capturing the per-signal explanation in
CI logs / final reports.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from crypto_research_watchlist.config import EnvSettings, load_app_config
from crypto_research_watchlist.diagnose import run_diagnose
from crypto_research_watchlist.pipeline import parquet_price_loader


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_diagnose_against_parquet_for_btc_and_eth():
    parquet = REPO_ROOT / "data" / "historical" / "prices_daily.parquet"
    if not parquet.exists():
        pytest.skip("no parquet to diagnose against")

    cfg = load_app_config(REPO_ROOT / "config.yml")
    cfg.crypto.universe.symbols = ["BTC-USD", "ETH-USD"]

    text = run_diagnose(
        cfg=cfg,
        env=EnvSettings(),
        price_loader=parquet_price_loader(parquet),
        funding_loader=lambda _s: None,    # no funding provider in test
        oi_loader=lambda _s: {},            # no OI provider in test
        onchain_loader=lambda _s: {},        # no on-chain provider in test
    )
    # Persist a copy so the operator can paste into the final report.
    out_path = REPO_ROOT / "data" / "historical" / "diagnose_btc_eth.txt"
    out_path.write_text(text)

    # Also render the institutional Telegram message for today's data
    # (full universe) so the operator sees what would actually go out.
    from crypto_research_watchlist.notifiers.telegram import render_html
    from crypto_research_watchlist.pipeline import run_once

    full_cfg = load_app_config(REPO_ROOT / "config.yml")
    result = run_once(
        cfg=full_cfg,
        engine=None,
        price_loader=parquet_price_loader(parquet),
        funding_loader=lambda _s: None,
        oi_loader=lambda _s: {},
        onchain_loader=lambda _s: {},
        market_loader=lambda: None,
        write_report=False,
        refresh_news=False,
    )
    html = render_html(result)
    sample_path = REPO_ROOT / "data" / "historical" / "telegram_sample_today.html"
    sample_path.write_text(html)
    print("\n--- diagnose output (parquet + stub providers) ---")
    print(text)
    assert "BTC-USD" in text
    assert "ETH-USD" in text
    assert "technical:" in text
    assert "cross_asset:" in text
