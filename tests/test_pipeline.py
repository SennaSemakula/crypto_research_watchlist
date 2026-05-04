"""End-to-end pipeline test using synthetic price data."""

from __future__ import annotations

import numpy as np
import pandas as pd

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


def test_run_once_produces_candidates_for_each_universe_member(cfg_demo, engine):
    loader = _synthetic_loader()
    result = run_once(cfg=cfg_demo, engine=engine, price_loader=loader, write_report=False)
    syms_in = set(cfg_demo.universe.symbols)
    syms_out = {c.symbol for c in result.candidates}
    assert syms_in == syms_out


def test_run_once_persists_records(cfg_demo, engine):
    from sqlalchemy import select

    from crypto_research_watchlist.db import session_factory, session_scope
    from crypto_research_watchlist.models import CandidateRecord, SignalRecord

    loader = _synthetic_loader(2)
    run_once(cfg=cfg_demo, engine=engine, price_loader=loader, write_report=False)

    SessionLocal = session_factory(engine)
    with session_scope(SessionLocal) as session:
        cands = list(session.scalars(select(CandidateRecord)).all())
        sigs = list(session.scalars(select(SignalRecord)).all())
    assert len(cands) == len(cfg_demo.universe.symbols)
    assert len(sigs) >= len(cfg_demo.universe.symbols)


def test_run_once_writes_markdown_report(cfg_demo, engine, tmp_path, monkeypatch):
    monkeypatch.setattr("crypto_research_watchlist.pipeline.REPO_ROOT", tmp_path)
    cfg_demo.reports.reports_dir = "reports"
    loader = _synthetic_loader(3)
    result = run_once(cfg=cfg_demo, engine=engine, price_loader=loader, write_report=True)
    assert result.report_path is not None
    assert result.report_path.exists()
    text = result.report_path.read_text()
    assert "Crypto Watchlist" in text
