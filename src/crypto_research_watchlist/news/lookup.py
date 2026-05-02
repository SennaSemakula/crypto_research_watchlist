"""Lookup helpers for the renderer.

`recent_articles_for(symbol, hours, limit)` returns the most recent articles
mentioning a universe symbol, ordered most-recent-first.

`top_catalysts(hours, limit)` returns the highest-magnitude sentiment
articles across the universe in the time window.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import desc, func, or_
from sqlalchemy.orm import Session

from ..models import NewsArticle


def _ticker_from_symbol(symbol: str) -> str:
    return symbol.split("-")[0].upper()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def recent_articles_for(
    engine, symbol: str, *, hours: int = 24, limit: int = 5,
) -> list[NewsArticle]:
    """Return the latest articles tagged with this symbol's ticker."""
    if engine is None or not symbol:
        return []
    ticker = _ticker_from_symbol(symbol)
    cutoff = _now() - timedelta(hours=hours)
    # SQLite JSON support is limited; use LIKE on the json text column as a
    # fallback. SQLAlchemy serialises JSON columns as text in SQLite by default.
    pattern = f'%"{ticker}"%'
    with Session(engine) as session:
        rows = session.query(NewsArticle).filter(
            NewsArticle.published_at >= cutoff,
            func.cast(NewsArticle.currencies_json, type_=NewsArticle.title.type).like(pattern),
        ).order_by(desc(NewsArticle.published_at)).limit(limit).all()
        # Detach so callers can use after the session closes.
        for r in rows:
            session.expunge(r)
    return rows


def top_catalysts(
    engine, *, hours: int = 24, limit: int = 3, min_magnitude: float = 0.3,
) -> list[NewsArticle]:
    """Return the strongest-sentiment articles across all symbols."""
    if engine is None:
        return []
    cutoff = _now() - timedelta(hours=hours)
    with Session(engine) as session:
        rows = session.query(NewsArticle).filter(
            NewsArticle.published_at >= cutoff,
            or_(
                NewsArticle.sentiment_score >= min_magnitude,
                NewsArticle.sentiment_score <= -min_magnitude,
            ),
        ).all()
        rows.sort(key=lambda r: abs(r.sentiment_score), reverse=True)
        rows = rows[:limit]
        for r in rows:
            session.expunge(r)
    return rows


def count_recent(engine, *, hours: int = 24) -> int:
    if engine is None:
        return 0
    cutoff = _now() - timedelta(hours=hours)
    with Session(engine) as session:
        return session.query(NewsArticle).filter(NewsArticle.published_at >= cutoff).count()
