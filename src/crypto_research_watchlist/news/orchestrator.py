"""Top-level news refresh orchestrator.

Fans out to every configured source, scores sentiment, dedupes, persists.
Best-effort: every source is wrapped in try/except so a single dead feed
does not break the rest.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from . import sources
from .store import upsert_articles

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class NewsRefreshReport:
    inserted: int = 0
    skipped: int = 0
    errors: int = 0
    by_source: dict[str, int] = field(default_factory=dict)


def refresh_news(
    engine,
    cfg,
    *,
    http=None,
    universe_symbols: list[str] | None = None,
) -> NewsRefreshReport:
    """Fetch from every configured source, persist, return a summary report.

    Errors are swallowed: a dead source logs WARNING and the rest of the
    fetch continues. ``http`` is forwarded to every fetcher so tests can
    inject a single mock.
    """
    report = NewsRefreshReport()
    if cfg is not None and universe_symbols is None:
        try:
            universe_symbols = list(cfg.universe.symbols)
        except Exception:
            universe_symbols = None

    fetchers = (
        ("cryptocompare", lambda: sources.fetch_cryptocompare(
            http=http, limit=50,
        )),
        ("coindesk", lambda: sources.fetch_coindesk_rss(http=http, limit=50)),
        ("cointelegraph", lambda: sources.fetch_cointelegraph_rss(http=http, limit=50)),
        ("reddit", lambda: sources.fetch_reddit(http=http, limit=25)),
    )

    all_articles = []
    for name, fn in fetchers:
        try:
            arts = fn() or []
        except Exception as exc:
            logger.warning("news source %s failed: %s", name, exc)
            report.errors += 1
            report.by_source[name] = 0
            continue
        report.by_source[name] = len(arts)
        all_articles.extend(arts)

    # Dedup in-memory by URL before persistence (some sources cross-post).
    seen: dict[str, object] = {}
    for art in all_articles:
        seen.setdefault(art.url, art)
    unique = list(seen.values())

    inserted, skipped = upsert_articles(engine, unique)
    report.inserted = inserted
    report.skipped = skipped
    logger.info(
        "news refresh: %d inserted, %d skipped, sources=%s",
        inserted, skipped, report.by_source,
    )
    return report
