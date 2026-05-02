"""News + sentiment pipeline.

Fetches headlines from CryptoPanic + RSS sources, scores sentiment with
VADER plus a small crypto keyword booster, dedupes on URL, persists to
the news_articles table. Tests are fully offline; live integration tests
under tests/integration/ are opt-in.
"""

from .lookup import recent_articles_for
from .orchestrator import NewsRefreshReport, refresh_news
from .sentiment import score_text
from .sources import NewsArticleDTO

__all__ = [
    "NewsArticleDTO",
    "NewsRefreshReport",
    "recent_articles_for",
    "refresh_news",
    "score_text",
]
