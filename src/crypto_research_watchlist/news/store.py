"""Persistence for news articles.

URL-keyed dedup. Insert-or-skip semantics; we never update an existing
row (publishers occasionally edit the title, but for our research log
the first-fetched version is fine).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import NewsArticle
from .sentiment import score_text
from .sources import NewsArticleDTO

logger = logging.getLogger(__name__)


def upsert_articles(engine, articles: list[NewsArticleDTO]) -> tuple[int, int]:
    """Persist articles to the news_articles table.

    Scores sentiment if not already attached. Dedupes on URL.
    Returns (inserted, skipped).
    """
    if engine is None or not articles:
        return 0, 0
    inserted = 0
    skipped = 0
    with Session(engine) as session:
        for art in articles:
            text_for_score = art.title
            if art.body:
                text_for_score = f"{art.title}. {art.body[:500]}"
            sent = score_text(text_for_score)
            # Use PEP 249-style "INSERT OR IGNORE" semantics.
            existing = session.query(NewsArticle).filter(NewsArticle.url == art.url).first()
            if existing is not None:
                skipped += 1
                continue
            row = NewsArticle(
                url=art.url[:1024],
                source=art.source,
                title=art.title[:1024],
                body=(art.body or "")[:8192] or None,
                published_at=_aware(art.published_at),
                fetched_at=datetime.now(UTC),
                currencies_json=list(art.raw_currencies),
                sentiment_score=float(sent.score),
                sentiment_label=sent.label,
                raw=art.raw or {},
            )
            try:
                session.add(row)
                session.commit()
                inserted += 1
            except IntegrityError:
                session.rollback()
                skipped += 1
            except Exception as exc:
                logger.warning("upsert article failed for %s: %s", art.url, exc)
                session.rollback()
    return inserted, skipped


def _aware(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt
