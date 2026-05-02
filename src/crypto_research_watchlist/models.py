"""ORM models. SQLite-friendly schema covering signals, candidates and
paper-trading state. Schema is small on purpose: persistence is for
auditability, not analytics.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SignalRecord(Base):
    """One row per (symbol, source, run_at). The aggregator looks up the
    latest run per symbol to assemble a candidate."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=0.0)
    label: Mapped[str] = mapped_column(String(32), default="NEUTRAL")
    details: Mapped[dict] = mapped_column(JSON, default=dict)

    __table_args__ = (UniqueConstraint("run_at", "symbol", "source", name="uq_signal_run_symbol_source"),)


class CandidateRecord(Base):
    """A scored candidate produced by the pipeline for one symbol on one run."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)  # STRONG / WATCH / AVOID
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reason: Mapped[str] = mapped_column(String(512), default="")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)


class PaperOrder(Base):
    """Paper-broker order. Idempotency by client_order_key."""

    __tablename__ = "paper_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    placed_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    client_order_key: Mapped[str] = mapped_column(String(96), unique=True, nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)  # BUY / SELL
    order_type: Mapped[str] = mapped_column(String(16), default="MARKET")
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    limit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING")  # PENDING / FILLED / REJECTED


class PaperPosition(Base):
    """Net position per symbol. There is exactly one row per symbol; the
    paper broker upserts on each fill."""

    __tablename__ = "paper_positions"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    avg_price: Mapped[float] = mapped_column(Float, default=0.0)
    realised_pnl: Mapped[float] = mapped_column(Float, default=0.0)
    last_update: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PaperCash(Base):
    """Single-row table holding the paper portfolio's cash position."""

    __tablename__ = "paper_cash"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    cash_usd: Mapped[float] = mapped_column(Float, default=0.0)
    last_update: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PassiveDecision(Base):
    """One row per passive-engine decision. Append-only audit trail.

    Mirrors the stock side's AutoTrade journal pattern, scaled down: we
    do not actually place orders in v1 (paper / shadow only) so storing
    the action + reasons + sizing is sufficient for back-evaluation.
    """

    __tablename__ = "passive_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    accumulation_score: Mapped[float] = mapped_column(Float, default=0.0)
    tranche_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)
    shadow_mode: Mapped[bool] = mapped_column(Integer, default=1)


class AggressiveDecision(Base):
    """One row per aggressive-engine decision."""

    __tablename__ = "aggressive_decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    prior_action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reasons: Mapped[dict] = mapped_column(JSON, default=dict)


class NewsArticle(Base):
    """One row per ingested news headline. Dedup on URL.

    Sentiment is precomputed at ingest so renderers can render quickly without
    re-scoring. ``currencies_json`` is a JSON list of ticker symbols mentioned
    (uppercase, no -USD suffix).
    """

    __tablename__ = "news_articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    body: Mapped[str | None] = mapped_column(String(8192), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    currencies_json: Mapped[list] = mapped_column(JSON, default=list)
    sentiment_score: Mapped[float] = mapped_column(Float, default=0.0)
    sentiment_label: Mapped[str] = mapped_column(String(16), default="neutral")
    raw: Mapped[dict] = mapped_column(JSON, default=dict)


class LearningSummaryRecord(Base):
    """Weekly digest snapshot. payload holds the full structured summary."""

    __tablename__ = "learning_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    week_ending: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
