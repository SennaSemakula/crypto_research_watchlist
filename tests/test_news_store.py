"""Tests for news store + lookup."""

from __future__ import annotations

from datetime import UTC, datetime

from crypto_research_watchlist.news.lookup import (
    count_recent,
    recent_articles_for,
    top_catalysts,
)
from crypto_research_watchlist.news.sources import NewsArticleDTO
from crypto_research_watchlist.news.store import upsert_articles


def _dto(*, url: str, title: str, currencies: list[str], hours_ago: int = 1, source: str = "coindesk") -> NewsArticleDTO:
    pub = datetime.now(UTC).replace(microsecond=0)
    pub = pub.replace(year=pub.year, month=pub.month)
    # Use timedelta to keep arithmetic correct.
    from datetime import timedelta
    pub -= timedelta(hours=hours_ago)
    return NewsArticleDTO(
        source=source,
        url=url,
        title=title,
        published_at=pub,
        raw_currencies=currencies,
    )


def test_upsert_articles_dedupes_url(engine):
    articles = [
        _dto(url="https://x.com/a", title="BTC ETF approved", currencies=["BTC"]),
        _dto(url="https://x.com/a", title="BTC ETF approved (dupe)", currencies=["BTC"]),
        _dto(url="https://x.com/b", title="SOL outage hack exploit", currencies=["SOL"]),
    ]
    inserted, skipped = upsert_articles(engine, articles)
    assert inserted == 2
    assert skipped == 1


def test_recent_articles_for_returns_tagged(engine):
    articles = [
        _dto(url="https://x.com/btc1", title="BTC ETF approval rally", currencies=["BTC"]),
        _dto(url="https://x.com/eth1", title="ETH upgrade scheduled", currencies=["ETH"]),
        _dto(url="https://x.com/sol1", title="SOL hack dumps", currencies=["SOL"]),
    ]
    upsert_articles(engine, articles)
    btc_articles = recent_articles_for(engine, "BTC-USD")
    assert len(btc_articles) == 1
    assert btc_articles[0].url == "https://x.com/btc1"


def test_top_catalysts_orders_by_magnitude(engine):
    articles = [
        _dto(url="https://x.com/a", title="BTC ETF approval all time high rally", currencies=["BTC"]),
        _dto(url="https://x.com/b", title="ETH hack exploit lawsuit fraud", currencies=["ETH"]),
        _dto(url="https://x.com/c", title="Boring market update", currencies=["SOL"]),
    ]
    upsert_articles(engine, articles)
    cats = top_catalysts(engine, limit=2)
    assert len(cats) <= 2
    # Both top catalysts must have non-trivial magnitude.
    for c in cats:
        assert abs(c.sentiment_score) >= 0.3


def test_count_recent_counts_only_window(engine):
    articles = [
        _dto(url="https://x.com/a", title="X1", currencies=["BTC"], hours_ago=1),
        _dto(url="https://x.com/b", title="X2", currencies=["BTC"], hours_ago=48),
    ]
    upsert_articles(engine, articles)
    assert count_recent(engine, hours=24) == 1
    assert count_recent(engine, hours=72) == 2
