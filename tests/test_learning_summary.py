"""Tests for the weekly learning summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from crypto_research_watchlist.autotrader.learning_summary import (
    build_weekly_summary,
    persist_summary,
    render_markdown,
    render_telegram,
)


def _seed_decisions(engine):
    from crypto_research_watchlist.models import (
        AggressiveDecision as AggressiveDecisionRow,
    )
    from crypto_research_watchlist.models import (
        CandidateRecord,
    )
    from crypto_research_watchlist.models import (
        PassiveDecision as PassiveDecisionRow,
    )
    from sqlalchemy.orm import Session

    now = datetime.now(timezone.utc)
    with Session(engine) as s:
        # This-week decisions.
        for i in range(3):
            s.add(PassiveDecisionRow(
                run_at=now - timedelta(days=i),
                symbol="BTC-USD",
                action="AUTO_BUY_SHADOW",
                accumulation_score=0.5,
                tranche_usd=100.0,
                reasons={"reasons": []}, shadow_mode=1,
            ))
        s.add(AggressiveDecisionRow(
            run_at=now - timedelta(days=1),
            symbol="ETH-USD", action="HOLD", score=0.3,
            prior_action="WATCH", reasons={"reasons": []},
        ))
        # This-week candidates.
        for i in range(2):
            s.add(CandidateRecord(
                run_at=now - timedelta(days=i),
                symbol="BTC-USD", action="STRONG",
                score=0.4, reason="ok", payload={},
            ))
        # Prior-week candidates (used by hit-rate path; need to be 7-14 days old).
        for i in range(2):
            s.add(CandidateRecord(
                run_at=now - timedelta(days=8 + i),
                symbol="BTC-USD", action="WATCH",
                score=0.2, reason="ok", payload={},
            ))
        s.commit()


def test_build_summary_counts_actions(engine):
    _seed_decisions(engine)
    summary = build_weekly_summary(engine=engine, weeks_back=1)
    assert summary.passive_action_counts.get("AUTO_BUY_SHADOW") == 3
    assert summary.aggressive_action_counts.get("HOLD") == 1


def test_render_markdown_includes_sections(engine):
    _seed_decisions(engine)
    summary = build_weekly_summary(engine=engine, weeks_back=1)
    md = render_markdown(summary)
    assert "# Crypto Learning Summary" in md
    assert "## Decision counts" in md
    assert "AUTO_BUY_SHADOW: 3" in md


def test_render_telegram_short_form(engine):
    _seed_decisions(engine)
    summary = build_weekly_summary(engine=engine, weeks_back=1)
    text = render_telegram(summary)
    assert "CRYPTO LEARNING SUMMARY" in text
    assert "Passive" in text


def test_persist_summary_writes_row(engine):
    _seed_decisions(engine)
    summary = build_weekly_summary(engine=engine, weeks_back=1)
    persist_summary(engine, summary)

    from crypto_research_watchlist.models import LearningSummaryRecord
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        rows = s.query(LearningSummaryRecord).all()
    assert len(rows) == 1
    assert "passive_action_counts" in rows[0].payload


def test_hit_rate_back_eval_with_synthetic_parquet(engine, tmp_path, monkeypatch):
    """Construct a tiny parquet, check that fwd-7d hit rate runs."""
    from crypto_research_watchlist.autotrader import learning_summary as ls
    from crypto_research_watchlist.models import CandidateRecord
    from sqlalchemy.orm import Session

    now = datetime.now(timezone.utc)
    # Seed prior-week candidates.
    with Session(engine) as s:
        s.add(CandidateRecord(
            run_at=now - timedelta(days=10),
            symbol="BTC-USD", action="WATCH",
            score=0.2, reason="ok", payload={},
        ))
        s.commit()

    # Build a synthetic parquet with rising prices around (now-10d).
    base = (now - timedelta(days=12)).replace(tzinfo=None)
    rows = []
    for i in range(20):
        rows.append({
            "date": pd.Timestamp(base + timedelta(days=i)),
            "symbol": "BTC-USD",
            "open": 100 + i,
            "high": 100 + i + 1,
            "low": 100 + i - 1,
            "close": 100 + i,
            "volume": 1e8,
        })
    parquet = tmp_path / "prices_daily.parquet"
    pd.DataFrame(rows).to_parquet(parquet)

    # Patch parquet loader to point at the temp file.
    real_loader = ls._try_load_parquet
    monkeypatch.setattr(
        ls, "_try_load_parquet",
        lambda: pd.read_parquet(parquet).assign(date=lambda d: pd.to_datetime(d["date"])),
    )
    summary = build_weekly_summary(engine=engine, weeks_back=1)
    # Forward-7d move should be positive (linear up).
    assert summary.hit_rate_pct is not None
    assert summary.hit_rate_pct >= 50.0
    assert summary.hit_rate_n >= 1
